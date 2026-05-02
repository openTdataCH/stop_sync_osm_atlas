import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis import Redis
from redis.exceptions import RedisError

_STATUS_KEY = "pipeline:update:status"
_LOCK_KEY = "pipeline:update:lock"
_DEFAULT_LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))

_STATE_LOCK = threading.Lock()
_FALLBACK_STATE: Dict[str, Any] = {}
_FALLBACK_LOCK_TOKEN: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_status() -> Dict[str, Any]:
    return {
        "status": "idle",
        "phase": "idle",
        "message": "No update running",
        "blocking_maintenance": False,
        "processed": None,
        "total": None,
        "eta_seconds": None,
        "run_id": None,
        "trigger": None,
        "started_at": None,
        "maintenance_started_at": None,
        "updated_at": _now_iso(),
        "finished_at": None,
        "last_success_at": None,
        "last_error": None,
        "data_updated_at": None,
        "next_run_at": None,
    }


def _get_redis_client() -> Optional[Redis]:
    uri = os.getenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/0")
    try:
        client = Redis.from_url(uri, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _read_raw_status() -> Dict[str, Any]:
    client = _get_redis_client()
    if client:
        try:
            payload = client.get(_STATUS_KEY)
            if payload:
                data = json.loads(payload)
                if isinstance(data, dict):
                    return data
        except (RedisError, json.JSONDecodeError):
            pass
    with _STATE_LOCK:
        return dict(_FALLBACK_STATE) if _FALLBACK_STATE else {}


def _write_raw_status(payload: Dict[str, Any]) -> None:
    client = _get_redis_client()
    if client:
        try:
            client.set(_STATUS_KEY, json.dumps(payload))
            return
        except RedisError:
            pass
    with _STATE_LOCK:
        _FALLBACK_STATE.clear()
        _FALLBACK_STATE.update(payload)


def get_status() -> Dict[str, Any]:
    raw = _read_raw_status()
    data = _base_status()
    data.update(raw)
    if "blocking_maintenance" not in raw and "maintenance" in raw:
        data["blocking_maintenance"] = bool(raw.get("maintenance"))
    data.pop("maintenance", None)
    data["updated_at"] = data.get("updated_at") or _now_iso()
    if not data.get("data_updated_at"):
        try:
            from backend.services.stats_export import load_stats_from_file

            stats = load_stats_from_file() or {}
            data["data_updated_at"] = stats.get("data_updated_at")
        except Exception:
            pass
    return data


def set_status(**fields: Any) -> Dict[str, Any]:
    current = get_status()

    current_blocking = bool(current.get("blocking_maintenance", False))
    incoming_blocking = fields.get("blocking_maintenance")
    if incoming_blocking is None:
        incoming_blocking = fields.get("maintenance", current_blocking)
    incoming_blocking = bool(incoming_blocking)

    fields.pop("maintenance", None)
    fields["blocking_maintenance"] = incoming_blocking

    # If starting blocking maintenance mode, record the start time for UI counters.
    if incoming_blocking and not current_blocking:
        fields["maintenance_started_at"] = _now_iso()
    # If leaving blocking maintenance mode, clear the start time.
    elif not incoming_blocking and current_blocking:
        fields["maintenance_started_at"] = None

    current.update(fields)
    current.pop("maintenance", None)
    current["updated_at"] = _now_iso()
    _write_raw_status(current)
    return current


def start_run(trigger: str, run_id: Optional[str] = None) -> str:
    run_identifier = run_id or str(uuid.uuid4())
    set_status(
        status="running",
        phase="initializing",
        message="Initializing pipeline run",
        blocking_maintenance=False,
        processed=None,
        total=None,
        eta_seconds=None,
        run_id=run_identifier,
        trigger=trigger,
        started_at=_now_iso(),
        finished_at=None,
        last_error=None,
    )
    return run_identifier


def set_phase(
    phase: str,
    message: str,
    *,
    maintenance: bool = False,
    blocking_maintenance: Optional[bool] = None,
    processed: Optional[int] = None,
    total: Optional[int] = None,
    eta_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    effective_blocking = maintenance if blocking_maintenance is None else blocking_maintenance
    return set_status(
        status="running",
        phase=phase,
        message=message,
        blocking_maintenance=effective_blocking,
        processed=processed,
        total=total,
        eta_seconds=eta_seconds,
    )


def finish_success(message: str = "Pipeline update completed") -> Dict[str, Any]:
    ts = _now_iso()
    return set_status(
        status="idle",
        phase="idle",
        message=message,
        blocking_maintenance=False,
        processed=None,
        total=None,
        eta_seconds=None,
        finished_at=ts,
        last_success_at=ts,
        last_error=None,
    )


def finish_failure(error_message: str) -> Dict[str, Any]:
    ts = _now_iso()
    return set_status(
        status="failed",
        phase="failed",
        message="Pipeline update failed",
        blocking_maintenance=False,
        finished_at=ts,
        last_error=error_message,
    )


def set_next_run(next_run_at: Optional[str]) -> Dict[str, Any]:
    return set_status(next_run_at=next_run_at)


def set_data_updated(data_updated_at: Optional[str]) -> Dict[str, Any]:
    return set_status(data_updated_at=data_updated_at)


def acquire_run_lock(ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS) -> Optional[str]:
    token = str(uuid.uuid4())
    client = _get_redis_client()
    if client:
        try:
            ok = client.set(_LOCK_KEY, token, nx=True, ex=max(1, ttl_seconds))
            if ok:
                return token

            # Recover from stale lock when persisted status says no run is active.
            status = get_status().get("status")
            if status != "running":
                client.delete(_LOCK_KEY)
                ok = client.set(_LOCK_KEY, token, nx=True, ex=max(1, ttl_seconds))
                if ok:
                    return token

            return None
        except RedisError:
            pass

    global _FALLBACK_LOCK_TOKEN
    with _STATE_LOCK:
        if _FALLBACK_LOCK_TOKEN is not None:
            return None
        _FALLBACK_LOCK_TOKEN = token
        return token


def refresh_run_lock(token: str, ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS) -> None:
    client = _get_redis_client()
    if client:
        try:
            if client.get(_LOCK_KEY) == token:
                client.expire(_LOCK_KEY, max(1, ttl_seconds))
        except RedisError:
            pass


def release_run_lock(token: str) -> None:
    client = _get_redis_client()
    if client:
        try:
            pipe = client.pipeline(True)
            while True:
                try:
                    pipe.watch(_LOCK_KEY)
                    current = pipe.get(_LOCK_KEY)
                    if current != token:
                        pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(_LOCK_KEY)
                    pipe.execute()
                    return
                except RedisError:
                    time.sleep(0.05)
                    continue
        except RedisError:
            pass

    global _FALLBACK_LOCK_TOKEN
    with _STATE_LOCK:
        if _FALLBACK_LOCK_TOKEN == token:
            _FALLBACK_LOCK_TOKEN = None
