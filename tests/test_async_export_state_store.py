from datetime import datetime, timedelta, timezone

import pytest

from backend.services import async_export
from backend.services import async_export_state_store


def test_async_export_state_store_defaults_to_file_backend(monkeypatch):
    monkeypatch.delenv("STATE_BACKEND", raising=False)
    monkeypatch.delenv("STATE_REDIS_URL", raising=False)

    assert async_export_state_store.resolve_backend_name() == "file"


def test_async_export_state_store_redis_requires_url(monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "redis")
    monkeypatch.setenv("STATE_REDIS_URL", "")

    with pytest.raises(RuntimeError, match="STATE_REDIS_URL"):
        async_export_state_store.get_async_export_state_store()


def test_async_export_state_store_uses_shared_backend(monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "redis")
    monkeypatch.setenv("STATE_REDIS_URL", "redis://localhost:6379/0")

    assert async_export_state_store.resolve_backend_name() == "redis"


def test_async_export_file_backend_roundtrip(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    task_id = "report-task-1"

    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    async_export.init_task(task_id)
    async_export.set_task_status(task_id, "processing")
    async_export.update_progress(task_id, processed=7, total=20)

    progress = async_export.get_progress(task_id)
    assert progress is not None
    assert progress["status"] == "processing"
    assert progress["processed"] == 7
    assert progress["total"] == 20

    output_file = tmp_path / "report-task-1.csv"
    output_file.write_text("a,b\n1,2\n", encoding="utf-8")
    async_export.complete_task(task_id, str(output_file), "report-task-1.csv")

    completed = async_export.get_completed_file(task_id)
    assert completed is not None
    assert completed["filename"] == "report-task-1.csv"
    assert completed["file_path"] == str(output_file)
    assert async_export.get_progress(task_id)["status"] == "completed"


def test_async_export_file_backend_cleanup_removes_stale_files(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    task_id = "stale-task"

    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    stale_created_at = (
        datetime.now(timezone.utc) - timedelta(seconds=async_export.TASK_MAX_AGE_SECONDS + 10)
    ).isoformat()

    output_file = tmp_path / "stale-report.pdf"
    output_file.write_bytes(b"PDF")

    store = async_export_state_store.get_async_export_state_store()
    store.write_progress(
        task_id,
        {
            "status": "completed",
            "processed": 1,
            "total": 1,
            "eta": None,
            "error": None,
            "created_at": stale_created_at,
        },
    )
    store.write_completed(
        task_id,
        {
            "file_path": str(output_file),
            "filename": "stale-report.pdf",
            "created_at": stale_created_at,
        },
    )

    removed_count = async_export.cleanup_stale_tasks()

    assert removed_count == 1
    assert async_export.get_progress(task_id) is None
    assert async_export.get_completed_file(task_id) is None
    assert not output_file.exists()
