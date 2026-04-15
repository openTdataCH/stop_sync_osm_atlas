import threading
import time
import os
from datetime import datetime

# Global storage for task progress and completed tasks
# task_id -> {status, processed, total, eta, error, created_at}
task_progress = {}
# task_id -> {file_path, filename, created_at}
completed_tasks = {}

_state_lock = threading.Lock()

# Cleanup configuration
TASK_MAX_AGE_SECONDS = 604800    # 1 week
CLEANUP_INTERVAL_SECONDS = 3600    # 1 hour

_cleanup_thread = None


def start_cleanup_thread():
    """Ensure the background cleanup thread is running."""
    global _cleanup_thread
    if _cleanup_thread and _cleanup_thread.is_alive():
        return
    _cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
    _cleanup_thread.start()


def cleanup_stale_tasks() -> int:
    """Remove task files and state entries older than TASK_MAX_AGE_SECONDS."""
    now = datetime.now()
    stale_task_ids = []

    with _state_lock:
        # Find stale completed tasks
        for t_id, info in list(completed_tasks.items()):
            age = (now - info['created_at']).total_seconds()
            if age > TASK_MAX_AGE_SECONDS:
                stale_task_ids.append(t_id)

        # Find stale/abandoned progress entries (no completed task)
        for t_id, info in list(task_progress.items()):
            if t_id in stale_task_ids:
                continue
            if t_id not in completed_tasks:
                created_at = info.get('created_at')
                if created_at and (now - created_at).total_seconds() > TASK_MAX_AGE_SECONDS:
                    stale_task_ids.append(t_id)

        # Remove stale entries and their files
        for t_id in stale_task_ids:
            task_info = completed_tasks.pop(t_id, None)
            task_progress.pop(t_id, None)
            if task_info:
                filepath = task_info.get('file_path')
                if filepath:
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except OSError:
                        pass

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
    with _state_lock:
        task_progress[task_id] = {
            'status': 'starting',
            'processed': 0,
            'total': 0,
            'eta': None,
            'error': None,
            'created_at': datetime.now()
        }


def update_progress(task_id: str, processed: int, total: int, start_time: float = None):
    """Update progress for a running task."""
    with _state_lock:
        if task_id not in task_progress:
            return

        task_progress[task_id]['processed'] = processed
        task_progress[task_id]['total'] = total

        if start_time and processed > 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed
            remaining = total - processed
            eta = remaining / rate if rate > 0 else None
            task_progress[task_id]['eta'] = eta


def set_task_status(task_id: str, status: str, error: str = None):
    with _state_lock:
        if task_id in task_progress:
            task_progress[task_id]['status'] = status
            if error:
                task_progress[task_id]['error'] = error


def complete_task(task_id: str, file_path: str, filename: str):
    with _state_lock:
        completed_tasks[task_id] = {
            'file_path': file_path,
            'filename': filename,
            'created_at': datetime.now()
        }
        if task_id in task_progress:
            task_progress[task_id]['status'] = 'completed'


def get_progress(task_id: str) -> dict:
    with _state_lock:
        if task_id not in task_progress:
            return None
        return task_progress[task_id].copy()


def get_completed_file(task_id: str) -> dict:
    with _state_lock:
        return completed_tasks.get(task_id)


def cancel_task(task_id: str) -> dict:
    """Remove task tracking and delete corresponding file if any."""
    with _state_lock:
        task_progress.pop(task_id, None)
        task_info = completed_tasks.pop(task_id, None)
        
    if task_info:
        try:
            filepath = task_info['file_path']
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
            
    return task_info
