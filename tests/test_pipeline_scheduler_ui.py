import re
import json
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


def test_pipeline_status_file_backend_persists_status(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("PIPELINE_STATE_BACKEND", "file")
    monkeypatch.setenv("PIPELINE_STATE_DIR", str(runtime_dir))

    pipeline_status.set_status(status="running", phase="matching", message="Matching")

    stored = json.loads((runtime_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    assert stored["status"] == "running"
    assert pipeline_status.get_status()["phase"] == "matching"


def test_pipeline_status_file_backend_lock_is_shared(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    monkeypatch.setenv("PIPELINE_STATE_BACKEND", "file")
    monkeypatch.setenv("PIPELINE_STATE_DIR", str(tmp_path / "runtime"))
    pipeline_status.set_status(status="idle")

    first = pipeline_status.acquire_run_lock(ttl_seconds=30)
    second = pipeline_status.acquire_run_lock(ttl_seconds=30)

    assert first is not None
    assert second is None

    pipeline_status.release_run_lock(first)

    third = pipeline_status.acquire_run_lock(ttl_seconds=30)
    assert third is not None
    pipeline_status.release_run_lock(third)


def test_pipeline_state_store_defaults_to_file_backend(monkeypatch):
    from backend.services import pipeline_state_store

    monkeypatch.delenv("PIPELINE_STATE_BACKEND", raising=False)
    monkeypatch.delenv("PIPELINE_STATE_REDIS_URL", raising=False)
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)

    assert pipeline_state_store._resolve_backend_name() == "file"


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
    from backend.services import data_meta

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data_meta, "DATA_META_PATH", str(tmp_path / "data" / "data_meta.json"))
    monkeypatch.setattr(job_runner, "get_zurich_now", lambda: datetime(2026, 5, 2, 19, 31, tzinfo=timezone.utc))
    monkeypatch.setattr(job_runner, "format_zurich_timestamp", lambda dt: "2026-05-02T21:31:00+02:00")
    captured = {}
    monkeypatch.setattr(job_runner, "set_data_updated", lambda value: captured.setdefault("value", value))

    result = job_runner._record_data_updated_timestamp()

    assert result == "2026-05-02T21:31:00+02:00"
    assert captured["value"] == "2026-05-02T21:31:00+02:00"
    assert (tmp_path / "data" / "data_meta.json").read_text(encoding="utf-8") == '{"data_updated_at": "2026-05-02T21:31:00+02:00"}'


def test_source_snapshot_unchanged_uses_http_validators():
    from matching_and_import_db.downloader import source_freshness

    previous = {"probe_ok": True, "etag": '"abc"', "last_modified": "old"}
    current_same = {"probe_ok": True, "etag": '"abc"', "last_modified": "new"}
    current_different = {"probe_ok": True, "etag": '"xyz"', "last_modified": "new"}

    assert source_freshness.source_snapshot_is_unchanged(previous, current_same) is True
    assert source_freshness.source_snapshot_is_unchanged(previous, current_different) is False


def test_run_atlas_gtfs_preprocessing_skips_when_sources_are_unchanged(monkeypatch):
    from matching_and_import_db.scheduler import job_runner

    previous_sources = {
        "atlas": {"probe_ok": True, "etag": '"atlas"'},
        "gtfs": {"probe_ok": True, "etag": '"gtfs"'},
    }
    current_sources = {
        "atlas": {"probe_ok": True, "etag": '"atlas"'},
        "gtfs": {"probe_ok": True, "etag": '"gtfs"'},
    }
    captured = {"phases": []}

    monkeypatch.setattr(job_runner, "_load_preprocessing_source_state", lambda: previous_sources)
    monkeypatch.setattr(job_runner, "_probe_preprocessing_sources", lambda: current_sources)
    monkeypatch.setattr(job_runner, "refresh_run_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_runner, "_persist_preprocessing_source_state", lambda *_args, **_kwargs: captured.setdefault("persisted", True))
    monkeypatch.setattr(job_runner, "_run_subprocess", lambda *args, **kwargs: captured.setdefault("subprocess_called", True))
    monkeypatch.setattr(
        job_runner,
        "set_phase",
        lambda **kwargs: captured["phases"].append((kwargs["phase"], kwargs["message"])),
    )

    job_runner._run_atlas_gtfs_preprocessing_if_needed("lock-token")

    assert captured.get("subprocess_called") is None
    assert captured["phases"][-1] == (
        "atlas_download",
        "ATLAS + GTFS unchanged; reusing cached preprocessing outputs",
    )