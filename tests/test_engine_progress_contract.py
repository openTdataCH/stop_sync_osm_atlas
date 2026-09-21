"""Optional composition test. Normal app tests need no engine installation."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.importing.bundle import read_bundle
from backend.services.pipeline_progress import apply_progress_event, initial_progress_plan


pytestmark = pytest.mark.skipif(not os.getenv('PROGRESS_CONTRACT_ENGINE'), reason='Set PROGRESS_CONTRACT_ENGINE for producer/consumer checks')


@pytest.mark.parametrize('mode', ['swiss', 'swiss-local-gtfs', 'gtfs'])
def test_engine_events_are_accepted_and_resolve_in_consumer(mode, tmp_path):
    engine = Path(os.environ['PROGRESS_CONTRACT_ENGINE']).resolve()
    examples = engine / 'examples'
    if mode == 'gtfs':
        args = ['gtfs', '--source', str(examples / 'gtfs'), '--namespace', 'demo', '--osm', str(examples / 'osm.xml')]
    else:
        args = ['swiss', '--source', str(examples / 'swiss/stops_ATLAS.csv'), '--osm', str(examples / 'swiss/osm.xml'),
                '--processed', str(examples / 'swiss/processed')]
        if mode == 'swiss-local-gtfs':
            args += ['--gtfs', str(examples / 'gtfs')]
    output = tmp_path / 'result'
    result = subprocess.run([sys.executable, '-m', 'transport_matcher.cli', *args, '--output', str(output)],
                            env={**os.environ, 'PYTHONPATH': str(engine / 'src')}, capture_output=True, text=True, check=True)
    events = []
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and 'progress_schema_version' in value:
            events.append(value)
    assert events and events[0]['event'] == 'pipeline_plan'
    state = dict(status='running', run_id='composition-test', phase='source_check',
                 stage_plan=initial_progress_plan(), stage_states={})
    for event in events:
        state.update(apply_progress_event(state, event, '2026-09-21T10:00:00+00:00', owner='engine', run_id='composition-test'))
    plan = events[0]['stages']
    assert all(state['stage_states'][spec['id']]['status'] == 'complete' for spec in plan)
    assert all(state['stage_states'][spec['phase']]['status'] == 'complete' for spec in plan)
    bundle = read_bundle(output)
    assert bundle['matches'] and bundle['routes']
