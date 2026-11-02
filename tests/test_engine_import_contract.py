"""Run the real engine on its examples and import each bundle into PostGIS.

The engine runs as a subprocess in its own interpreter (``ENGINE_PYTHON``), so
the app never imports it. The tests need ``ENGINE_PYTHON``, the engine checkout
(``ENGINE_DIR`` or the sibling ``../engine``) and ``TEST_POSTGRES_URI``;
``make quality`` and CI provide all three, and other runs skip.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import text

from backend.extensions import db
from backend.importing.bundle import read_bundle
from backend.importing.importer import build_fast_insert_payloads, _write_rows
from backend.importing.projection import project_bundle
from backend.importing.publication import publish_snapshot
from backend.services.pipeline_progress import apply_progress_event, initial_progress_plan

MODES = ('gtfs', 'swiss', 'swiss-local-gtfs')


def _cli_args(mode, examples):
    swiss = ['swiss', '--source', examples / 'swiss/stops_ATLAS.csv', '--osm', examples / 'swiss/osm.xml',
             '--processed', examples / 'swiss/processed']
    return {
        'gtfs': ['gtfs', '--source', examples / 'gtfs', '--namespace', 'demo', '--osm', examples / 'osm.xml'],
        'swiss': swiss,
        'swiss-local-gtfs': [*swiss, '--gtfs', examples / 'gtfs'],
    }[mode]


@pytest.fixture(scope='session')
def engine_run(tmp_path_factory):
    """Return ``run(mode) -> (progress events, bundle directory)``; each mode runs once."""
    python = os.getenv('ENGINE_PYTHON')
    if not python:
        pytest.skip('Set ENGINE_PYTHON to an interpreter with the engine dependencies')
    root = Path(os.getenv('ENGINE_DIR') or Path(__file__).resolve().parents[2] / 'engine').resolve()
    examples = root / 'examples'
    if not examples.is_dir():
        pytest.skip(f'No engine checkout with examples at {root}')
    runs = {}

    def run(mode):
        if mode not in runs:
            output = tmp_path_factory.mktemp(mode) / 'bundle'
            command = [python, '-m', 'osm_public_transport_matcher.cli', *map(str, _cli_args(mode, examples)), '--output', str(output)]
            result = subprocess.run(command,
                                    env={**os.environ, 'PYTHONPATH': str(root / 'src')}, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            runs[mode] = (_progress_events(result.stdout), output)
        return runs[mode]

    return run


def _progress_events(stdout):
    events = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and 'progress_schema_version' in value:
            events.append(value)
    return events


def _publish(engine, bundle_dir):
    bundle = read_bundle(bundle_dir)
    publish_snapshot(engine, build_fast_insert_payloads(*project_bundle(bundle)), _write_rows, manifest=bundle['manifest'])
    return bundle['manifest']


@pytest.mark.parametrize('mode', MODES)
def test_engine_progress_events_resolve_in_the_consumer(mode, engine_run):
    events, _ = engine_run(mode)
    assert events and events[0]['event'] == 'pipeline_plan'
    state = dict(status='running', run_id='composition-test', phase='source_check',
                 stage_plan=initial_progress_plan(), stage_states={})
    roots = {spec['id']: spec['order'] for spec in state['stage_plan'] if spec['parent_id'] is None}
    planned = sorted(events[0]['stages'], key=lambda spec: (roots[spec['phase']], spec['order']))
    finished = [event['stage_id'] for event in events if event['event'] == 'stage_finished']
    assert finished == [spec['id'] for spec in planned]
    for event in events:
        state.update(apply_progress_event(state, event, '2026-09-21T10:00:00+00:00', owner='engine', run_id='composition-test'))
    plan = events[0]['stages']
    assert all(state['stage_states'][spec['id']]['status'] == 'complete' for spec in plan)
    assert all(state['stage_states'][spec['phase']]['status'] == 'complete' for spec in plan)


@pytest.mark.parametrize('mode', MODES)
def test_engine_bundle_publishes_into_postgis(mode, engine_run, postgres):
    manifest = _publish(postgres, engine_run(mode)[1])
    with postgres.connect() as connection:
        assert connection.execute(text('SELECT run_id FROM dataset_publication')).scalar() == manifest['run_id']
        assert connection.execute(text('SELECT count(*) FROM stops_matched')).scalar()


def test_the_examples_together_fill_every_snapshot_table(engine_run, postgres):
    """An engine change that silently empties a table fails here."""
    filled = set()
    for mode in MODES:
        _publish(postgres, engine_run(mode)[1])
        with postgres.connect() as connection:
            filled |= {table.name for table in db.Model.metadata.sorted_tables
                       if connection.execute(text(f'SELECT count(*) FROM "{table.name}"')).scalar()}
    assert {table.name for table in db.Model.metadata.sorted_tables} - filled == set()
