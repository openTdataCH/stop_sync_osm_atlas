"""Background export tasks: the data exports, the summary PDF and the documentation PDF.

``start_task`` runs the work in a thread; the client follows it at
``/api/exports/<task_id>/progress``, then fetches ``…/download`` or calls
``…/cancel`` (``backend/blueprints/reports.py``).
"""
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from flask import current_app

from backend.services.async_export_state_store import (
    get_async_export_state_store,
    now_iso,
)
from backend.services.time_utils import parse_utc_timestamp

# Cleanup configuration
TASK_MAX_AGE_SECONDS = 604800    # 1 week
CLEANUP_INTERVAL_SECONDS = 3600    # 1 hour

_cleanup_thread = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _task_age_seconds(created_at_value) -> float | None:
    created_at = parse_utc_timestamp(created_at_value)
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


def start_task(work, *args) -> str:
    """Run ``work(task_id, *args)`` in a background thread and return the new task's id.

    ``work`` returns ``(file path, download name)``, or None when it was
    cancelled or has recorded its own error; an exception marks the task
    failed. Week-old tasks are removed first.
    """
    start_cleanup_thread()
    cleanup_stale_tasks()
    task_id = str(uuid.uuid4())
    init_task(task_id)
    flask_app = current_app._get_current_object()
    threading.Thread(target=_run_task, args=(flask_app, task_id, work, args), daemon=True).start()
    return task_id


def _run_task(flask_app, task_id: str, work, args) -> None:
    with flask_app.app_context():
        if get_progress(task_id) is None:
            return  # cancelled before it started
        set_task_status(task_id, 'processing')
        try:
            result = work(task_id, *args)
        except Exception as exc:
            set_task_status(task_id, 'error', str(exc))
            flask_app.logger.error('Export %s failed: %s', task_id, exc)
            return
        if result is not None:
            complete_task(task_id, *result)


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
