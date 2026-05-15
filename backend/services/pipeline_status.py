import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis.exceptions import RedisError

from backend.services.pipeline_state_store import get_pipeline_state_store

_DEFAULT_LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        "last_pipeline_data_import_ended_at": None,
        "next_run_at": None,
        "run_type": None,
        "refresh_scope_tables_rewritten": [],
        "refresh_scope_tables_reused": [],
    }


def _read_raw_status() -> Dict[str, Any]:
    try:
        return get_pipeline_state_store().read_status()
    except (RedisError, RuntimeError):
        return {}


def _write_raw_status(payload: Dict[str, Any]) -> None:
    try:
        get_pipeline_state_store().write_status(payload)
    except (RedisError, RuntimeError):
        return


def get_status() -> Dict[str, Any]:
    raw = _read_raw_status()
    data = _base_status()
    data.update(raw)
    if "blocking_maintenance" not in raw and "maintenance" in raw:
        data["blocking_maintenance"] = bool(raw.get("maintenance"))
    data.pop("maintenance", None)
    data["updated_at"] = data.get("updated_at") or _now_iso()
    if not data.get("last_pipeline_data_import_ended_at"):
        try:
            from backend.services.stats_export import load_stats_from_file
            
            stats = load_stats_from_file() or {}
            data["last_pipeline_data_import_ended_at"] = stats.get("last_pipeline_data_import_ended_at") or stats.get("data_updated_at")
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


def set_data_updated(last_pipeline_data_import_ended_at: Optional[str]) -> Dict[str, Any]:
    return set_status(last_pipeline_data_import_ended_at=last_pipeline_data_import_ended_at)


def acquire_run_lock(ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS) -> Optional[str]:
    token = str(uuid.uuid4())
    try:
        store = get_pipeline_state_store()
        if store.acquire_lock(token, ttl_seconds=max(1, ttl_seconds)):
            return token

        status = get_status()
        lock_state = store.read_lock()
        lock_acquired_at = _parse_iso_timestamp(lock_state.get("acquired_at"))
        status_updated_at = _parse_iso_timestamp(status.get("updated_at"))
        should_clear_stale_lock = (
            status.get("status") != "running"
            and lock_acquired_at is not None
            and status_updated_at is not None
            and status_updated_at >= lock_acquired_at
        )
        if should_clear_stale_lock:
            store.clear_lock()
            if store.acquire_lock(token, ttl_seconds=max(1, ttl_seconds)):
                return token
    except (RedisError, RuntimeError):
        return None

    return None


def refresh_run_lock(token: str, ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS) -> None:
    try:
        get_pipeline_state_store().refresh_lock(token, ttl_seconds=max(1, ttl_seconds))
    except (RedisError, RuntimeError):
        return


def release_run_lock(token: str) -> None:
    try:
        get_pipeline_state_store().release_lock(token)
    except (RedisError, RuntimeError):
        return
