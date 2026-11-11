"""The stored pipeline status, its run lease and the recovery of a dead runner."""
import json
from datetime import datetime, timedelta, timezone


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


def test_failure_reports_the_failed_stage_and_its_own_cause(monkeypatch):
    from backend.services import pipeline_status

    stored = {}
    monkeypatch.setattr(pipeline_status, "_read_raw_status", lambda: dict(stored))
    monkeypatch.setattr(pipeline_status, "_patch_raw_status", lambda fields: stored.update(fields) or dict(stored))
    spec = {"id": "osm.download", "parent_id": "source_files", "phase": "source_files",
            "label": "Download OSM data from Overpass", "description": "Request the OSM snapshot.",
            "order": 50, "progress_kind": "indeterminate"}
    cause = "Overpass request failed: https://overpass-api.de/api/interpreter: HTTP 504 (3 attempts)"

    pipeline_status.start_run(trigger="manual", run_id="run-overpass")
    pipeline_status.record_progress_event({"event": "pipeline_plan", "progress_schema_version": 2, "stages": [spec]})
    for event in ({"event": "stage_started"}, {"event": "stage_failed", "error": cause}):
        pipeline_status.record_progress_event(
            {**event, "progress_schema_version": 2, "stage_id": spec["id"], "stage_spec": spec, "seconds": 1})
    failed = pipeline_status.finish_failure("The matching engine exited with code 1")

    assert failed["failed_stage"] == "osm.download"
    assert failed["failed_phase"] == "source_files"
    assert failed["last_error"] == f"Download OSM data from Overpass: {cause}"

    pipeline_status.start_run(trigger="manual", run_id="run-killed")
    killed = pipeline_status.finish_failure("The matching engine exited with code -9")
    assert killed["failed_stage"] is None
    assert killed["last_error"] == "The matching engine exited with code -9"


def test_data_warning_reports_a_failed_or_overdue_update():
    from backend.services.pipeline_status import _data_warning

    published = "2026-10-30T03:00:00+01:00"
    assert _data_warning({"status": "failed", "last_pipeline_data_import_ended_at": published}) == (
        "Latest update failed; showing data from 2026-10-30 03:00")
    assert _data_warning({"status": "failed"}) == "Latest update failed; no data is published yet"
    # A failure after the switch still shows the newest data.
    assert _data_warning({"status": "failed", "dataset_published": True,
                          "last_pipeline_data_import_ended_at": published}) is None

    now = datetime.now(timezone.utc)
    recent = {"status": "idle", "schedule_interval_hours": 24,
              "last_pipeline_data_import_ended_at": (now - timedelta(hours=47)).isoformat()}
    overdue = dict(recent, last_pipeline_data_import_ended_at=(now - timedelta(hours=49)).isoformat())
    assert _data_warning(recent) is None
    assert _data_warning(overdue).startswith("No update for more than 48 hours; showing data from ")
    assert _data_warning(dict(overdue, schedule_interval_hours=None)) is None


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
    reused = pipeline_status.set_phase_outcome("source_files", "reused")
    assert reused["phase_outcomes"] == {"source_files": "reused"}
    assert reused["phase_history"][-1]["phase"] == "source_files"
    assert reused["phase_history"][-1]["status"] == "reused"
    assert reused["phase_history"][-1]["duration_seconds"] == 0.0
    assert reused["phase_history"][-1]["started_at"] == reused["phase_history"][-1]["finished_at"]

    active = pipeline_status.set_phase("source_files", "Preparing ATLAS data")
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
        "parent_id": "matching_inputs",
        "phase": "matching_inputs",
        "label": "A future parser stage",
        "description": "Delivered by a newer engine without an application code change.",
        "order": 99,
        "progress_kind": "indeterminate",
    }

    pipeline_status.record_progress_event({
        "event": "pipeline_plan",
        "progress_schema_version": 2,
        "stages": [spec],
    })
    pipeline_status.record_progress_event({
        "event": "stage_started",
        "progress_schema_version": 2,
        "stage_id": spec["id"],
        "stage_spec": spec,
        "seconds": 0,
    })
    completed = pipeline_status.record_progress_event({
        "event": "stage_finished",
        "progress_schema_version": 2,
        "stage_id": spec["id"],
        "stage_spec": spec,
        "seconds": 3.25,
    })

    assert completed["phase"] == "matching_inputs"
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
    pipeline_status.set_phase_outcome("source_files", "reused")
    status = pipeline_status.record_progress_event(dict(event="pipeline_plan", progress_schema_version=2, stages=[{
        "id": "timetable.engine_owned",
        "parent_id": "source_files",
        "phase": "source_files",
        "label": "Engine-owned timetable work",
        "description": "Arrives after the runner has recorded reuse.",
        "order": 10,
        "progress_kind": "indeterminate",
    }]))

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
    pipeline_status.record_progress_event(dict(event="pipeline_plan", progress_schema_version=2, stages=[{
        "id": "atlas.prepare",
        "parent_id": "source_files",
        "phase": "source_files",
        "label": "Prepare ATLAS",
        "description": "Prepare the ATLAS cache.",
        "order": 10,
        "progress_kind": "indeterminate",
    }]))
    status = pipeline_status.record_progress_event(dict(event="stage_outcome", progress_schema_version=2,
                                                        stage_id="atlas.prepare", outcome="reused"))

    assert status["phase_outcomes"]["source_files"] == "reused"
    assert status["stage_states"]["atlas.prepare"]["status"] == "reused"


def test_pipeline_status_file_backend_persists_status(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))

    pipeline_status.set_status(status="running", phase="matching", message="Matching")

    stored = json.loads((runtime_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    assert stored["status"] == "running"
    assert pipeline_status.get_status()["phase"] == "matching"


def test_pipeline_status_patches_do_not_overwrite_run_or_schedule_fields(monkeypatch, tmp_path):
    from backend.services import pipeline_status

    runtime_dir = tmp_path / "runtime"
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

    monkeypatch.setenv("STATE_DIR", str(tmp_path / "runtime"))
    token = pipeline_status.acquire_run_lock(ttl_seconds=300)
    pipeline_status.set_status(
        status="running",
        phase="stop_matching",
        run_id="run-live",
        phase_started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert token is not None
    assert pipeline_status.reconcile_orphaned_run(stale_after_seconds=1) is False
    assert pipeline_status.get_status()["status"] == "running"
    pipeline_status.release_run_lock(token)


def test_liveness_reconciliation_fails_a_dead_owned_process(monkeypatch, tmp_path):
    import socket
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import get_pipeline_state_store

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


def test_liveness_reconciliation_recovers_a_stale_lease_from_another_host(monkeypatch, tmp_path):
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import get_pipeline_state_store

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setenv("STATE_DIR", str(runtime_dir))
    stale_heartbeat = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    (runtime_dir / "pipeline_lock.json").write_text(json.dumps({
        "token": "other-host-token",
        "acquired_at": stale_heartbeat,
        "heartbeat_at": stale_heartbeat,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "owner": {"host": "another-host", "pid": 1},
    }), encoding="utf-8")
    pipeline_status.set_status(
        status="running",
        phase="database",
        run_id="other-host-run",
        phase_started_at=stale_heartbeat,
    )

    assert pipeline_status.reconcile_orphaned_run(stale_after_seconds=60) is True
    assert pipeline_status.get_status()["status"] == "failed"
    assert get_pipeline_state_store().read_lock() == {}
