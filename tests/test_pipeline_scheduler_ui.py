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

    monkeypatch.setenv("STATE_BACKEND", "file")
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
            assert job_id == "daily_pipeline_update"
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


def test_pipeline_status_accepts_maintenance_input_alias(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )

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

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )

    status = pipeline_status.set_data_updated("2026-05-02T19:31:00+02:00")

    assert status["last_pipeline_data_import_ended_at"] == "2026-05-02T19:31:00+02:00"


def test_pipeline_status_records_phase_history(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )

    pipeline_status.start_run(trigger="manual", run_id="run-1")
    pipeline_status.set_phase("stop_matching", "Stop matching")
    pipeline_status.set_phase("database", "Staging database")
    finished = pipeline_status.finish_success()

    assert [entry["phase"] for entry in finished["phase_history"]] == [
        "source_check",
        "stop_matching",
        "database",
    ]
    assert all(entry["duration_seconds"] >= 0 for entry in finished["phase_history"])
    assert finished["phase_started_at"] is None

    pipeline_status.start_run(trigger="manual", run_id="run-2")
    pipeline_status.set_phase("stop_matching", "Stop matching")
    failed = pipeline_status.finish_failure("source unavailable")

    assert failed["failed_phase"] == "stop_matching"
    assert failed["phase_history"][-1]["status"] == "failed"


def test_pipeline_status_records_and_clears_reused_phase_outcomes(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )

    pipeline_status.start_run(trigger="manual", run_id="run-cache")
    reused = pipeline_status.set_phase_outcome("atlas", "reused")
    assert reused["phase_outcomes"] == {"atlas": "reused"}
    assert reused["phase_history"][-1]["phase"] == "atlas"
    assert reused["phase_history"][-1]["status"] == "reused"
    assert reused["phase_history"][-1]["duration_seconds"] == 0.0
    assert reused["phase_history"][-1]["started_at"] == reused["phase_history"][-1]["finished_at"]

    active = pipeline_status.set_phase("atlas", "Preparing ATLAS data")
    assert active["phase_outcomes"] == {}
    assert all(entry.get("status") != "reused" for entry in active["phase_history"])


def test_versioned_progress_plan_and_events_are_stored_generically(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )
    pipeline_status.start_run(trigger="manual", run_id="run-progress")
    spec = {
        "id": "osm.future_parser",
        "parent_id": "osm",
        "phase": "osm",
        "label": "A future parser stage",
        "description": "Delivered by a newer engine without an application code change.",
        "order": 99,
        "progress_kind": "indeterminate",
    }

    pipeline_status.record_progress_event({
        "event": "pipeline_plan",
        "progress_schema_version": 1,
        "stages": [spec],
    })
    pipeline_status.record_progress_event({
        "event": "stage_started",
        "progress_schema_version": 1,
        "stage_id": spec["id"],
        "stage_spec": spec,
        "seconds": 0,
    })
    completed = pipeline_status.record_progress_event({
        "event": "stage_finished",
        "progress_schema_version": 1,
        "stage_id": spec["id"],
        "stage_spec": spec,
        "seconds": 3.25,
    })

    assert completed["phase"] == "osm"
    assert completed["message"] == "A future parser stage"
    assert completed["stage_states"][spec["id"]]["status"] == "complete"
    assert completed["stage_states"][spec["id"]]["duration_seconds"] == 3.25


def test_late_engine_plan_inherits_an_existing_phase_outcome(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )
    pipeline_status.start_run(trigger="manual", run_id="run-reuse")
    pipeline_status.set_phase_outcome("timetable", "reused")
    status = pipeline_status.set_progress_plan([{
        "id": "timetable.engine_owned",
        "parent_id": "timetable",
        "phase": "timetable",
        "label": "Engine-owned timetable work",
        "description": "Arrives after the runner has recorded reuse.",
        "order": 10,
        "progress_kind": "indeterminate",
    }])

    assert status["stage_states"]["timetable.engine_owned"]["status"] == "reused"


def test_all_reused_engine_children_roll_up_to_the_parent_phase(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(
        pipeline_status,
        "_patch_raw_status",
        lambda fields: stored.update(fields) or dict(stored),
    )
    pipeline_status.start_run(trigger="manual", run_id="run-atlas-reuse")
    pipeline_status.set_progress_plan([{
        "id": "atlas.prepare",
        "parent_id": "atlas",
        "phase": "atlas",
        "label": "Prepare ATLAS",
        "description": "Prepare the ATLAS cache.",
        "order": 10,
        "progress_kind": "indeterminate",
    }])
    status = pipeline_status.set_progress_stage_outcome("atlas.prepare", "reused")

    assert status["phase_outcomes"]["atlas"] == "reused"
    assert status["stage_states"]["atlas.prepare"]["status"] == "reused"


def test_progress_plan_rejects_unknown_or_redefined_stage_contracts():
    import pytest
    from backend.services.pipeline_progress import initial_progress_plan, merge_progress_plan

    with pytest.raises(ValueError, match="Unknown parent"):
        merge_progress_plan(initial_progress_plan(), [{
            "id": "future.orphan",
            "parent_id": "missing",
            "phase": "missing",
            "label": "Orphan",
            "description": "Invalid parent.",
            "order": 10,
            "progress_kind": "indeterminate",
        }])

    with pytest.raises(ValueError, match="definition changed"):
        merge_progress_plan(initial_progress_plan(), [{
            "id": "database.validate",
            "parent_id": "database",
            "phase": "database",
            "label": "Renamed during the run",
            "description": "Conflicting metadata.",
            "order": 10,
            "progress_kind": "indeterminate",
        }])


def test_pipeline_status_file_backend_persists_status(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    pipeline_status.set_status(status="running", phase="matching", message="Matching")

    stored = json.loads((runtime_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    assert stored["status"] == "running"
    assert pipeline_status.get_status()["phase"] == "matching"


def test_pipeline_status_patches_do_not_overwrite_run_or_schedule_fields(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    pipeline_status.set_next_run("2026-05-03T08:00:00+00:00")
    pipeline_status.set_status(status="running", phase="matching", message="Matching")
    pipeline_status.set_next_run("2026-05-04T08:00:00+00:00")

    status = pipeline_status.get_status()
    assert status["status"] == "running"
    assert status["phase"] == "matching"
    assert status["message"] == "Matching"
    assert status["next_run_at"] == "2026-05-04T08:00:00+00:00"


def test_active_lock_recovers_status_reset_to_idle(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))
    pipeline_status.set_status(
        status="idle",
        phase="idle",
        finished_at=None,
        phase_started_at="2026-05-02T10:00:00+00:00",
        phase_history=[{"phase": "initializing", "duration_seconds": 3}],
    )
    token = pipeline_status.acquire_run_lock(ttl_seconds=30)

    try:
        status = pipeline_status.get_status()
        assert status["status"] == "running"
        assert status["phase"] == "matching"
        assert status["message"].startswith("Pipeline process active")
    finally:
        assert token is not None
        pipeline_status.release_run_lock(token)


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


def test_liveness_reconciliation_preserves_a_live_owned_process(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "runtime"))
    token = pipeline_status.acquire_run_lock(ttl_seconds=300)
    pipeline_status.set_status(
        status="running",
        phase="stop_matching",
        run_id="run-live",
        phase_started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert token is not None
    assert pipeline_status.reconcile_orphaned_run(stale_after_seconds=1, lock_ttl_seconds=300) is False
    assert pipeline_status.get_status()["status"] == "running"
    pipeline_status.release_run_lock(token)


def test_liveness_reconciliation_fails_a_dead_owned_process(monkeypatch, tmp_path):
    import socket
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import get_pipeline_state_store

    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "runtime"))
    store = get_pipeline_state_store()
    assert store.acquire_lock(
        "dead-token",
        ttl_seconds=14400,
        owner={
            "host": socket.gethostname(),
            "runtime_instance": "previous-container-lifetime",
            "pid": 999999,
            "process_start_ticks": "1",
        },
    )
    pipeline_status.set_status(
        status="running",
        phase="database",
        run_id="run-dead",
        phase_started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert pipeline_status.reconcile_orphaned_run(stale_after_seconds=9999) is True
    recovered = pipeline_status.get_status()
    assert recovered["status"] == "failed"
    assert recovered["failed_phase"] == "database"
    assert "stopped unexpectedly" in recovered["last_error"]
    assert store.read_lock() == {}


def test_liveness_reconciliation_recovers_a_stale_legacy_lease(monkeypatch, tmp_path):
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import get_pipeline_state_store

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))
    stale_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
    (runtime_dir / "pipeline_lock.json").write_text(json.dumps({
        "token": "legacy-token",
        "acquired_at": stale_heartbeat.isoformat(),
        "expires_at": (stale_heartbeat + timedelta(seconds=300)).isoformat(),
    }), encoding="utf-8")
    pipeline_status.set_status(
        status="running",
        phase="import",
        run_id="legacy-run",
        phase_started_at=stale_heartbeat.isoformat(),
    )

    assert pipeline_status.reconcile_orphaned_run(
        stale_after_seconds=60,
        lock_ttl_seconds=300,
    ) is True
    assert pipeline_status.get_status()["status"] == "failed"
    assert get_pipeline_state_store().read_lock() == {}


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


def test_running_pipeline_is_present_in_server_rendered_navbar_and_bootstrap_state(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(stats_export, "load_stats_from_file", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "status": "running",
            "phase": "matching",
            "message": "Matching sources",
            "blocking_maintenance": False,
            "last_pipeline_data_import_ended_at": "2026-05-02T19:31:00+02:00",
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    html = client.get("/").get_data(as_text=True)

    assert '<span id="navbarDataUpdatedText">Pipeline running in the background</span>' in html
    assert 'window.initialPipelineStatus = {' in html
    assert '"phase": "matching"' in html
    assert '"status": "running"' in html


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
    from backend.jobs import job_runner
    monkeypatch.setenv('DATABASE_URI', 'test-database-secret')
    monkeypatch.setenv('SECRET_KEY', 'test-session-secret')
    monkeypatch.setenv('SOURCE_API_TOKEN', 'source-token')
    monkeypatch.setattr(job_runner, 'set_phase', lambda **kwargs: None)
    captured = {}
    class Process:
        stdout = iter(())

        def wait(self):
            return 0

    def popen(command, **kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setattr(job_runner.subprocess, 'Popen', popen)
    job_runner._run_subprocess(['transport-matcher', '--help'], 'matching', 'Matching')
    assert 'DATABASE_URI' not in captured['env']
    assert 'SECRET_KEY' not in captured['env']
    assert captured['env']['SOURCE_API_TOKEN'] == 'source-token'


def test_engine_progress_ignores_unversioned_log_events(monkeypatch):
    from backend.jobs import job_runner

    events = []
    monkeypatch.setattr(job_runner, 'record_progress_event', lambda payload, **kwargs: events.append(payload))

    job_runner._handle_engine_progress({
        'event': 'stage_started',
        'stage': 'matching.stops_and_problems',
    })
    job_runner._handle_engine_progress({
        'event': 'cache_decision',
        'stage': 'atlas',
        'reason': 'hit',
    })

    assert events == []


def test_engine_progress_forwards_versioned_events_without_stage_mapping(monkeypatch):
    from backend.jobs import job_runner

    events = []
    monkeypatch.setattr(job_runner, 'record_progress_event', lambda payload, **kwargs: events.append(payload))
    payload = {
        'event': 'stage_started',
        'progress_schema_version': 1,
        'stage_id': 'osm.future_parser',
        'stage_spec': {
            'id': 'osm.future_parser',
            'parent_id': 'osm',
            'phase': 'osm',
            'label': 'Future parser',
            'description': 'A stage unknown to this application version.',
            'order': 99,
            'progress_kind': 'indeterminate',
        },
    }

    job_runner._handle_engine_progress(payload)

    assert events == [payload]
