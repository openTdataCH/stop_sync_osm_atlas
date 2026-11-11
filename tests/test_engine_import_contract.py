"""Run the real engine on its examples and import each bundle into PostGIS.

The engine runs as a subprocess in its own interpreter (``ENGINE_PYTHON``), so
the app never imports it. The tests need ``ENGINE_PYTHON``, the engine checkout
(``backend.version.engine_dir``) and ``TEST_POSTGRES_URI``;
``make quality`` and CI provide all three, and other runs skip.
"""
from collections import Counter
import json
import os
import subprocess

import pytest
from sqlalchemy import text

from backend.extensions import db
from backend.importing.bundle import read_bundle
from backend.importing.importer import build_fast_insert_payloads, _write_rows
from backend.importing.projection import project_bundle
from backend.importing.publication import publish_snapshot
from backend.services.matching_rules import ALL_MATCH_TYPES
from backend.services.pipeline_progress import apply_progress_event, initial_progress_plan
from backend.version import engine_dir

MODES = ('gtfs', 'swiss', 'swiss-local-gtfs')
SWISS_MODES = ('swiss', 'swiss-local-gtfs')


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
    root = engine_dir()
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


@pytest.mark.parametrize('mode', MODES)
def test_stored_match_types_are_copied_from_the_bundle(mode, engine_run):
    """Matched rows carry the bundle's methods; rows without a bundle match carry none.

    The Swiss example has a two-sided stop: its effectively matched middle has no match
    in the bundle, so it has no match type. ``no_nearby_counterpart`` is the
    application's own label for a source stop with nothing nearby.
    """
    bundle = read_bundle(engine_run(mode)[1])
    rows = build_fast_insert_payloads(*project_bundle(bundle))['stops_matched']
    assert (Counter(row['match_type'] for row in rows if row['stop_type'] == 'matched')
            == Counter(match['method'] for match in bundle['matches']))
    invented = {(row['stop_type'], row['match_type']) for row in rows
                if row['stop_type'] != 'matched' and row['match_type'] is not None} - {('atlas_unmatched', 'no_nearby_counterpart')}
    assert not invented, f'Rows without a bundle match carry a match type: {sorted(invented)}'
    if mode in SWISS_MODES:
        assert any(row['stop_type'] == 'effectively_matched' for row in rows), 'The Swiss example lost its two-sided stop'


@pytest.mark.parametrize('mode', MODES)
def test_line_links_keep_their_match_method_and_stop_score(mode, engine_run):
    bundle = read_bundle(engine_run(mode)[1])
    links = {row['kind']: row['value'] for row in bundle['routes']}['line_family_matches']
    rows = build_fast_insert_payloads(*project_bundle(bundle))['line_family_matches']
    assert links and all(link['stop_score'] is not None for link in links)
    assert (sorted((row['match_method'], row['stop_score']) for row in rows)
            == sorted((link['match_method'], link['stop_score']) for link in links))


@pytest.mark.parametrize('mode', SWISS_MODES)
def test_the_rule_catalog_lists_every_swiss_match_type(mode, engine_run):
    """Fails when the engine renames or adds a match type, so the catalog never goes stale silently."""
    methods = {match['method'] for match in read_bundle(engine_run(mode)[1])['matches']}
    missing = sorted(methods - ALL_MATCH_TYPES)
    assert not missing, (
        f'The engine writes match types that backend/services/matching_rules.py does not list: {missing}. '
        'Add each to its rule there with a label, or rename the old entry: the map filters '
        'and Matches by rule on the analytics page read that file.'
    )


def test_the_examples_together_fill_every_snapshot_table(engine_run, postgres):
    """An engine change that silently empties a table fails here."""
    filled = set()
    for mode in MODES:
        _publish(postgres, engine_run(mode)[1])
        with postgres.connect() as connection:
            filled |= {table.name for table in db.Model.metadata.sorted_tables
                       if connection.execute(text(f'SELECT count(*) FROM "{table.name}"')).scalar()}
    assert {table.name for table in db.Model.metadata.sorted_tables} - filled == set()
