import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from redis.exceptions import RedisError

from backend.services.pipeline_progress import (
    PROGRESS_SCHEMA_VERSION,
    PIPELINE_PHASE_STAGES,
    initial_progress_plan,
    apply_progress_event,
    phase_fields,
    project_stage_states,
    finalize_stage_states,
)
from backend.services.pipeline_state_store import get_pipeline_state_store

_DEFAULT_LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))
_DEFAULT_HEARTBEAT_SECONDS = int(
    os.getenv("PIPELINE_LOCK_HEARTBEAT_SECONDS", str(max(5, min(60, _DEFAULT_LOCK_TTL_SECONDS // 4))))
)
_DEFAULT_STALE_SECONDS = int(
    os.getenv("PIPELINE_LOCK_STALE_SECONDS", str(max(30, (_DEFAULT_HEARTBEAT_SECONDS * 2) + 15)))
)

PIPELINE_PHASES = [stage.id for stage in PIPELINE_PHASE_STAGES]


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


def _process_start_ticks(pid: int) -> str | None:
    """Return Linux process start ticks, which disambiguate reused PIDs."""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            raw = handle.read()
    except (FileNotFoundError, OSError, PermissionError):
        return None
    try:
        fields_after_name = raw.rsplit(")", 1)[1].strip().split()
        return fields_after_name[19]
    except (IndexError, ValueError):
        return None


def _runtime_instance_id() -> str | None:
    """Identify the current PID namespace/container lifetime."""
    try:
        with open("/proc/sys/kernel/random/boot_id", "r", encoding="utf-8") as handle:
            boot_id = handle.read().strip()
    except (FileNotFoundError, OSError, PermissionError):
        boot_id = ""
    init_started = _process_start_ticks(1)
    if not boot_id and not init_started:
        return None
    return f"{boot_id}:{init_started or 'unknown'}"


def _current_lock_owner() -> Dict[str, Any]:
    pid = os.getpid()
    return {
        "host": socket.gethostname(),
        "runtime_instance": _runtime_instance_id(),
        "pid": pid,
        "process_start_ticks": _process_start_ticks(pid),
    }


def _lock_owner_is_alive(lock_state: Dict[str, Any]) -> bool | None:
    """Return True/False when this host can prove ownership, otherwise None."""
    owner = lock_state.get("owner")
    if not isinstance(owner, dict) or not owner:
        return None
    if owner.get("host") != socket.gethostname():
        return None

    owner_runtime = owner.get("runtime_instance")
    current_runtime = _runtime_instance_id()
    if owner_runtime and current_runtime and owner_runtime != current_runtime:
        return False

    try:
        pid = int(owner.get("pid"))
    except (TypeError, ValueError):
        return None
    expected_start = owner.get("process_start_ticks")
    actual_start = _process_start_ticks(pid)
    if expected_start and actual_start:
        return str(expected_start) == str(actual_start)
    if expected_start and actual_start is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None
    return True


def _lock_heartbeat_at(lock_state: Dict[str, Any], ttl_seconds: int) -> datetime | None:
    heartbeat = _parse_iso_timestamp(lock_state.get("heartbeat_at"))
    if heartbeat is not None:
        return heartbeat
    # Compatibility with pre-heartbeat metadata: refreshes moved expires_at
    # forward by exactly the lease TTL, so recover the last refresh time.
    expires_at = _parse_iso_timestamp(lock_state.get("expires_at"))
    if expires_at is not None:
        return expires_at - timedelta(seconds=max(1, ttl_seconds))
    return _parse_iso_timestamp(lock_state.get("acquired_at"))


def _base_status() -> Dict[str, Any]:
    stage_plan = initial_progress_plan()
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
        "phase_started_at": None,
        "phase_history": [],
        "phase_outcomes": {},
        "progress_schema_version": PROGRESS_SCHEMA_VERSION,
        "stage_plan": stage_plan,
        "stage_states": {
            item["id"]: {"status": "waiting"}
            for item in stage_plan
        },
        "maintenance_started_at": None,
        "updated_at": _now_iso(),
        "finished_at": None,
        "last_success_at": None,
        "last_error": None,
        "warnings": [],
        "dataset_published": False,
        "failed_phase": None,
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


def _patch_raw_status(fields: Dict[str, Any], *, expected_run_id=None) -> Dict[str, Any]:
    try:
        return get_pipeline_state_store().patch_status(fields, expected_run_id=expected_run_id)
    except (RedisError, RuntimeError):
        return {}


def _has_active_run_lock() -> bool:
    try:
        lock_state = get_pipeline_state_store().read_lock()
    except (RedisError, RuntimeError):
        return False
    expires_at = _parse_iso_timestamp(lock_state.get("expires_at"))
    return bool(lock_state.get("token") and (expires_at is None or expires_at > datetime.now(timezone.utc)))


def _infer_active_phase(data: Dict[str, Any]) -> str:
    phase = data.get("phase")
    if phase and phase not in {"idle", "failed"}:
        return str(phase)
    history = data.get("phase_history") or []
    legacy_phases = ["initializing", "matching", "import", "publish"]
    if any(isinstance(entry, dict) and entry.get("phase") in legacy_phases for entry in history):
        completed_legacy = {
            entry.get("phase")
            for entry in history
            if isinstance(entry, dict) and entry.get("status") != "failed"
        }
        for candidate in legacy_phases:
            if candidate not in completed_legacy:
                return candidate
        return "publish"

    ordered_phases = PIPELINE_PHASES
    completed = {
        entry.get("phase")
        for entry in history
        if isinstance(entry, dict) and entry.get("status") != "failed"
    }
    for candidate in ordered_phases:
        if candidate not in completed:
            return candidate
    return "publish"


def get_status() -> Dict[str, Any]:
    raw = _read_raw_status()
    data = _base_status()
    data.update(raw)
    # Historical runs without the public plan keep the legacy timeline view.
    # Do not invent waiting children for work that finished before instrumentation.
    if raw and "stage_plan" not in raw:
        data.update(stage_plan=[], stage_states={})
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
    # A live lease is the authoritative signal that a runner exists. This
    # defensive projection also repairs the UI view of status files written by
    # older scheduler versions that reset an active run to idle on startup.
    if data.get("status") == "idle" and not data.get("finished_at") and _has_active_run_lock():
        data.update(
            status="running",
            phase=_infer_active_phase(data),
            message="Pipeline process active; waiting for its next progress update",
            trigger=data.get("trigger") or "manual",
            started_at=data.get("started_at") or data.get("phase_started_at"),
        )
    data["stage_states"] = project_stage_states(data)
    return data


def set_status(*, expected_run_id=None, **fields: Any) -> Dict[str, Any]:
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

    fields["updated_at"] = _now_iso()
    fields["stage_states"] = project_stage_states(dict(current, **fields))
    stored = (_patch_raw_status(fields, expected_run_id=expected_run_id)
              if expected_run_id is not None else _patch_raw_status(fields))
    result = _base_status()
    result.update(stored)
    result.pop("maintenance", None)
    return result


def start_run(
    trigger: str,
    run_id: Optional[str] = None,
    *,
    initial_phase: str = "source_check",
    message: str = "Checking source freshness",
) -> str:
    if initial_phase not in PIPELINE_PHASES:
        raise ValueError(f"Unknown initial pipeline phase: {initial_phase}")
    run_identifier = run_id or str(uuid.uuid4())
    started_at = _now_iso()
    set_status(
        status="running",
        phase=initial_phase,
        message=message,
        blocking_maintenance=False,
        processed=None,
        total=None,
        eta_seconds=None,
        run_id=run_identifier,
        trigger=trigger,
        started_at=started_at,
        phase_started_at=started_at,
        phase_history=[],
        phase_outcomes={},
        progress_schema_version=PROGRESS_SCHEMA_VERSION,
        stage_plan=initial_progress_plan(),
        stage_states={item["id"]: {"status": "waiting"} for item in initial_progress_plan()},
        finished_at=None,
        last_error=None,
        failed_phase=None,
        warnings=[],
        dataset_published=False,
    )
    return run_identifier


def set_phase_outcome(phase: str, outcome: str) -> Dict[str, Any]:
    """Record a timestamped, zero-duration cache reuse or mode skip.

    These phases do not execute, but the decision is still a real pipeline
    event. Keeping it in phase_history gives the UI an honest timestamp
    without pretending that the stage consumed runtime.
    """
    if phase not in PIPELINE_PHASES:
        raise ValueError(f"Unknown pipeline phase: {phase}")
    if outcome not in {"reused", "skipped"}:
        raise ValueError(f"Unsupported pipeline phase outcome: {outcome}")
    current = get_status()
    if current.get("finished_at"):
        return current
    outcomes = dict(current.get("phase_outcomes") or {})
    outcomes[phase] = outcome
    history = [
        entry
        for entry in (current.get("phase_history") or [])
        if not (
            isinstance(entry, dict)
            and entry.get("phase") == phase
            and entry.get("status") in {"reused", "skipped"}
        )
    ]
    observed_at = _now_iso()
    history.append({
        "phase": phase,
        "started_at": observed_at,
        "finished_at": observed_at,
        "duration_seconds": 0.0,
        "status": outcome,
    })
    stage_states = dict(current.get("stage_states") or {})
    for spec in current.get("stage_plan") or []:
        if isinstance(spec, dict) and spec.get("phase") == phase:
            stage_states[spec.get("id")] = {
                "status": outcome,
                "started_at": observed_at,
                "finished_at": observed_at,
                "duration_seconds": 0.0,
            }
    return set_status(phase_outcomes=outcomes, phase_history=history, stage_states=stage_states)


def set_progress_plan(stages: list[dict[str, Any]]) -> Dict[str, Any]:
    return record_progress_event(dict(event="pipeline_plan", progress_schema_version=PROGRESS_SCHEMA_VERSION, stages=stages))


def set_progress_stage_outcome(stage_id: str, outcome: str) -> Dict[str, Any]:
    return record_progress_event(dict(event="stage_outcome", progress_schema_version=PROGRESS_SCHEMA_VERSION,
                                      stage_id=stage_id, outcome=outcome))


def record_progress_event(payload: dict[str, Any], *, owner=None, run_id=None) -> Dict[str, Any]:
    """Validate and reduce without writes, then persist one guarded patch."""
    current = get_status()
    fields = apply_progress_event(current, payload, _now_iso(), owner=owner, run_id=run_id)
    if not fields:
        return current
    return set_status(expected_run_id=run_id, **fields)


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
    current = get_status()
    if current.get("finished_at"):
        return current
    fields = phase_fields(current, phase, message, _now_iso(),
                          blocking_maintenance=maintenance if blocking_maintenance is None else blocking_maintenance,
                          processed=processed, total=total, eta_seconds=eta_seconds)
    return set_status(**fields)


def finish_success(message: str = "Pipeline update completed", *, warnings=None, run_id=None) -> Dict[str, Any]:
    ts = _now_iso()
    current = get_status()
    if current.get("finished_at") or (run_id is not None and current.get("run_id") != run_id):
        return current
    history = list(current.get("phase_history") or [])
    phase_started_at = current.get("phase_started_at")
    active_phase = current.get("phase")
    started = _parse_iso_timestamp(phase_started_at)
    ended = _parse_iso_timestamp(ts)
    if active_phase and active_phase not in {"idle", "failed"} and phase_started_at:
        duration = max(0.0, (ended - started).total_seconds()) if started and ended else None
        history.append({
            "phase": active_phase,
            "started_at": phase_started_at,
            "finished_at": ts,
            "duration_seconds": round(duration, 3) if duration is not None else None,
        })
    states, stage_warnings = finalize_stage_states(current, ts, failed=False)
    all_warnings = list(dict.fromkeys([*(warnings or []), *stage_warnings]))
    return set_status(
        expected_run_id=run_id,
        stage_states=states,
        warnings=all_warnings,
        status="idle",
        phase="idle",
        message=("Dataset published with warnings" if current.get("dataset_published") else "Run completed with warnings") if all_warnings else message,
        blocking_maintenance=False,
        processed=None,
        total=None,
        eta_seconds=None,
        finished_at=ts,
        phase_started_at=None,
        phase_history=history,
        last_success_at=current.get("last_success_at") if all_warnings else ts,
        last_error=None,
    )


def finish_failure(error_message: str, *, run_id=None) -> Dict[str, Any]:
    ts = _now_iso()
    current = get_status()
    if current.get("finished_at") or (run_id is not None and current.get("run_id") != run_id):
        return current
    history = list(current.get("phase_history") or [])
    phase_started_at = current.get("phase_started_at")
    active_phase = current.get("phase")
    started = _parse_iso_timestamp(phase_started_at)
    ended = _parse_iso_timestamp(ts)
    if active_phase and active_phase not in {"idle", "failed"} and phase_started_at:
        duration = max(0.0, (ended - started).total_seconds()) if started and ended else None
        history.append({
            "phase": active_phase,
            "started_at": phase_started_at,
            "finished_at": ts,
            "duration_seconds": round(duration, 3) if duration is not None else None,
            "status": "failed",
        })
    states, _ = finalize_stage_states(current, ts, failed=True)
    return set_status(
        expected_run_id=run_id,
        stage_states=states,
        status="failed",
        phase="failed",
        message="Pipeline update failed",
        blocking_maintenance=False,
        finished_at=ts,
        phase_started_at=None,
        phase_history=history,
        failed_phase=active_phase,
        last_error=error_message,
    )


def set_next_run(next_run_at: Optional[str]) -> Dict[str, Any]:
    # Scheduling metadata has a separate writer from execution state. Patch
    # only its own fields so a scheduler refresh cannot change an active run.
    stored = _patch_raw_status({
        "next_run_at": next_run_at,
        "schedule_updated_at": _now_iso(),
    })
    result = _base_status()
    result.update(stored)
    return result


def set_data_updated(last_pipeline_data_import_ended_at: Optional[str]) -> Dict[str, Any]:
    return set_status(last_pipeline_data_import_ended_at=last_pipeline_data_import_ended_at)


def reconcile_orphaned_run(
    *,
    stale_after_seconds: int = _DEFAULT_STALE_SECONDS,
    lock_ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Fail a run whose lease owner died or stopped heartbeating.

    Owner metadata permits immediate recovery after a restart of the same
    scheduler container. Older or cross-host locks are recovered only after
    their inferred heartbeat exceeds the conservative stale threshold.
    """
    raw_status = _read_raw_status()
    if raw_status.get("status") != "running":
        return False

    try:
        store = get_pipeline_state_store()
        lock_state = store.read_lock()
    except (RedisError, RuntimeError):
        return False

    token = lock_state.get("token")
    owner_alive = _lock_owner_is_alive(lock_state) if token else False
    heartbeat_at = _lock_heartbeat_at(lock_state, lock_ttl_seconds) if token else None
    heartbeat_stale = (
        heartbeat_at is None
        or datetime.now(timezone.utc) - heartbeat_at > timedelta(seconds=max(1, stale_after_seconds))
    )
    orphaned = owner_alive is False or (owner_alive is None and heartbeat_stale)
    if not orphaned:
        return False

    run_id = raw_status.get("run_id")
    if token:
        store.release_lock(str(token))

    # Do not fail a replacement runner that won the lock between the checks.
    replacement_lock = store.read_lock()
    if replacement_lock.get("token") and replacement_lock.get("token") != token:
        return False
    latest = _read_raw_status()
    if latest.get("status") != "running" or latest.get("run_id") != run_id:
        return False
    finish_failure("Pipeline runner stopped unexpectedly; the previous published dataset remains active")
    return True


def acquire_run_lock(ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS) -> Optional[str]:
    token = str(uuid.uuid4())
    try:
        store = get_pipeline_state_store()
        owner = _current_lock_owner()
        if store.acquire_lock(token, ttl_seconds=max(1, ttl_seconds), owner=owner):
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
            if store.acquire_lock(token, ttl_seconds=max(1, ttl_seconds), owner=owner):
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
