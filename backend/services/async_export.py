import os
import threading
import time
from datetime import datetime, timezone

from backend.services.async_export_state_store import (
    get_async_export_state_store,
    now_iso,
    parse_created_at,
)

# Cleanup configuration
TASK_MAX_AGE_SECONDS = 604800    # 1 week
CLEANUP_INTERVAL_SECONDS = 3600    # 1 hour

_cleanup_thread = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _task_age_seconds(created_at_value) -> float | None:
    created_at = parse_created_at(created_at_value)
    if created_at is None:
        return None
    return (_now_utc() - created_at).total_seconds()


def _remove_task_file(task_info: dict | None) -> None:
    if not task_info:
        return
    filepath = task_info.get('file_path')
    if not filepath:
        return
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        return


def start_cleanup_thread():
    """Ensure the background cleanup thread is running."""
    global _cleanup_thread
    if _cleanup_thread and _cleanup_thread.is_alive():
        return
    _cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
    _cleanup_thread.start()


def cleanup_stale_tasks() -> int:
    """Remove task files and state entries older than TASK_MAX_AGE_SECONDS."""
    store = get_async_export_state_store()
    stale_task_ids: list[str] = []
    stale_task_ids_set: set[str] = set()

    completed = store.list_completed()
    for task_id, info in completed.items():
        age = _task_age_seconds(info.get('created_at'))
        if age is not None and age > TASK_MAX_AGE_SECONDS:
            stale_task_ids.append(task_id)
            stale_task_ids_set.add(task_id)

    progress = store.list_progress()
    for task_id, info in progress.items():
        if task_id in stale_task_ids_set:
            continue
        if task_id in completed:
            continue
        age = _task_age_seconds(info.get('created_at'))
        if age is not None and age > TASK_MAX_AGE_SECONDS:
            stale_task_ids.append(task_id)
            stale_task_ids_set.add(task_id)

    for task_id in stale_task_ids:
        task_info = store.read_completed(task_id)
        store.delete_completed(task_id)
        store.delete_progress(task_id)
        _remove_task_file(task_info)

    return len(stale_task_ids)


def _periodic_cleanup():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            cleanup_stale_tasks()
        except Exception:
            pass


def init_task(task_id: str):
    """Initialize a new task in the progress dictionary."""
    get_async_export_state_store().write_progress(
        task_id,
        {
            'status': 'starting',
            'processed': 0,
            'total': 0,
            'eta': None,
            'error': None,
            'created_at': now_iso(),
        },
    )


def update_progress(task_id: str, processed: int, total: int, start_time: float = None):
    """Update progress for a running task."""
    store = get_async_export_state_store()
    progress = store.read_progress(task_id)
    if not progress:
        return

    progress['processed'] = processed
    progress['total'] = total

    if start_time and processed > 0:
        elapsed = time.time() - start_time
        rate = processed / elapsed
        remaining = total - processed
        eta = remaining / rate if rate > 0 else None
        progress['eta'] = eta

    store.write_progress(task_id, progress)


def set_task_status(task_id: str, status: str, error: str = None):
    store = get_async_export_state_store()
    progress = store.read_progress(task_id)
    if not progress:
        return
    progress['status'] = status
    if error:
        progress['error'] = error
    store.write_progress(task_id, progress)


def complete_task(task_id: str, file_path: str, filename: str):
    store = get_async_export_state_store()
    store.write_completed(
        task_id,
        {
            'file_path': file_path,
            'filename': filename,
            'created_at': now_iso(),
        },
    )

    progress = store.read_progress(task_id)
    if progress:
        progress['status'] = 'completed'
        store.write_progress(task_id, progress)


def get_progress(task_id: str) -> dict:
    progress = get_async_export_state_store().read_progress(task_id)
    if not progress:
        return None
    return dict(progress)


def get_completed_file(task_id: str) -> dict:
    task_info = get_async_export_state_store().read_completed(task_id)
    if not task_info:
        return None
    return dict(task_info)


def cancel_task(task_id: str) -> dict:
    """Remove task tracking and delete corresponding file if any."""
    store = get_async_export_state_store()
    task_info = store.read_completed(task_id)
    store.delete_progress(task_id)
    store.delete_completed(task_id)
    _remove_task_file(task_info)

    return task_info
