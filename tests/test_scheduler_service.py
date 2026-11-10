"""The scheduler process: its interval, next-run timestamp, startup and watchdog."""
from datetime import datetime, timedelta, timezone


def test_create_interval_trigger_uses_hours():
    from backend.jobs import service

    trigger = service._create_interval_trigger(interval_hours=6)

    assert trigger.__class__.__name__ == "IntervalTrigger"
    assert trigger.interval == timedelta(hours=6)


def test_update_next_run_timestamp_serializes_utc_iso(monkeypatch):
    from backend.jobs import service

    expected = datetime(2026, 5, 2, 10, 30, tzinfo=timezone.utc)
    captured = {}

    class DummyJob:
        next_run_time = expected

    class DummyScheduler:
        def get_job(self, job_id):
            assert job_id == "scheduled_pipeline_update"
            return DummyJob()

    monkeypatch.setattr(service, "scheduler", DummyScheduler())
    monkeypatch.setattr(service, "set_next_run", lambda value, **kwargs: captured.update(value=value, **kwargs))

    service._update_next_run_timestamp()

    assert captured == {"value": expected.isoformat(), "interval_hours": service.PIPELINE_SCHEDULE_INTERVAL_HOURS}


def test_scheduler_started_listener_refreshes_next_run(monkeypatch):
    from backend.jobs import service

    captured = {}
    monkeypatch.setattr(service, "_pipeline_watchdog", lambda: captured.setdefault("watchdog", True))
    monkeypatch.setattr(service, "_update_next_run_timestamp", lambda: captured.setdefault("called", True))

    service._handle_scheduler_started()

    assert captured["called"] is True
    assert captured["watchdog"] is True


def test_pipeline_watchdog_logs_recovered_runs(monkeypatch, caplog):
    from backend.jobs import service

    monkeypatch.setattr(service, "reconcile_orphaned_run", lambda: True)

    service._pipeline_watchdog()

    assert "Recovered an interrupted pipeline run" in caplog.text


def test_scheduler_startup_preserves_an_active_pipeline_status(monkeypatch, tmp_path):
    from backend.jobs import service
    from backend.services import pipeline_status

    monkeypatch.setenv("STATE_DIR", str(tmp_path / "runtime"))
    pipeline_status.set_status(
        status="running",
        phase="matching",
        message="Matching sources",
        run_id="run-active",
        started_at="2026-05-02T10:00:00+00:00",
    )

    class DummyJob:
        next_run_time = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)

    class DummyScheduler:
        def add_job(self, *args, **kwargs):
            return None

        def add_listener(self, *args, **kwargs):
            return None

        def get_job(self, job_id):
            assert job_id == "scheduled_pipeline_update"
            return DummyJob()

        def start(self):
            return None

    monkeypatch.setattr(service, "scheduler", DummyScheduler())
    monkeypatch.setattr(service.signal, "signal", lambda *args: None)

    service.main()

    status = pipeline_status.get_status()
    assert status["status"] == "running"
    assert status["phase"] == "matching"
    assert status["message"] == "Matching sources"
    assert status["run_id"] == "run-active"
    assert status["next_run_at"] == "2026-05-03T08:00:00+00:00"
