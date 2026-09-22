"""Public lifecycle behavior, independent of storage and engine implementation."""
from copy import deepcopy

import pytest

from backend.services import pipeline_status
from backend.services.pipeline_progress import (
    ProgressValidationError, apply_progress_event, initial_progress_plan,
)
from backend.services.pipeline_state_store import MemoryPipelineStateStore, FilePipelineStateStore


NOW = "2026-09-21T10:00:00+00:00"
SPEC = dict(id="osm.future", parent_id="matching_inputs", phase="matching_inputs", label="Future parser",
            description="Engine-owned future work", order=10)


def event(kind, **fields):
    return dict(event=kind, progress_schema_version=2, stage_id=SPEC['id'], **fields)


@pytest.fixture
def state():
    plan = initial_progress_plan()
    return dict(status="running", run_id="run-1", phase="source_check", phase_started_at=NOW,
                stage_plan=plan, stage_states={s['id']: {'status': 'waiting'} for s in plan})


@pytest.fixture
def store(monkeypatch):
    store = MemoryPipelineStateStore()
    monkeypatch.setattr(pipeline_status, 'get_pipeline_state_store', lambda: store)
    # Avoid reading operational statistics when testing status persistence.
    store.patch_status({'last_pipeline_data_import_ended_at': NOW})
    pipeline_status.start_run('manual', run_id='run-1')
    pipeline_status.set_progress_plan([SPEC])
    return store


@pytest.mark.parametrize('payload', [
    event('not_an_event', stage_spec=SPEC),
    event('stage_started', stage_spec={**SPEC, 'id': 'osm.other'}),
    event('stage_finished', stage_spec=SPEC, seconds={'invalid': 1}),
    event('stage_finished', stage_spec=SPEC, seconds=float('nan')),
    event('stage_finished', stage_spec=SPEC, seconds=-1),
    event('stage_progress', stage_spec=SPEC, processed=True),
    event('stage_progress', stage_spec=SPEC, processed=2, total=1),
    event('stage_progress', stage_spec=SPEC, counters=[]),
    event('pipeline_plan', stages=[SPEC, SPEC]),
    {**event('stage_started', stage_spec=SPEC), 'progress_schema_version': True},
    {**event('stage_started', stage_spec=SPEC), 'progress_schema_version': 1},
    event('stage_started', stage_spec={**SPEC, 'progress_kind': []}),
])
def test_invalid_event_has_no_side_effects(state, payload):
    before = deepcopy(state)
    with pytest.raises(ProgressValidationError):
        apply_progress_event(state, payload, NOW, owner='engine')
    assert state == before


def test_rejected_event_never_changes_persisted_plan(store):
    before = deepcopy(store.read_status())
    with pytest.raises(ProgressValidationError):
        pipeline_status.record_progress_event(event('unknown', stage_spec={**SPEC, 'id': 'osm.new'}))
    assert store.read_status() == before


@pytest.mark.parametrize('spec', [
    dict(id='new_root', parent_id=None, phase='new_root', label='Root', description='Root', order=100),
    {**SPEC, 'id': 'database.engine', 'parent_id': 'database', 'phase': 'database'},
    initial_progress_plan()[0],
])
def test_engine_cannot_define_roots_or_app_work(state, spec):
    with pytest.raises(ProgressValidationError):
        apply_progress_event(state, event('pipeline_plan', stages=[spec]), NOW, owner='engine')


def test_engine_cannot_drive_existing_app_stage(state):
    with pytest.raises(ProgressValidationError):
        apply_progress_event(state, {**event('stage_started'), 'stage_id': 'publish.swap'}, NOW, owner='engine')


def test_interrupted_run_closes_children_and_cannot_be_reopened(store):
    pipeline_status.record_progress_event(event('stage_started'), run_id='run-1')
    failed = pipeline_status.finish_failure('Engine terminated', run_id='run-1')
    assert failed['stage_states']['osm.future']['status'] == 'failed'
    assert failed['stage_states']['matching_inputs']['status'] == 'failed'
    assert failed['stage_states']['database.validate']['status'] == 'skipped'
    before = deepcopy(store.read_status())
    pipeline_status.record_progress_event(event('stage_progress'), run_id='run-1')
    assert store.read_status() == before
    assert not any(s['status'] == 'running' for s in failed['stage_states'].values())


def test_completed_child_and_parent_stay_complete_after_late_heartbeat(store):
    pipeline_status.record_progress_event(event('stage_started'))
    completed = pipeline_status.record_progress_event(event('stage_finished', seconds=2))
    assert completed['stage_states']['matching_inputs']['status'] == 'complete'
    before = deepcopy(store.read_status())
    pipeline_status.record_progress_event(event('stage_progress', seconds=3))
    assert store.read_status() == before


def test_next_run_resets_plan_and_rejects_previous_writer(store):
    pipeline_status.start_run('manual', run_id='run-2')
    before = deepcopy(store.read_status())
    pipeline_status.record_progress_event(event('stage_started', stage_spec=SPEC), owner='engine', run_id='run-1')
    assert store.read_status() == before
    assert SPEC['id'] not in store.read_status()['stage_states']


@pytest.mark.parametrize('backend', ['memory', 'file'])
def test_storage_rechecks_run_identity_and_terminal_state(backend, tmp_path):
    store = MemoryPipelineStateStore() if backend == 'memory' else FilePipelineStateStore(str(tmp_path))
    store.patch_status(dict(run_id='new', status='running'))
    store.patch_status(dict(message='stale'), expected_run_id='old')
    assert 'message' not in store.read_status()
    store.patch_status(dict(status='failed', finished_at=NOW), expected_run_id='new')
    store.patch_status(dict(status='running'), expected_run_id='new')
    assert store.read_status()['status'] == 'failed'


def test_success_does_not_hide_unresolved_or_failed_children(store):
    pipeline_status.record_progress_event(event('stage_started'))
    finished = pipeline_status.finish_success()
    assert finished['warnings']
    assert finished['stage_states']['osm.future']['status'] == 'failed'
    assert finished['stage_states']['database.validate']['status'] == 'skipped'
    assert not any(s['status'] == 'running' for s in finished['stage_states'].values())


def test_mixed_cache_reuse_and_execution_is_not_a_reused_phase(store):
    other = {**SPEC, 'id': 'osm.second', 'order': 20}
    pipeline_status.set_progress_plan([other])
    pipeline_status.record_progress_event(event('stage_outcome', outcome='reused'))
    pipeline_status.record_progress_event({**event('stage_started'), 'stage_id': other['id']})
    finished = pipeline_status.record_progress_event({**event('stage_finished', seconds=1), 'stage_id': other['id']})
    assert finished['stage_states']['matching_inputs']['status'] == 'complete'
    assert 'matching_inputs' not in finished['phase_outcomes']


def test_runner_ignores_malformed_telemetry_and_keeps_consuming(store):
    from backend.jobs.job_runner import _handle_engine_progress
    _handle_engine_progress(event('stage_finished', seconds={'bad': 1}), run_id='run-1')
    _handle_engine_progress(event('stage_started'), run_id='run-1')
    assert store.read_status()['stage_states'][SPEC['id']]['status'] == 'running'


def test_legacy_finished_run_does_not_acquire_waiting_children(store):
    store.write_status(dict(status='idle', phase='idle', finished_at=NOW, last_pipeline_data_import_ended_at=NOW))
    status = pipeline_status.get_status()
    assert status['stage_plan'] == []
    assert status['stage_states'] == {}
    pipeline_status.start_run('manual', run_id='new')
    assert pipeline_status.get_status()['stage_plan'] == initial_progress_plan()


def test_historical_version_one_plan_keeps_its_recorded_roots(store):
    old_plan = [
        dict(id='osm', parent_id=None, phase='osm', label='Prepare OpenStreetMap', description='OSM', order=40),
        dict(id='osm.prepare', parent_id='osm', phase='osm', label='Parse OSM', description='OSM', order=20),
    ]
    store.write_status(dict(
        status='idle', phase='idle', finished_at=NOW, last_pipeline_data_import_ended_at=NOW,
        progress_schema_version=1, stage_plan=old_plan,
        stage_states={'osm.prepare': {'status': 'complete', 'duration_seconds': 4}},
    ))
    status = pipeline_status.get_status()
    assert status['stage_plan'] == old_plan
    assert status['stage_states']['osm']['status'] == 'complete'
    assert 'matching_inputs' not in status['stage_states']
    pipeline_status.start_run('manual', run_id='new')
    status = pipeline_status.get_status()
    assert status['progress_schema_version'] == 2
    assert status['stage_plan'] == initial_progress_plan()
    assert 'osm' not in status['stage_states']
