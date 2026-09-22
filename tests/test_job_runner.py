import logging
from types import SimpleNamespace

import pytest

from backend.jobs import job_runner


def test_timed_step_logs_success(caplog):
    with caplog.at_level(logging.INFO, logger="backend.jobs.job_runner"):
        with job_runner._timed_step("osm_download"):
            pass

    assert "Step osm_download completed successfully in" in caplog.text


def test_timed_step_logs_failure(caplog):
    with pytest.raises(RuntimeError, match="boom"):
        with caplog.at_level(logging.ERROR, logger="backend.jobs.job_runner"):
            with job_runner._timed_step("osm_download"):
                raise RuntimeError("boom")

    assert "Step osm_download failed after" in caplog.text


def test_missing_engine_explains_how_to_rebuild_scheduler(monkeypatch):
    monkeypatch.setattr(job_runner, 'set_phase', lambda **kwargs: None)

    def missing_executable(command, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', command[0])

    monkeypatch.setattr(job_runner.subprocess, 'Popen', missing_executable)
    with pytest.raises(RuntimeError, match='docker compose build scheduler') as error:
        job_runner._run_subprocess(['transport-matcher', 'swiss'], 'matching', 'Matching')
    assert '--force-recreate scheduler' in str(error.value)
    assert 'MATCHER_COMMAND' in str(error.value)


def test_import_bundle_reports_projection_and_analytics(monkeypatch):
    from backend.importing import importer
    from backend.services import data_meta

    progress = []
    stage_events = []
    base_data = SimpleNamespace(
        gtfs_atlas_stats={},
        duplicate_sloid_map={},
    )
    manifest = {'run_id': 'run-1', 'metadata': {'capabilities': []}}
    monkeypatch.setattr(importer, 'read_bundle', lambda directory: {'manifest': manifest})
    monkeypatch.setattr(importer, 'project_bundle', lambda bundle: (base_data, {}, {}))
    monkeypatch.setattr(importer, 'build_fast_insert_payloads', lambda *args: {})

    def import_to_database(*, progress_callback, **kwargs):
        progress_callback('publish', 'Publishing the new dataset')
        return set()

    monkeypatch.setattr(importer, 'import_to_database', import_to_database)
    monkeypatch.setattr(importer, '_write_gtfs_atlas_stats', lambda payload: None)
    monkeypatch.setattr(importer, 'export_stats_after_import', lambda *args: {'summary': {}})
    monkeypatch.setattr(data_meta, 'update_data_meta', lambda **kwargs: None)

    importer.import_bundle(
        'bundle',
        progress_callback=lambda phase, message: progress.append((phase, message)),
        stage_event_callback=stage_events.append,
    )

    assert progress == [
        ('database', 'Validating the result bundle'),
        ('database', 'Preparing application records'),
        ('database', 'Loading and indexing the staged database'),
        ('publish', 'Publishing the new dataset'),
        ('publish', 'Generating analytics for the published dataset'),
    ]
    assert [(event['event'], event['stage_id']) for event in stage_events] == [
        ('stage_started', 'database.validate'),
        ('stage_finished', 'database.validate'),
        ('stage_started', 'database.prepare'),
        ('stage_finished', 'database.prepare'),
        ('stage_started', 'publish.analytics'),
        ('stage_finished', 'publish.analytics'),
    ]


@pytest.mark.parametrize('failure', ['empty_result', 'exception'])
def test_analytics_failure_preserves_publication_and_reports_failed_stage(monkeypatch, failure):
    from pathlib import Path
    from backend.importing import importer

    published = []
    events = []
    # Real bundle validation and projection; only database and report I/O are replaced.
    monkeypatch.setattr(importer, 'import_to_database', lambda **kw: published.append(kw['manifest']) or set())
    monkeypatch.setattr(importer, '_write_gtfs_atlas_stats', lambda data: None)

    def export(*args):
        if failure == 'exception':
            raise OSError('report disk unavailable')
        return None

    monkeypatch.setattr(importer, 'export_stats_after_import', export)
    bundle = Path(__file__).parent / 'fixtures/result-v1'
    with pytest.raises(importer.PublishedDatasetError, match='Dataset published') as error:
        importer.import_bundle(bundle, stage_event_callback=events.append)
    assert error.value.manifest == published[0]
    analytics = [event for event in events if event['stage_id'] == 'publish.analytics']
    assert [event['event'] for event in analytics] == ['stage_started', 'stage_failed']
    assert analytics[-1]['error']


def test_progress_delivery_never_masks_work_outcome():
    from backend.importing.progress import progress_stage

    def broken_report(event):
        raise OSError('status store unavailable')

    completed = []
    with progress_stage('publish.swap', broken_report):
        completed.append('committed')
    assert completed == ['committed']
    with pytest.raises(ValueError, match='work failed'):
        with progress_stage('database.load', broken_report):
            raise ValueError('work failed')


def test_runner_reports_published_dataset_with_analytics_warning(monkeypatch):
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import MemoryPipelineStateStore
    from backend.importing.importer import PublishedDatasetError

    store = MemoryPipelineStateStore()
    monkeypatch.setattr(pipeline_status, 'get_pipeline_state_store', lambda: store)
    monkeypatch.setenv('PIPELINE_BUNDLE', '/unused-test-bundle')
    monkeypatch.setattr(job_runner, '_record_data_updated_timestamp', lambda *args: None)
    monkeypatch.setattr(job_runner.data_meta, 'update_data_meta', lambda **kw: None)

    def imported(directory, stage_event_callback):
        for stage_id in ('database.validate', 'database.prepare', 'database.load', 'publish.swap', 'publish.analytics'):
            for kind in ('stage_started', 'stage_failed' if stage_id == 'publish.analytics' else 'stage_finished'):
                stage_event_callback(dict(event=kind, progress_schema_version=2, stage_id=stage_id))
        raise PublishedDatasetError({'run_id': 'published-run', 'schema_version': 1}, 'report disk unavailable')

    monkeypatch.setattr(job_runner, 'import_bundle', imported)
    assert job_runner.run_pipeline('import') == 0
    status = store.read_status()
    assert status['dataset_published'] is True
    assert status['warnings']
    assert status['stage_states']['publish.swap']['status'] == 'complete'
    assert status['stage_states']['publish.analytics']['status'] == 'failed'
    assert status['stage_states']['publish']['status'] == 'failed'
    assert status['status'] == 'idle'


@pytest.mark.parametrize('mode', ['match-import', 'import'])
def test_reused_run_modes_keep_input_loading_separate(monkeypatch, mode):
    from backend.services import pipeline_status
    from backend.services.pipeline_state_store import MemoryPipelineStateStore

    store = MemoryPipelineStateStore()
    monkeypatch.setattr(pipeline_status, 'get_pipeline_state_store', lambda: store)
    monkeypatch.setenv('PIPELINE_BUNDLE', '/unused-test-bundle')
    monkeypatch.setattr(job_runner, '_record_data_updated_timestamp', lambda *args: None)
    monkeypatch.setattr(job_runner.data_meta, 'update_data_meta', lambda **kw: None)
    observed = []
    monkeypatch.setattr(job_runner, '_run_subprocess', lambda *args, **kw: observed.append(store.read_status()))

    def imported(*args, **kwargs):
        observed.append(store.read_status())
        return {'run_id': 'test', 'schema_version': 1}

    monkeypatch.setattr(job_runner, 'import_bundle', imported)
    assert job_runner.run_pipeline(mode) == 0
    before_work = observed[0]
    if mode == 'match-import':
        assert before_work['phase'] == 'matching_inputs'
        assert before_work['phase_outcomes'] == {'source_check': 'skipped', 'source_files': 'reused'}
        assert before_work['stage_states']['matching_inputs']['status'] == 'running'
    else:
        assert before_work['phase_outcomes'] == {
            **dict.fromkeys(('source_check', 'source_files', 'matching_inputs', 'stop_matching', 'route_matching'), 'skipped'),
            'bundle': 'reused',
        }
