"""Pipeline status and run lease, stored as JSON files in the shared runtime directory (STATE_DIR)."""

import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict

from backend.services.json_files import (
    exclusive_file_lock,
    read_json_object,
    resolve_state_dir,
    write_json_atomic,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_iso(ttl_seconds: int) -> str:
    return (_now_utc() + timedelta(seconds=max(1, ttl_seconds))).isoformat()


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


def _accept_run_update(current: dict, run_id: str) -> bool:
    return current.get("run_id") == run_id and current.get("status") == "running" and not current.get("finished_at")


class FilePipelineStateStore:
    def __init__(self, runtime_dir: str):
        self._status_path = os.path.join(runtime_dir, "pipeline_status.json")
        self._lock_path = os.path.join(runtime_dir, "pipeline_lock.json")
        self._guard_path = os.path.join(runtime_dir, "pipeline_lock.guard")

    def _guard_lock(self):
        return exclusive_file_lock(self._guard_path)

    def read_status(self) -> Dict[str, Any]:
        with self._guard_lock():
            return read_json_object(self._status_path)

    def read_lock(self) -> Dict[str, Any]:
        with self._guard_lock():
            return read_json_object(self._lock_path)

    def write_status(self, payload: Dict[str, Any]) -> None:
        with self._guard_lock():
            write_json_atomic(self._status_path, payload)

    def patch_status(self, fields: Dict[str, Any], *, expected_run_id: str | None = None) -> Dict[str, Any]:
        with self._guard_lock():
            current = read_json_object(self._status_path)
            if expected_run_id is not None and not _accept_run_update(current, expected_run_id):
                return current
            current.update(fields)
            write_json_atomic(self._status_path, current)
            return current

    def acquire_lock(self, token: str, ttl_seconds: int, owner: Dict[str, Any] | None = None) -> bool:
        with self._guard_lock():
            current = read_json_object(self._lock_path)
            expires_at = _parse_expiry(current.get("expires_at"))
            if current.get("token") and expires_at and expires_at > _now_utc():
                return False
            now = _now_utc().isoformat()
            write_json_atomic(
                self._lock_path,
                {
                    "token": token,
                    "acquired_at": now,
                    "heartbeat_at": now,
                    "expires_at": _expiry_iso(ttl_seconds),
                    "owner": owner or {},
                },
            )
            return True

    def refresh_lock(self, token: str, ttl_seconds: int) -> None:
        with self._guard_lock():
            current = read_json_object(self._lock_path)
            if current.get("token") != token:
                return
            write_json_atomic(
                self._lock_path,
                {
                    "token": token,
                    "acquired_at": current.get("acquired_at") or _now_utc().isoformat(),
                    "heartbeat_at": _now_utc().isoformat(),
                    "expires_at": _expiry_iso(ttl_seconds),
                    "owner": current.get("owner") or {},
                },
            )

    def release_lock(self, token: str) -> None:
        with self._guard_lock():
            current = read_json_object(self._lock_path)
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


def get_pipeline_state_store() -> FilePipelineStateStore:
    return FilePipelineStateStore(resolve_state_dir())
