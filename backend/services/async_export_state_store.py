import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, Protocol

from redis import Redis

from backend.services.state_backend_config import (
    resolve_state_backend,
    resolve_state_dir,
    resolve_state_redis_url,
)

_PROGRESS_PATH = "tasks_progress.json"
_COMPLETED_PATH = "tasks_completed.json"
_GUARD_PATH = "tasks.guard"

_REDIS_PROGRESS_KEY_PREFIX = "async_export:progress"
_REDIS_COMPLETED_KEY_PREFIX = "async_export:completed"
_REDIS_PROGRESS_IDS_KEY = "async_export:progress_ids"
_REDIS_COMPLETED_IDS_KEY = "async_export:completed_ids"


def _read_json_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    parent = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = handle.name
    os.replace(temp_path, path)


def _normalize_mapping(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized[key] = value
    return normalized


def _parse_iso_timestamp(value: Any) -> datetime | None:
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


def parse_created_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return _parse_iso_timestamp(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AsyncExportStateStore(Protocol):
    def read_progress(self, task_id: str) -> Dict[str, Any] | None: ...

    def write_progress(self, task_id: str, payload: Dict[str, Any]) -> None: ...

    def list_progress(self) -> Dict[str, Dict[str, Any]]: ...

    def delete_progress(self, task_id: str) -> None: ...

    def read_completed(self, task_id: str) -> Dict[str, Any] | None: ...

    def write_completed(self, task_id: str, payload: Dict[str, Any]) -> None: ...

    def list_completed(self) -> Dict[str, Dict[str, Any]]: ...

    def delete_completed(self, task_id: str) -> None: ...


class RedisAsyncExportStateStore:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url

    def _client(self) -> Redis:
        return Redis.from_url(self._redis_url, decode_responses=True)

    @staticmethod
    def _progress_key(task_id: str) -> str:
        return f"{_REDIS_PROGRESS_KEY_PREFIX}:{task_id}"

    @staticmethod
    def _completed_key(task_id: str) -> str:
        return f"{_REDIS_COMPLETED_KEY_PREFIX}:{task_id}"

    def read_progress(self, task_id: str) -> Dict[str, Any] | None:
        payload = self._client().get(self._progress_key(task_id))
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def write_progress(self, task_id: str, payload: Dict[str, Any]) -> None:
        client = self._client()
        client.set(self._progress_key(task_id), json.dumps(payload))
        client.sadd(_REDIS_PROGRESS_IDS_KEY, task_id)

    def list_progress(self) -> Dict[str, Dict[str, Any]]:
        client = self._client()
        task_ids = client.smembers(_REDIS_PROGRESS_IDS_KEY) or set()
        progress: Dict[str, Dict[str, Any]] = {}
        stale_ids = []
        for task_id in task_ids:
            payload = client.get(self._progress_key(task_id))
            if not payload:
                stale_ids.append(task_id)
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                stale_ids.append(task_id)
                continue
            if isinstance(data, dict):
                progress[task_id] = data
        if stale_ids:
            client.srem(_REDIS_PROGRESS_IDS_KEY, *stale_ids)
        return progress

    def delete_progress(self, task_id: str) -> None:
        client = self._client()
        client.delete(self._progress_key(task_id))
        client.srem(_REDIS_PROGRESS_IDS_KEY, task_id)

    def read_completed(self, task_id: str) -> Dict[str, Any] | None:
        payload = self._client().get(self._completed_key(task_id))
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def write_completed(self, task_id: str, payload: Dict[str, Any]) -> None:
        client = self._client()
        client.set(self._completed_key(task_id), json.dumps(payload))
        client.sadd(_REDIS_COMPLETED_IDS_KEY, task_id)

    def list_completed(self) -> Dict[str, Dict[str, Any]]:
        client = self._client()
        task_ids = client.smembers(_REDIS_COMPLETED_IDS_KEY) or set()
        completed: Dict[str, Dict[str, Any]] = {}
        stale_ids = []
        for task_id in task_ids:
            payload = client.get(self._completed_key(task_id))
            if not payload:
                stale_ids.append(task_id)
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                stale_ids.append(task_id)
                continue
            if isinstance(data, dict):
                completed[task_id] = data
        if stale_ids:
            client.srem(_REDIS_COMPLETED_IDS_KEY, *stale_ids)
        return completed

    def delete_completed(self, task_id: str) -> None:
        client = self._client()
        client.delete(self._completed_key(task_id))
        client.srem(_REDIS_COMPLETED_IDS_KEY, task_id)


class FileAsyncExportStateStore:
    def __init__(self, runtime_dir: str):
        self._progress_path = os.path.join(runtime_dir, _PROGRESS_PATH)
        self._completed_path = os.path.join(runtime_dir, _COMPLETED_PATH)
        self._guard_path = os.path.join(runtime_dir, _GUARD_PATH)

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

    def read_progress(self, task_id: str) -> Dict[str, Any] | None:
        with self._guard_lock():
            return _normalize_mapping(_read_json_file(self._progress_path)).get(task_id)

    def write_progress(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._guard_lock():
            progress = _normalize_mapping(_read_json_file(self._progress_path))
            progress[task_id] = payload
            _atomic_write_json(self._progress_path, progress)

    def list_progress(self) -> Dict[str, Dict[str, Any]]:
        with self._guard_lock():
            return _normalize_mapping(_read_json_file(self._progress_path))

    def delete_progress(self, task_id: str) -> None:
        with self._guard_lock():
            progress = _normalize_mapping(_read_json_file(self._progress_path))
            progress.pop(task_id, None)
            _atomic_write_json(self._progress_path, progress)

    def read_completed(self, task_id: str) -> Dict[str, Any] | None:
        with self._guard_lock():
            return _normalize_mapping(_read_json_file(self._completed_path)).get(task_id)

    def write_completed(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._guard_lock():
            completed = _normalize_mapping(_read_json_file(self._completed_path))
            completed[task_id] = payload
            _atomic_write_json(self._completed_path, completed)

    def list_completed(self) -> Dict[str, Dict[str, Any]]:
        with self._guard_lock():
            return _normalize_mapping(_read_json_file(self._completed_path))

    def delete_completed(self, task_id: str) -> None:
        with self._guard_lock():
            completed = _normalize_mapping(_read_json_file(self._completed_path))
            completed.pop(task_id, None)
            _atomic_write_json(self._completed_path, completed)


class MemoryAsyncExportStateStore:
    def __init__(self):
        self._state_lock = threading.Lock()
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._completed: Dict[str, Dict[str, Any]] = {}

    def read_progress(self, task_id: str) -> Dict[str, Any] | None:
        with self._state_lock:
            payload = self._progress.get(task_id)
            return dict(payload) if payload else None

    def write_progress(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._state_lock:
            self._progress[task_id] = dict(payload)

    def list_progress(self) -> Dict[str, Dict[str, Any]]:
        with self._state_lock:
            return {task_id: dict(payload) for task_id, payload in self._progress.items()}

    def delete_progress(self, task_id: str) -> None:
        with self._state_lock:
            self._progress.pop(task_id, None)

    def read_completed(self, task_id: str) -> Dict[str, Any] | None:
        with self._state_lock:
            payload = self._completed.get(task_id)
            return dict(payload) if payload else None

    def write_completed(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._state_lock:
            self._completed[task_id] = dict(payload)

    def list_completed(self) -> Dict[str, Dict[str, Any]]:
        with self._state_lock:
            return {task_id: dict(payload) for task_id, payload in self._completed.items()}

    def delete_completed(self, task_id: str) -> None:
        with self._state_lock:
            self._completed.pop(task_id, None)


_MEMORY_STORE = MemoryAsyncExportStateStore()


def resolve_backend_name() -> str:
    return resolve_state_backend()


def get_async_export_state_store() -> AsyncExportStateStore:
    backend = resolve_backend_name()
    if backend == "redis":
        redis_url = resolve_state_redis_url()
        if not redis_url:
            raise RuntimeError("STATE_REDIS_URL is required when STATE_BACKEND=redis")
        return RedisAsyncExportStateStore(redis_url)
    if backend == "file":
        return FileAsyncExportStateStore(resolve_state_dir())
    if backend == "memory":
        return _MEMORY_STORE
    raise RuntimeError(f"Unsupported STATE_BACKEND: {backend}")
