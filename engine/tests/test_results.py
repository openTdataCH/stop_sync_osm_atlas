"""Producer result contract, integrity and atomic publication tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import threading

import pytest

from transport_matcher import match, SourceStop, OsmNode, write_bundle
from transport_matcher.results import InvalidResult, validate_bundle, validate_output


def example():
    return match(
        [SourceStop('demo', 'near', 52., 13., name='Near'), SourceStop('demo', 'far', 52.2, 13.2, name='Far')],
        [OsmNode('100', 52., 13., name='Near'), OsmNode('100', 52.4, 13.4, element_type='way')],
    )


def read_sections(path):
    manifest = json.loads((path / 'manifest.json').read_text())
    return manifest, {section: [json.loads(line) for line in gzip.open(path / info['name'], 'rt', encoding='utf-8')]
                      for section, info in manifest['files'].items()}


def test_roundtrip_preserves_semantic_output_typed_ids_and_quality(tmp_path):
    result = example()
    path = write_bundle(result, tmp_path / 'run')
    manifest = validate_bundle(path)
    stored_manifest, rows = read_sections(path)
    assert manifest == stored_manifest
    assert {row['key'] for row in rows['source_stops']} == {'demo:near', 'demo:far'}
    assert {row['key'] for row in rows['osm_nodes']} == {'osm:node:100', 'osm:way:100'}
    assert [(row['source_key'], row['osm_key'], row['method']) for row in rows['matches']] == [('demo:near', 'osm:node:100', 'name')]
    assert {row['key'] for row in rows['unmatched']} == {'demo:far', 'osm:way:100'}
    assert {row['problem_id'] for row in rows['problems']} == {problem.problem_id for problem in result.problems}
    assert next(row['value'] for row in rows['extensions'] if row['kind'] == 'quality_metrics')['distance_quality']['overall']['count'] == 1
    for section, info in manifest['files'].items():
        content = (path / info['name']).read_bytes()
        assert info['sha256'] == hashlib.sha256(content).hexdigest()
        assert info['bytes'] == len(content)
        assert info['rows'] == len(rows[section])


@pytest.mark.parametrize('mutation,message', [
    (lambda out: out.all_source_nodes.pop(), 'complete entity list'),
    (lambda out: (out.unmatched_source.clear(), out.source_isolated_keys.clear()), 'Source match coverage'),
    (lambda out: out.osm_stop_units.pop(), 'stop-unit coverage'),
    (lambda out: out.problems.clear(), 'unmatched detection coverage'),
    (lambda out: out.matched.append(out.matched[0]), 'Duplicate match pair'),
    (lambda out: setattr(out.matched[0], 'distance_m', float('nan')), 'match distance'),
    (lambda out: out.effectively_matched_osm_ids.append('way_100'), 'Effective-match status'),
])
def test_invalid_outputs_never_publish_partial_results(tmp_path, mutation, message):
    result = example()
    mutation(result)
    with pytest.raises(InvalidResult, match=message):
        write_bundle(result, tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
    assert list(tmp_path.glob('.matching-*')) == []


def test_detection_cannot_reference_an_unknown_entity(tmp_path):
    result = example()
    result.problems[0] = replace(result.problems[0], source_keys=('other:missing',))
    with pytest.raises(InvalidResult, match='unknown entities'):
        write_bundle(result, tmp_path / 'bad')


def test_route_result_foreign_keys_are_validated(tmp_path):
    result = example()
    result.routes = {'itineraries': [{'id': 1, 'line_family_id': 99}]}
    with pytest.raises(InvalidResult, match='unknown route family'):
        write_bundle(result, tmp_path / 'bad')


def test_route_evidence_foreign_keys_are_validated(tmp_path):
    result = example()
    result.source_route_evidence_by_key['missing:source'] = {'gtfs': []}
    with pytest.raises(InvalidResult, match='Route evidence references unknown source'):
        write_bundle(result, tmp_path / 'bad')


def test_existing_directory_is_never_overwritten_even_when_empty(tmp_path):
    path = tmp_path / 'existing'
    path.mkdir()
    with pytest.raises(FileExistsError):
        write_bundle(example(), path)
    assert list(path.iterdir()) == []
    sentinel = path / 'reviewed.txt'
    sentinel.write_text('keep')
    with pytest.raises(FileExistsError):
        write_bundle(example(), path)
    assert sentinel.read_text() == 'keep'


def test_publication_failure_cleans_up_temporary_directory(tmp_path, monkeypatch):
    from transport_matcher.results import bundle
    def reject(*args):
        raise OSError('simulated publication failure')
    monkeypatch.setattr(bundle, '_publish_directory', reject)
    with pytest.raises(OSError, match='publication failure'):
        write_bundle(example(), tmp_path / 'bad')
    assert list(tmp_path.iterdir()) == []


def test_serialized_validation_failure_cleans_up_temporary_directory(tmp_path, monkeypatch):
    from transport_matcher.results import validation
    def reject(*args):
        raise InvalidResult('simulated serialization failure')
    monkeypatch.setattr(validation, 'validate_bundle', reject)
    with pytest.raises(InvalidResult, match='serialization failure'):
        write_bundle(example(), tmp_path / 'bad')
    assert list(tmp_path.iterdir()) == []


def test_concurrent_writers_publish_exactly_one_complete_bundle(tmp_path, monkeypatch):
    from transport_matcher.results import bundle
    original = bundle._publish_directory
    barrier = threading.Barrier(2)
    def together(temporary, destination):
        barrier.wait(timeout=10)
        return original(temporary, destination)
    monkeypatch.setattr(bundle, '_publish_directory', together)
    def run():
        try:
            return write_bundle(example(), tmp_path / 'same')
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        outputs = list(workers.map(lambda _: run(), range(2)))
    assert sum(output is not None for output in outputs) == 1
    validate_bundle(tmp_path / 'same')
    assert list(tmp_path.glob('.matching-*')) == []


def test_checksum_and_count_corruption_are_rejected(tmp_path):
    path = write_bundle(example(), tmp_path / 'run')
    manifest_path = path / 'manifest.json'
    original = json.loads(manifest_path.read_text())
    changed = deepcopy(original)
    changed['files']['matches']['rows'] += 1
    manifest_path.write_text(json.dumps(changed))
    with pytest.raises(InvalidResult, match='Row count mismatch'):
        validate_bundle(path)
    manifest_path.write_text(json.dumps(original))
    with (path / original['files']['matches']['name']).open('ab') as handle:
        handle.write(b'changed')
    with pytest.raises(InvalidResult, match='Checksum or size mismatch'):
        validate_bundle(path)


def test_optional_station_reference_keeps_original_osm_tag_fields(tmp_path):
    from transport_matcher import MatchingProfile, ReferenceRule, Reference
    profile = MatchingProfile(
        station_reference_matching=True, osm_station_ref_tag='ref:local-station',
        reference_rules=(ReferenceRule('local-station', 'ref:local-station', scope='station'),),
    )
    result = match(
        [SourceStop('local', 'stop', 52., 13., station_ref='X', references=(Reference('local-station', 'X', 'station'),))],
        [OsmNode('100', 52., 13., tags={'ref:local-station': 'X', 'uic_ref': 'original-uic'})],
        profile,
    )
    path = write_bundle(result, tmp_path / 'custom-reference')
    _, rows = read_sections(path)
    row = rows['osm_nodes'][0]
    assert row['station_reference'] == 'X'
    assert row['uic_ref'] == row['tags']['uic_ref'] == 'original-uic'
    assert row['tags']['ref:local-station'] == 'X'
    assert row['key'] == 'osm:node:100'
