"""Offline boundary regressions for normalized sources and complete runs."""
import csv
from pathlib import Path

import pandas as pd
import pytest

from transport_matcher.adapters.atlas import atlas_records, atlas_state
from transport_matcher.adapters.gtfs import read_gtfs, run_gtfs
from transport_matcher.adapters.osm import read_osm
from transport_matcher.adapters.get_atlas_gtfs import build_gtfs_db_payload_rows
from transport_matcher.adapters.get_osm_data import process_osm_routes_data
from transport_matcher.swiss import run_matching


def _csv(path, rows, *, delimiter=','):
    with Path(path).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def _feed(path, *, routes=True):
    path.mkdir()
    _csv(path / 'stops.txt', [
        {'stop_id': 'A', 'stop_name': 'Alpha', 'stop_lat': '48.0', 'stop_lon': '2.0'},
        {'stop_id': 'B', 'stop_name': 'Beta', 'stop_lat': '48.002', 'stop_lon': '2.0'},
    ])
    if routes:
        _csv(path / 'routes.txt', [{'route_id': 'R-j25', 'route_short_name': '1', 'route_type': '3'}])
        _csv(path / 'trips.txt', [{'trip_id': 'T', 'route_id': 'R-j25', 'direction_id': '0', 'trip_headsign': 'Loop'}])
        _csv(path / 'stop_times.txt', [
            {'trip_id': 'T', 'stop_id': 'A', 'stop_sequence': '30'},
            {'trip_id': 'T', 'stop_id': 'B', 'stop_sequence': '20'},
            {'trip_id': 'T', 'stop_id': 'A', 'stop_sequence': '10'},
        ])
    return path


def _osm(path):
    path.write_text('''<osm>
      <node id="1" lat="48.0" lon="2.0"><tag k="name" v="Alpha"/><tag k="public_transport" v="platform"/></node>
      <node id="2" lat="48.002" lon="2.0"><tag k="name" v="Beta"/><tag k="public_transport" v="platform"/></node>
      <relation id="100">
        <tag k="type" v="route"/><tag k="route" v="bus"/><tag k="gtfs:route_id" v="R-j25"/><tag k="ref_trips" v="T.H"/>
        <member type="node" ref="1" role="platform"/><member type="node" ref="2" role="platform"/><member type="node" ref="1" role="platform"/>
      </relation>
    </osm>''', encoding='utf-8')
    return path


def test_gtfs_without_swiss_identifiers_preserves_feed_scope_and_repeated_calls(tmp_path):
    feed = _feed(tmp_path / 'feed')
    first = read_gtfs(feed, namespace='paris')
    second = read_gtfs(feed, namespace='lyon')
    paris = set(first.source.get_all_rows_as_dict())
    lyon = set(second.source.get_all_rows_as_dict())
    assert paris == {'paris:A', 'paris:B'}
    assert not paris & lyon
    assert all(not stop.station_ref for stop in first.source.get_all_rows_as_dict().values())
    calls = first.route_data['atlas_itinerary_stop_calls']
    assert list(calls.stop_sequence) == [10, 20, 30]
    assert list(calls.canonical_stop_key) == ['paris:A', 'paris:B', 'paris:A']
    assert first.source.get_route_evidence('paris:A')['gtfs'][0]['route_id_normalized'] == 'paris:route:R-j25'


def test_gtfs_stops_only_is_supported_and_partial_routes_fail(tmp_path):
    feed = _feed(tmp_path / 'feed', routes=False)
    assert read_gtfs(feed, namespace='paris').route_data == {}
    _csv(feed / 'routes.txt', [{'route_id': 'R', 'route_type': '3'}])
    with pytest.raises(ValueError, match='evidence is incomplete'):
        read_gtfs(feed, namespace='paris')


def test_generic_run_compares_ordered_itineraries_and_keeps_namespace(tmp_path):
    output = run_gtfs(_feed(tmp_path / 'feed'), _osm(tmp_path / 'osm.xml'), namespace='paris')
    assert {(item.source_node.key, item.osm_node.node_id) for item in output.matched} == {('paris:A', '1'), ('paris:B', '2')}
    assert output.routes['matched_routes'] == 1
    assert len(output.routes['itinerary_matches']) == 1
    assert output.routes['itinerary_matches'][0]['stop_score'] == 1.0
    assert [call['canonical_stop_key'] for call in output.routes['stop_calls'][:3]] == ['paris:A', 'paris:B', 'paris:A']


def test_osm_adapter_preserves_collocated_nodes_and_typed_way_identity(tmp_path):
    path = tmp_path / 'osm.xml'
    path.write_text('''<osm>
      <node id="1" lat="48" lon="2"><tag k="public_transport" v="platform"/></node>
      <node id="2" lat="48" lon="2"><tag k="public_transport" v="stop_position"/></node>
      <way id="1"><center lat="48" lon="2"/><tag k="aerialway" v="station"/><tag k="public_transport" v="station"/></way>
    </osm>''')
    assert {node.key for node in read_osm(path).get_all_nodes()} == {'osm:node:1', 'osm:node:2', 'osm:way:1'}


def test_direct_gtfs_identity_keeps_atlas_coordinates_across_uic_numbers():
    traffic_points = pd.DataFrame([
        {'sloid': 'ch:1:sloid:target', 'number': '8509999', 'wgs84North': 47.5, 'wgs84East': 8.5},
    ])
    payload = {
        'gtfs_stops': pd.DataFrame([{'stop_id': '8500001:0:A', 'uic_number': '8500001', 'stop_lat': 47.5, 'stop_lon': 8.5}]),
        'matches': pd.DataFrame([{'stop_id': '8500001:0:A', 'sloid': 'ch:1:sloid:target', 'match_method': 'original_stop_id'}]),
    }
    _, states = build_gtfs_db_payload_rows(payload, traffic_points)
    assert states[0]['resolved_sloid'] == 'ch:1:sloid:target'
    assert (states[0]['atlas_lat'], states[0]['atlas_lon']) == (47.5, 8.5)


def test_swiss_runner_uses_only_explicit_files_and_returns_complete_products(tmp_path, monkeypatch):
    source = tmp_path / 'atlas.csv'
    _csv(source, [
        {'sloid': 'ch:1:sloid:A', 'number': '8500001', 'designation': 'A', 'designationOfficial': 'Alpha', 'wgs84North': '48', 'wgs84East': '2'},
        {'sloid': 'ch:1:sloid:B', 'number': '8500002', 'designation': 'B', 'designationOfficial': 'Beta', 'wgs84North': '48.002', 'wgs84East': '2'},
    ], delimiter=';')
    osm = _osm(tmp_path / 'osm.xml')
    other_directory = tmp_path / 'other'
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    output = run_matching(source, osm)
    assert len(output.matched) == 2
    assert output.all_source_nodes[0].key == 'atlas:ch:1:sloid:A'
    assert output.extensions['gtfs_stops'] == []
    assert output.extensions['gtfs_atlas_state'] == []
    assert 'gtfs_identity' not in output.metadata['capabilities']
    assert output.routes['osm_route_relations'][0]['relation_id'] == '100'
    assert 'routes' in output.metadata['capabilities']
    assert list(other_directory.iterdir()) == []
    assert output.metadata['inputs'][0]['sha256']


def test_empty_osm_products_replace_stale_cached_files(tmp_path):
    stale = tmp_path / 'osm_route_relations.csv'
    stale.write_text('relation_id,gtfs_route_id\nold,old\n')
    products = process_osm_routes_data('<osm/>', out_dir=tmp_path)
    assert products['osm_route_relations'].empty
    assert pd.read_csv(stale).empty


def test_generic_unknown_direction_is_optional_and_gtfs_namespace_is_resolved(tmp_path):
    feed = _feed(tmp_path / 'feed')
    osm = _osm(tmp_path / 'osm.xml')
    osm.write_text(osm.read_text().replace('<tag k="ref_trips" v="T.H"/>', ''))
    output = run_gtfs(feed, osm, namespace='gtfs')
    assert output.routes['itinerary_matches'][0]['match_reason'] == 'ordered_stop_match_direction_unknown'
    assert output.routes['itinerary_matches'][0]['direction_score'] == 0
    osm.write_text(osm.read_text().replace('<tag k="type" v="route"/>', '<tag k="type" v="route"/><tag k="ref_trips" v="T.R"/>'))
    assert run_gtfs(feed, osm, namespace='gtfs').routes['itinerary_matches'] == []


def test_swiss_fresh_gtfs_exports_identity_and_normalized_route_match_without_source_writes(tmp_path):
    feed = _feed(tmp_path / 'feed')
    _csv(feed / 'stops.txt', [
        {'stop_id': '8500001:0:A', 'original_stop_id': 'ch:1:sloid:A', 'stop_name': 'Alpha', 'stop_lat': '48', 'stop_lon': '2'},
        {'stop_id': '8500002:0:B', 'original_stop_id': 'ch:1:sloid:B', 'stop_name': 'Beta', 'stop_lat': '48.002', 'stop_lon': '2'},
    ])
    # The Swiss streaming reader keeps the complete real call order.
    _csv(feed / 'stop_times.txt', [
        {'trip_id': 'T', 'stop_id': '8500001:0:A', 'stop_sequence': '10'},
        {'trip_id': 'T', 'stop_id': '8500002:0:B', 'stop_sequence': '20'},
    ])
    source = tmp_path / 'atlas.csv'
    _csv(source, [
        {'sloid': 'ch:1:sloid:A', 'number': '8500001', 'designation': 'A', 'designationOfficial': 'Alpha', 'wgs84North': '48', 'wgs84East': '2'},
        {'sloid': 'ch:1:sloid:B', 'number': '8500002', 'designation': 'B', 'designationOfficial': 'Beta', 'wgs84North': '48.002', 'wgs84East': '2'},
    ], delimiter=';')
    osm = _osm(tmp_path / 'osm.xml')
    osm.write_text(osm.read_text().replace('R-j25', 'R-j24'))
    before = {path.name: path.read_bytes() for path in feed.iterdir()}
    output = run_matching(source, osm, gtfs_dir=feed)
    assert len(output.extensions['gtfs_stops']) == 2
    assert 'gtfs_identity' in output.metadata['capabilities']
    assert {row['resolved_sloid'] for row in output.extensions['gtfs_atlas_state']} == {'ch:1:sloid:A', 'ch:1:sloid:B'}
    assert output.routes['line_family_matches'][0]['match_method'] == 'normalized_gtfs_route_id'
    assert {item['filename'] for item in output.metadata['inputs']} >= {'stops.txt', 'stop_times.txt', 'routes.txt', 'trips.txt'}
    assert {path.name: path.read_bytes() for path in feed.iterdir()} == before


def test_explicit_boundary_changes_between_runs_are_respected(tmp_path):
    import json
    pytest.importorskip('geopandas')
    from transport_matcher.adapters.geo_utils import filter_points_in_switzerland
    boundary = tmp_path / 'boundary.geojson'
    frame = pd.DataFrame([{'lat': 0.5, 'lon': 0.5}, {'lat': 3.5, 'lon': 3.5}])
    def write_square(start):
        boundary.write_text(json.dumps({'type': 'Polygon', 'coordinates': [[
            [start, start], [start + 1, start], [start + 1, start + 1], [start, start + 1], [start, start],
        ]]}))
    write_square(0)
    first = filter_points_in_switzerland(frame, 'lat', 'lon', boundary_geojson=str(boundary))
    write_square(3)
    second = filter_points_in_switzerland(frame, 'lat', 'lon', boundary_geojson=str(boundary))
    assert first['lat'].tolist() == [0.5]
    assert second['lat'].tolist() == [3.5]


def test_swiss_snapshot_matches_original_head_golden_decisions():
    import json
    example = Path(__file__).resolve().parents[1] / 'examples/swiss'
    expected = json.loads((example / 'expected.json').read_text())
    output = run_matching(example / 'stops_ATLAS.csv', example / 'osm.xml', example / 'processed')
    pairs = [(m.source_node.source_id, m.osm_node.node_id, m.match_type, round(m.distance_m, 5)) for m in output.matched]
    assert sorted(pairs) == sorted(tuple(row) for row in expected['pairs'])
    assert sorted(node.source_id for node in output.unmatched_source) == expected['unmatched_source']
    assert sorted(node.node_id for node in output.unmatched_osm) == expected['unmatched_osm']
    assert output.effectively_matched_osm_ids == expected['effectively_matched_osm_ids']
    groups = [{'kind': u.stop_kind, 'group': u.group_kind, 'rep': u.representative_node_id,
               'members': [[m.node_id, m.member_role] for m in u.members]} for u in output.osm_stop_units]
    assert groups == expected['groups']
    duplicates = {key.removeprefix('atlas:'): [value.removeprefix('atlas:') for value in members]
                  for key, members in output.duplicate_key_map.items()}
    assert duplicates == expected['duplicates']
    problems = [(m.source_node.source_id, m.osm_node.node_id, p.problem_type, p.priority)
                for m in output.matched for p in m.problems]
    for problem in output.problems:
        if not problem.osm_ids:
            problems.extend((key.removeprefix('atlas:'), None, problem.problem_type, problem.priority) for key in problem.source_keys)
        if not problem.source_keys:
            problems.extend((None, node, problem.problem_type, problem.priority) for node in problem.osm_ids)
    assert sorted(problems, key=repr) == sorted([tuple(row) for row in expected['problems']], key=repr)
    assert output.routes['line_family_matches'] == expected['line_family_matches']
    assert output.routes['itinerary_matches'] == expected['itinerary_matches']


def test_gtfs_parent_station_cannot_compete_with_its_boarding_stop(tmp_path):
    feed = tmp_path / 'feed'
    feed.mkdir()
    _csv(feed / 'stops.txt', [
        {'stop_id': 'parent', 'stop_name': 'Central', 'stop_lat': '48', 'stop_lon': '2', 'location_type': '1', 'parent_station': ''},
        {'stop_id': 'platform', 'stop_name': 'Central', 'stop_lat': '48', 'stop_lon': '2', 'location_type': '0', 'parent_station': 'parent'},
    ])
    adapter = read_gtfs(feed, namespace='demo')
    assert list(adapter.source.get_all_rows_as_dict()) == ['demo:platform']
    assert adapter.source.get_by_key('demo:platform').parent_id == 'demo:parent'
    assert len(adapter.extensions['gtfs_source']['stops']) == 2


def test_osm_evidence_only_indexes_exported_elements_and_reports_external_stops(tmp_path):
    from transport_matcher.adapters.route_products import unresolved_osm_member_diagnostics
    path = _osm(tmp_path / 'osm.xml')
    path.write_text(path.read_text().replace('</relation>', '<member type="node" ref="999" role="platform"/></relation>'))
    state = read_osm(path)
    assert set(state._node_routes) == {'1', '2'}
    assert '999' not in state.name_dirs
    products = process_osm_routes_data(path.read_text(), out_dir=None)
    diagnostics = unresolved_osm_member_diagnostics(products)
    assert diagnostics[0]['count'] == 1
    assert diagnostics[0]['examples'][0]['element_id'] == '999'
    members = products['osm_route_relation_members']
    products['osm_route_relation_members'] = pd.concat([members] * 12, ignore_index=True)
    repeated = unresolved_osm_member_diagnostics(products)[0]
    assert repeated['count'] == 12
    assert len(repeated['examples']) == 10
