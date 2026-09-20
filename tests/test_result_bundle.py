"""Consumer contract tests use published fixture bytes, not engine imports."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from backend.importing.bundle import InvalidBundle, read_bundle, validate_records
from backend.importing.projection import project_bundle

EXAMPLE = Path(__file__).resolve().parents[1] / 'tests/fixtures/result-v1'


def test_example_projects_complete_entities_problems_and_groups():
    bundle = read_bundle(EXAMPLE)
    result, problems, routes = project_bundle(bundle)
    assert len(result.matched) == 1
    assert len(result.unmatched_atlas) == len(result.unmatched_osm) == 1
    assert result.matched[0].atlas_node.sloid == 'demo:a'
    assert result.matched[0].osm_node.node_id == '101'
    assert problems['unmatched_atlas_problem_map'][id(result.unmatched_atlas[0])]['problems']
    assert len(result.osm_stop_units) == 2
    assert routes == {'route_write_payload': {}}


@pytest.mark.parametrize('mutation, message', [
    (lambda b: b['matches'][0].update(source_key='missing'), 'unknown entity'),
    (lambda b: b['source_stops'].append(b['source_stops'][0]), 'Duplicate source'),
    (lambda b: b['source_stops'][0].update(lat=float('nan')), 'Invalid coordinates'),
    (lambda b: b['matches'][0].update(distance_m=-1), 'Invalid match distance'),
    (lambda b: b['unmatched'].clear(), 'coverage is incomplete'),
    (lambda b: b['groups'][0]['members'][0].update(node_id='missing'), 'Unknown OSM group'),
])
def test_rejects_inconsistent_domain_references(mutation, message):
    bundle = deepcopy(read_bundle(EXAMPLE))
    mutation(bundle)
    with pytest.raises(InvalidBundle, match=message):
        validate_records(bundle)


def test_incompatible_or_partial_bundle_rejected_before_projection(tmp_path):
    directory = tmp_path / 'result'
    shutil.copytree(EXAMPLE, directory)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schema_version'] = 999
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidBundle, match='Unsupported'):
        read_bundle(directory)
    manifest['schema_version'] = 1
    manifest_path.write_text(json.dumps(manifest))
    (directory / 'matches.jsonl.gz').write_bytes(b'incomplete')
    with pytest.raises(InvalidBundle, match='file size'):
        read_bundle(directory)


def test_consumer_has_no_engine_imports():
    import ast
    backend = Path(__file__).resolve().parents[1] / 'backend'
    for path in backend.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert all(not name.startswith(('transport_matcher', 'matching_and_import_db')) for name in names), path


def test_consumer_reads_bundle_when_engine_import_is_forbidden():
    script = '''
import sys
class BlockEngine:
    def find_spec(self, fullname, *args):
        if fullname.startswith('transport_matcher'):
            raise ImportError('engine deliberately unavailable')
sys.meta_path.insert(0, BlockEngine())
from backend.importing.bundle import read_bundle
from backend.importing.projection import project_bundle
from backend.app import create_app
project_bundle(read_bundle(sys.argv[1]))
app = create_app()
assert app.test_client().get('/health').status_code in (200, 404)
'''
    subprocess.run([sys.executable, '-c', script, str(EXAMPLE)], check=True)


@pytest.mark.parametrize('mutation, message', [
    (lambda b: b['unmatched'][1].update(effectively_matched='false'), 'effective-match status'),
    (lambda b: b['unmatched'][0].update(isolated='false'), 'isolation status'),
    (lambda b: b['unmatched'][1].update(effectively_matched=True), 'disagrees with trio'),
    (lambda b: b['groups'][0].update(stop_kind='trio'), 'stop-unit roles'),
    (lambda b: b['groups'][0]['members'][0].update(member_role='pair_a'), 'stop-unit roles'),
    (lambda b: b['problems'].clear(), 'unmatched detection coverage'),
    (lambda b: b['matches'][0].update(problems=[None]), 'Problem must be an object'),
    (lambda b: b['source_stops'][0].update(namespace='feed:agency', key='feed:agency:a'), 'source namespace'),
    (lambda b: b['routes'].append({'kind': 'itineraries', 'value': [{'id': 1, 'line_family_id': 123}]}), 'unknown route family'),
    (lambda b: b['diagnostics'].append({'message': 'missing code'}), 'stable code'),
    (lambda b: b['extensions'].append({'kind': 'gtfs_stops', 'value': None}), 'Invalid gtfs_stops extension'),
    (lambda b: b['routes'].append({'kind': 'stop_calls'}), 'Missing routes entry value'),
])
def test_consumer_rejects_semantically_invalid_snapshots(mutation, message):
    bundle = deepcopy(read_bundle(EXAMPLE))
    mutation(bundle)
    with pytest.raises(InvalidBundle, match=message):
        validate_records(bundle)


def test_osm_identity_type_prefix_prevents_projection_collisions():
    bundle = deepcopy(read_bundle(EXAMPLE))
    way = {**bundle['osm_nodes'][0], 'element_type': 'way', 'key': 'osm:way:101'}
    bundle['osm_nodes'].append(way)
    bundle['unmatched'].append({'side': 'osm', 'key': way['key'], 'isolated': False, 'effectively_matched': False})
    with pytest.raises(InvalidBundle, match='type prefix'):
        validate_records(bundle)


def test_matched_diagnostics_keep_pair_scope_and_merge_general_detections_without_duplicates():
    bundle = deepcopy(read_bundle(EXAMPLE))
    first = bundle['matches'][0]
    second = {**deepcopy(first), 'osm_key': 'osm:node:102'}
    bundle['matches'].append(second)
    bundle['unmatched'] = [row for row in bundle['unmatched'] if row['side'] != 'osm']
    bundle['problems'] = [row for row in bundle['problems'] if not row['osm_ids']]
    first['problems'] = [{'problem_type': 'distance', 'priority': 1}]
    bundle['problems'].extend([
        {'problem_id': 'distance-pair', 'problem_type': 'distance', 'priority': 1,
         'source_keys': [first['source_key']], 'osm_ids': ['101']},
        {'problem_id': 'extra-pair', 'problem_type': 'attributes', 'priority': 2,
         'source_keys': [first['source_key']], 'osm_ids': ['101']},
        {'problem_id': 'source-group', 'problem_type': 'duplicates', 'priority': 3,
         'source_keys': [first['source_key']], 'osm_ids': []},
    ])
    validate_records(bundle)
    result, _, _ = project_bundle(bundle)
    assert [(p.problem_type, p.priority) for p in result.matched[0].problems] == [
        ('distance', 1), ('attributes', 2), ('duplicates', 3),
    ]
    assert [(p.problem_type, p.priority) for p in result.matched[1].problems] == [('duplicates', 3)]


@pytest.mark.parametrize('descriptor', [None, [], 'invalid'])
def test_malformed_manifest_file_descriptor_is_reported_as_invalid_bundle(tmp_path, descriptor):
    directory = tmp_path / 'result'
    shutil.copytree(EXAMPLE, directory)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['source_stops'] = descriptor
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidBundle, match='Invalid file descriptor'):
        read_bundle(directory)
