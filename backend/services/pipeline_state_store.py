import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, Protocol

from redis import Redis
from redis.exceptions import RedisError

_STATUS_KEY = "pipeline:update:status"
_LOCK_KEY = "pipeline:update:lock"
_DEFAULT_RUNTIME_DIR = os.path.join("data", "runtime")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_iso(ttl_seconds: int) -> str:
    return (_now_utc() + timedelta(seconds=max(1, ttl_seconds))).isoformat()


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_json_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    parent = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = handle.name
    os.replace(temp_path, path)


def _parse_expiry(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_dir() -> str:
    return os.getenv("PIPELINE_STATE_DIR", _DEFAULT_RUNTIME_DIR)


class PipelineStateStore(Protocol):
    def read_status(self) -> Dict[str, Any]: ...

    def write_status(self, payload: Dict[str, Any]) -> None: ...

    def read_lock(self) -> Dict[str, Any]: ...

    def acquire_lock(self, token: str, ttl_seconds: int) -> bool: ...

    def refresh_lock(self, token: str, ttl_seconds: int) -> None: ...

    def release_lock(self, token: str) -> None: ...

    def clear_lock(self) -> None: ...


class RedisPipelineStateStore:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url

    def _client(self) -> Redis:
        return Redis.from_url(self._redis_url, decode_responses=True)

    def read_status(self) -> Dict[str, Any]:
        try:
            payload = self._client().get(_STATUS_KEY)
        except RedisError:
            return {}
        if not payload:
            return {}
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def read_lock(self) -> Dict[str, Any]:
        try:
            payload = self._client().get(_LOCK_KEY)
        except RedisError:
            return {}
        if not payload:
            return {}
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {"token": payload}
        return data if isinstance(data, dict) else {}

    def write_status(self, payload: Dict[str, Any]) -> None:
        self._client().set(_STATUS_KEY, json.dumps(payload))

    def acquire_lock(self, token: str, ttl_seconds: int) -> bool:
        payload = json.dumps({"token": token, "acquired_at": _now_utc().isoformat()})
        return bool(self._client().set(_LOCK_KEY, payload, nx=True, ex=max(1, ttl_seconds)))

    def refresh_lock(self, token: str, ttl_seconds: int) -> None:
        client = self._client()
        current = self.read_lock()
        if current.get("token") == token:
            client.expire(_LOCK_KEY, max(1, ttl_seconds))

    def release_lock(self, token: str) -> None:
        client = self._client()
        pipe = client.pipeline(True)
        while True:
            try:
                pipe.watch(_LOCK_KEY)
                current = pipe.get(_LOCK_KEY)
                if not current:
                    pipe.unwatch()
                    return
                try:
                    current_payload = json.loads(current)
                except json.JSONDecodeError:
                    current_payload = {"token": current}
                if current_payload.get("token") != token:
                    pipe.unwatch()
                    return
                pipe.multi()
                pipe.delete(_LOCK_KEY)
                pipe.execute()
                return
            except RedisError:
                continue

    def clear_lock(self) -> None:
        self._client().delete(_LOCK_KEY)


class FilePipelineStateStore:
    def __init__(self, runtime_dir: str):
        self._status_path = os.path.join(runtime_dir, "pipeline_status.json")
        self._lock_path = os.path.join(runtime_dir, "pipeline_lock.json")
        self._guard_path = os.path.join(runtime_dir, "pipeline_lock.guard")

    @contextmanager
    def _guard_lock(self) -> Iterator[None]:
        import fcntl

        _ensure_parent_dir(self._guard_path)
        with open(self._guard_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read_status(self) -> Dict[str, Any]:
        return _read_json_file(self._status_path)

    def read_lock(self) -> Dict[str, Any]:
        with self._guard_lock():
            return _read_json_file(self._lock_path)

    def write_status(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(self._status_path, payload)

    def acquire_lock(self, token: str, ttl_seconds: int) -> bool:
        with self._guard_lock():
            current = _read_json_file(self._lock_path)
            expires_at = _parse_expiry(current.get("expires_at"))
            if current.get("token") and expires_at and expires_at > _now_utc():
                return False
            _atomic_write_json(
                self._lock_path,
                {
                    "token": token,
                    "acquired_at": _now_utc().isoformat(),
                    "expires_at": _expiry_iso(ttl_seconds),
                },
            )
            return True

    def refresh_lock(self, token: str, ttl_seconds: int) -> None:
        with self._guard_lock():
            current = _read_json_file(self._lock_path)
            if current.get("token") != token:
                return
            _atomic_write_json(
                self._lock_path,
                {
                    "token": token,
                    "acquired_at": current.get("acquired_at") or _now_utc().isoformat(),
                    "expires_at": _expiry_iso(ttl_seconds),
                },
            )

    def release_lock(self, token: str) -> None:
        with self._guard_lock():
            current = _read_json_file(self._lock_path)
            if current.get("token") != token:
                return
            try:
                os.remove(self._lock_path)
            except FileNotFoundError:
                return

    def clear_lock(self) -> None:
        with self._guard_lock():
            try:
                os.remove(self._lock_path)
            except FileNotFoundError:
                return


class MemoryPipelineStateStore:
    def __init__(self):
        self._state_lock = threading.Lock()
        self._status: Dict[str, Any] = {}
        self._lock_state: Dict[str, Any] = {}

    def read_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._status)

    def write_status(self, payload: Dict[str, Any]) -> None:
        with self._state_lock:
            self._status.clear()
            self._status.update(payload)

    def read_lock(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._lock_state)

    def acquire_lock(self, token: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        with self._state_lock:
            if self._lock_state.get("token") is not None:
                return False
            self._lock_state = {"token": token, "acquired_at": _now_utc().isoformat()}
            return True

    def refresh_lock(self, token: str, ttl_seconds: int) -> None:
        del token, ttl_seconds

    def release_lock(self, token: str) -> None:
        with self._state_lock:
            if self._lock_state.get("token") == token:
                self._lock_state = {}

    def clear_lock(self) -> None:
        with self._state_lock:
            self._lock_state = {}


_MEMORY_STORE = MemoryPipelineStateStore()


def _resolve_backend_name() -> str:
    configured = (os.getenv("PIPELINE_STATE_BACKEND") or "").strip().lower()
    if configured:
        return configured

    if os.getenv("PIPELINE_STATE_REDIS_URL"):
        return "redis"

    return "file"


def get_pipeline_state_store() -> PipelineStateStore:
    backend = _resolve_backend_name()
    if backend == "redis":
        redis_url = os.getenv("PIPELINE_STATE_REDIS_URL")
        if not redis_url:
            raise RuntimeError("PIPELINE_STATE_REDIS_URL is required when PIPELINE_STATE_BACKEND=redis")
        return RedisPipelineStateStore(redis_url)
    if backend == "file":
        return FilePipelineStateStore(_runtime_dir())
    if backend == "memory":
        return _MEMORY_STORE
    raise RuntimeError(f"Unsupported PIPELINE_STATE_BACKEND: {backend}")