import re
from datetime import datetime, timedelta, timezone


def test_create_interval_trigger_uses_hours():
    from matching_and_import_db.scheduler import service

    trigger = service._create_interval_trigger(interval_hours=6)

    assert trigger.__class__.__name__ == "IntervalTrigger"
    assert trigger.interval == timedelta(hours=6)


def test_update_next_run_timestamp_serializes_utc_iso(monkeypatch):
    from matching_and_import_db.scheduler import service

    expected = datetime(2026, 5, 2, 10, 30, tzinfo=timezone.utc)
    captured = {}

    class DummyJob:
        next_run_time = expected

    class DummyScheduler:
        def get_job(self, job_id):
            assert job_id == "daily_pipeline_update"
            return DummyJob()

    monkeypatch.setattr(service, "scheduler", DummyScheduler())
    monkeypatch.setattr(service, "set_next_run", lambda value: captured.setdefault("value", value))

    service._update_next_run_timestamp()

    assert captured["value"] == expected.isoformat()


def test_scheduler_started_listener_refreshes_next_run(monkeypatch):
    from matching_and_import_db.scheduler import service

    captured = {}
    monkeypatch.setattr(service, "_update_next_run_timestamp", lambda: captured.setdefault("called", True))

    service._handle_scheduler_started()

    assert captured["called"] is True


def test_pipeline_status_accepts_maintenance_input_alias(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})
    monkeypatch.setattr(pipeline_status, "_write_raw_status", lambda payload: None)

    status = pipeline_status.set_status(maintenance=True)

    assert status["blocking_maintenance"] is True
    assert "maintenance" not in status


def test_pipeline_status_maps_old_storage_key(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {"maintenance": True})

    status = pipeline_status.get_status()

    assert status["blocking_maintenance"] is True
    assert "maintenance" not in status


def test_pipeline_status_falls_back_to_stats_data_updated_at(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})

    class DummyStatsExport:
        @staticmethod
        def load_stats_from_file():
            return {"data_updated_at": "2026-05-02T19:31:00+02:00"}

    monkeypatch.setitem(__import__("sys").modules, "backend.services.stats_export", DummyStatsExport)

    status = pipeline_status.get_status()

    assert status["data_updated_at"] == "2026-05-02T19:31:00+02:00"


def test_pipeline_status_supports_data_updated_field(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})
    monkeypatch.setattr(pipeline_status, "_write_raw_status", lambda payload: None)

    status = pipeline_status.set_data_updated("2026-05-02T19:31:00+02:00")

    assert status["data_updated_at"] == "2026-05-02T19:31:00+02:00"


def test_navbar_renders_next_run_metadata(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(
        stats_export,
        "load_stats_from_file",
        lambda: {"data_updated_at": "2026-05-02T09:15:00+02:00"},
    )
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "data_updated_at": "2026-05-02T19:31:00+02:00",
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="navbarDataUpdated"' in html
    assert 'id="navbarDataUpdatedText"' in html
    assert 'data-data-updated-at="2026-05-02T19:31:00+02:00"' in html
    assert 'data-pipeline-next-run-at="2026-05-03T08:00:00+00:00"' in html
    assert 'data-running-label="Pipeline running in the background"' in html
    assert 'id="navbarNextRunInfo"' in html
    assert 'data-bs-toggle="tooltip"' in html
    assert 'title="Next pipeline run: 2026-05-03 08:00"' in html
    navbar_fragment = re.search(r'<span[^>]*id="navbarDataUpdated"[\s\S]*?<\/span>\s*<\/li>', html)
    assert navbar_fragment is not None
    assert 'far fa-clock' not in navbar_fragment.group(0)
    assert re.search(r'<span[^>]*id="navbarDataUpdated"[^>]*title=', html) is None


def test_record_data_updated_timestamp_writes_meta_and_status(monkeypatch, tmp_path):
    from matching_and_import_db.scheduler import job_runner

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(job_runner, "DATA_META_PATH", str(tmp_path / "data" / "data_meta.json"))
    monkeypatch.setattr(job_runner, "get_zurich_now", lambda: datetime(2026, 5, 2, 19, 31, tzinfo=timezone.utc))
    monkeypatch.setattr(job_runner, "format_zurich_timestamp", lambda dt: "2026-05-02T21:31:00+02:00")
    captured = {}
    monkeypatch.setattr(job_runner, "set_data_updated", lambda value: captured.setdefault("value", value))

    result = job_runner._record_data_updated_timestamp()

    assert result == "2026-05-02T21:31:00+02:00"
    assert captured["value"] == "2026-05-02T21:31:00+02:00"
    assert (tmp_path / "data" / "data_meta.json").read_text(encoding="utf-8") == '{"data_updated_at": "2026-05-02T21:31:00+02:00"}'