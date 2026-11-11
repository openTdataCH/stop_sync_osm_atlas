"""Async export tasks (progress and completed files), stored as JSON files in the shared runtime directory (STATE_DIR)."""

import os
from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.json_files import (
    exclusive_file_lock,
    read_json_object,
    resolve_state_dir,
    write_json_atomic,
)

_PROGRESS_PATH = "tasks_progress.json"
_COMPLETED_PATH = "tasks_completed.json"
_GUARD_PATH = "tasks.guard"


def _normalize_mapping(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized[key] = value
    return normalized


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileAsyncExportStateStore:
    def __init__(self, runtime_dir: str):
        self._progress_path = os.path.join(runtime_dir, _PROGRESS_PATH)
        self._completed_path = os.path.join(runtime_dir, _COMPLETED_PATH)
        self._guard_path = os.path.join(runtime_dir, _GUARD_PATH)

    def _guard_lock(self):
        return exclusive_file_lock(self._guard_path)

    def read_progress(self, task_id: str) -> Dict[str, Any] | None:
        with self._guard_lock():
            return _normalize_mapping(read_json_object(self._progress_path)).get(task_id)

    def write_progress(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._guard_lock():
            progress = _normalize_mapping(read_json_object(self._progress_path))
            progress[task_id] = payload
            write_json_atomic(self._progress_path, progress)

    def list_progress(self) -> Dict[str, Dict[str, Any]]:
        with self._guard_lock():
            return _normalize_mapping(read_json_object(self._progress_path))

    def delete_progress(self, task_id: str) -> None:
        with self._guard_lock():
            progress = _normalize_mapping(read_json_object(self._progress_path))
            progress.pop(task_id, None)
            write_json_atomic(self._progress_path, progress)

    def read_completed(self, task_id: str) -> Dict[str, Any] | None:
        with self._guard_lock():
            return _normalize_mapping(read_json_object(self._completed_path)).get(task_id)

    def write_completed(self, task_id: str, payload: Dict[str, Any]) -> None:
        with self._guard_lock():
            completed = _normalize_mapping(read_json_object(self._completed_path))
            completed[task_id] = payload
            write_json_atomic(self._completed_path, completed)

    def list_completed(self) -> Dict[str, Dict[str, Any]]:
        with self._guard_lock():
            return _normalize_mapping(read_json_object(self._completed_path))

    def delete_completed(self, task_id: str) -> None:
        with self._guard_lock():
            completed = _normalize_mapping(read_json_object(self._completed_path))
            completed.pop(task_id, None)
            write_json_atomic(self._completed_path, completed)


def get_async_export_state_store() -> FileAsyncExportStateStore:
    return FileAsyncExportStateStore(resolve_state_dir())
