import re
import json
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
            assert job_id == "daily_pipeline_update"
            return DummyJob()

    monkeypatch.setattr(service, "scheduler", DummyScheduler())
    monkeypatch.setattr(service, "set_next_run", lambda value: captured.setdefault("value", value))

    service._update_next_run_timestamp()

    assert captured["value"] == expected.isoformat()


def test_scheduler_started_listener_refreshes_next_run(monkeypatch):
    from backend.jobs import service

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


def test_pipeline_status_falls_back_to_stats_last_pipeline_data_import_ended_at(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})

    class DummyStatsExport:
        @staticmethod
        def load_stats_from_file():
            return {"last_pipeline_data_import_ended_at": "2026-05-02T19:31:00+02:00"}

    monkeypatch.setitem(__import__("sys").modules, "backend.services.stats_export", DummyStatsExport)

    status = pipeline_status.get_status()

    assert status["last_pipeline_data_import_ended_at"] == "2026-05-02T19:31:00+02:00"


def test_pipeline_status_supports_data_updated_field(monkeypatch):
    from backend.services import pipeline_status

    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})
    monkeypatch.setattr(pipeline_status, "_write_raw_status", lambda payload: None)

    status = pipeline_status.set_data_updated("2026-05-02T19:31:00+02:00")

    assert status["last_pipeline_data_import_ended_at"] == "2026-05-02T19:31:00+02:00"


def test_pipeline_status_records_phase_history(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_write_raw_status",
        lambda payload: stored.update(payload),
    )

    pipeline_status.start_run(trigger="manual", run_id="run-1")
    pipeline_status.set_phase("matching", "Matching sources")
    pipeline_status.set_phase("import", "Importing snapshot")
    finished = pipeline_status.finish_success()

    assert [entry["phase"] for entry in finished["phase_history"]] == [
        "initializing",
        "matching",
        "import",
    ]
    assert all(entry["duration_seconds"] >= 0 for entry in finished["phase_history"])
    assert finished["phase_started_at"] is None

    pipeline_status.start_run(trigger="manual", run_id="run-2")
    pipeline_status.set_phase("matching", "Matching sources")
    failed = pipeline_status.finish_failure("source unavailable")

    assert failed["failed_phase"] == "matching"
    assert failed["phase_history"][-1]["status"] == "failed"


def test_pipeline_status_file_backend_persists_status(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    pipeline_status.set_status(status="running", phase="matching", message="Matching")

    stored = json.loads((runtime_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    assert stored["status"] == "running"
    assert pipeline_status.get_status()["phase"] == "matching"


def test_pipeline_status_file_backend_lock_is_shared(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "runtime"))
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

    monkeypatch.delenv("STATE_BACKEND", raising=False)
    monkeypatch.delenv("STATE_REDIS_URL", raising=False)
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)

    assert pipeline_state_store._resolve_backend_name() == "file"


def test_navbar_renders_next_run_metadata(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(
        stats_export,
        "load_stats_from_file",
        lambda: {"last_pipeline_data_import_ended_at": "2026-05-02T09:15:00+02:00"},
    )
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "last_pipeline_data_import_ended_at": "2026-05-02T19:31:00+02:00",
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
    assert 'title="Next pipeline run: 2026-05-03 10:00"' in html
    navbar_fragment = re.search(r'<span[^>]*id="navbarDataUpdated"[\s\S]*?<\/span>\s*<\/li>', html)
    assert navbar_fragment is not None
    assert 'far fa-clock' not in navbar_fragment.group(0)
    assert re.search(r'<span[^>]*id="navbarDataUpdated"[^>]*title=', html) is None


def test_navbar_renders_next_run_without_import_timestamp(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(stats_export, "load_stats_from_file", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "last_pipeline_data_import_ended_at": None,
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="navbarDataUpdated"' in html
    assert 'data-data-updated-at=""' in html
    assert 'data-pipeline-next-run-at="2026-05-03T08:00:00+00:00"' in html
    assert "Data not imported yet" in html
    assert 'title="Next pipeline run: 2026-05-03 10:00"' in html


def test_record_data_updated_timestamp_writes_meta_and_status(monkeypatch, tmp_path):
    from backend.jobs import job_runner
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
    assert (tmp_path / "data" / "data_meta.json").read_text(encoding="utf-8") == '{"last_pipeline_data_import_ended_at": "2026-05-02T21:31:00+02:00"}'


def test_record_data_updated_timestamp_persists_run_type_and_refresh_scope(monkeypatch, tmp_path):
    from backend.jobs import job_runner
    from backend.jobs.job_types import PipelineRunType
    from backend.services import data_meta

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data_meta, "DATA_META_PATH", str(tmp_path / "data" / "data_meta.json"))
    monkeypatch.setattr(job_runner, "get_zurich_now", lambda: datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(job_runner, "format_zurich_timestamp", lambda dt: "2026-05-03T12:00:00+02:00")
    captured = {}
    monkeypatch.setattr(job_runner, "set_data_updated", lambda value: captured.setdefault("value", value))
    monkeypatch.setattr(job_runner, "set_status", lambda **kwargs: captured.setdefault("status", kwargs))

    result = job_runner._record_data_updated_timestamp(
        run_type=PipelineRunType.ATLAS_CACHED,
        rewritten_tables=['osm_nodes', 'line_families'],
        reused_tables=['atlas_stops', 'gtfs_stops_raw'],
    )

    assert result == "2026-05-03T12:00:00+02:00"
    assert captured["value"] == "2026-05-03T12:00:00+02:00"
    assert captured["status"]["run_type"] == "atlas_cached"
    assert captured["status"]["refresh_scope_tables_reused"] == ['atlas_stops', 'gtfs_stops_raw']
    assert json.loads((tmp_path / "data" / "data_meta.json").read_text(encoding="utf-8")) == {
        "last_pipeline_data_import_ended_at": "2026-05-03T12:00:00+02:00",
        "last_run_type": "atlas_cached",
        "refresh_scope_tables_rewritten": ['osm_nodes', 'line_families'],
        "refresh_scope_tables_reused": ['atlas_stops', 'gtfs_stops_raw'],
    }


def test_format_zurich_display_timestamp_formats_iso_strings():
    from backend.services.time_utils import format_zurich_display_timestamp

    assert format_zurich_display_timestamp("2026-05-10T11:14:40.367792+02:00") == "2026-05-10 11:14"
    assert format_zurich_display_timestamp("2026-05-10T09:14:40Z") == "2026-05-10 11:14"


def test_engine_command_reuses_source_snapshots_without_engine_import(monkeypatch, tmp_path):
    from backend.jobs import job_runner
    monkeypatch.setenv('MATCHER_COMMAND', '/path/to/engine/bin/transport-matcher')
    monkeypatch.setenv('PIPELINE_WORKSPACE', str(tmp_path))
    destination = tmp_path / 'result'
    command = job_runner._engine_command('match-import', destination)
    assert command[0] == '/path/to/engine/bin/transport-matcher'
    assert '--download' not in command
    assert str(destination) in command
    assert '--download' in job_runner._engine_command('full', destination)


def test_engine_command_force_refresh_only_applies_to_acquisition(monkeypatch, tmp_path):
    from backend.jobs import job_runner
    monkeypatch.setenv('PIPELINE_FORCE_FULL_REFRESH', 'true')
    assert '--force' in job_runner._engine_command('full', tmp_path / 'result')
    assert '--force' not in job_runner._engine_command('match-import', tmp_path / 'result')


def test_engine_process_does_not_receive_application_credentials(monkeypatch):
    from types import SimpleNamespace
    from backend.jobs import job_runner
    monkeypatch.setenv('DATABASE_URI', 'test-database-secret')
    monkeypatch.setenv('SECRET_KEY', 'test-session-secret')
    monkeypatch.setenv('SOURCE_API_TOKEN', 'source-token')
    monkeypatch.setattr(job_runner, 'set_phase', lambda **kwargs: None)
    captured = {}
    def run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(job_runner.subprocess, 'run', run)
    job_runner._run_subprocess(['transport-matcher', '--help'], 'matching', 'Matching')
    assert 'DATABASE_URI' not in captured['env']
    assert 'SECRET_KEY' not in captured['env']
    assert captured['env']['SOURCE_API_TOKEN'] == 'source-token'
