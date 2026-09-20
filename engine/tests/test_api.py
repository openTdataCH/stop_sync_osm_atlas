"""Public API portability and allocation invariants, entirely offline."""
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from transport_matcher.api import match
from transport_matcher.core.models import SourceStop, OsmNode, Reference
from transport_matcher.core.state import SourceState, OsmState
from transport_matcher.core.route_state import RouteState
from transport_matcher.profiles import MatchingProfile, ReferenceRule, SWITZERLAND


def test_non_swiss_fixture_has_complete_results_without_identifiers_or_routes():
    data = json.loads((Path(__file__).parent / 'fixtures/berlin.json').read_text())
    source = [SourceStop(**row) for row in data['source']]
    osm = [OsmNode(**row) for row in data['osm']]
    output = match(source, osm)
    assert {(row.source_node.source_id, row.osm_node.node_id, row.match_type) for row in output.matched} == {
        ('central', '100', 'name'), ('riverside', '101', 'distance_matching_3a'),
    }
    assert [row.key for row in output.unmatched_source] == ['berlin-demo:remote']
    assert [row.node_id for row in output.unmatched_osm] == ['102']
    assert output.source_isolated_keys == ['berlin-demo:remote']
    assert output.isolated_osm_ids == ['102']
    assert {(p.problem_type, p.source_keys, p.osm_ids) for p in output.problems} == {
        ('unmatched', ('berlin-demo:remote',), ()), ('unmatched', (), ('102',)),
    }
    assert len(output.osm_stop_units) == 3
    assert output.diagnostics[0]['code'] == 'route_evidence_unavailable'
    assert all(row.evidence['rule'] == row.match_type for row in output.matched)


def test_exact_identifiers_require_compatible_namespace_and_scope():
    sources = [
        SourceStop('feed-a', '1', 52., 13., references=(Reference('feed-a', '1'),)),
        SourceStop('feed-b', '1', 52., 13., references=(Reference('feed-b', '1'),)),
        SourceStop('feed-a', 'parent', 52., 13., references=(Reference('feed-a', '1', 'station'),)),
    ]
    osm = [OsmNode('1', 52., 13., tags={'gtfs:stop_id': '1', 'gtfs:feed': 'a'})]
    profile = MatchingProfile(predicate_names=('exact',), reference_rules=(
        ReferenceRule('feed-a', 'gtfs:stop_id', osm_scope_tag='gtfs:feed', osm_scope_value='a'),
    ))
    output = match(sources, osm, profile)
    assert [row.source_node.key for row in output.matched] == ['feed-a:1']
    assert {row.key for row in output.unmatched_source} == {'feed-b:1', 'feed-a:parent'}
    incompatible_osm = [OsmNode('1', 52., 13., tags={'gtfs:stop_id': '1', 'gtfs:feed': 'b'})]
    assert match(sources, incompatible_osm, profile).matched == []


def test_co_located_osm_elements_keep_distinct_typed_identity():
    nodes = [OsmNode('123', 52., 13.), OsmNode('123', 52., 13., element_type='way')]
    state = OsmState.from_records(nodes)
    assert {node.key for node in state.get_all_nodes()} == {'osm:node:123', 'osm:way:123'}
    assert len(state.batch_query_radius([(52., 13.)], 50)[0]) == 2
    assert len(match([], state).unmatched_osm) == 2


def test_runs_copy_allocation_state_and_do_not_share_route_equivalences():
    source = SourceState([SourceStop('demo', '1', 52., 13., name='One')])
    osm = OsmState.from_records([OsmNode('1', 52., 13., name='One')])
    first = match(source, osm)
    second = match(source, osm)
    assert asdict(first) == asdict(second)
    assert not source.matched_ids and not osm.used_ids
    a, b = RouteState({'rel': 'feed-a:line'}), RouteState()
    assert a.get_source_route('rel') == 'feed-a:line'
    assert b.get_source_route('rel') is None


def test_route_namespace_collisions_do_not_create_matches():
    source = SourceState([SourceStop('a', '1', 52., 13.)], route_evidence_by_key={
        'a:1': {'gtfs': [{'route_id': 'a:route:7', 'direction_id': '0'}]},
    })
    osm = OsmState.from_records([OsmNode('1', 52., 13.)], node_routes={
        '1': [{'gtfs_route_id': 'b:route:7', 'direction_id': '0'}],
    })
    profile = MatchingProfile(predicate_names=('route',))
    assert match(source, osm, profile).matched == []
    osm._node_routes['1'][0]['gtfs_route_id'] = 'a:route:7'
    assert match(source, osm, profile).matched[0].match_type == 'route_gtfs_tokens'


def swiss_stop(identifier, lon, code):
    return SourceStop('atlas', identifier, 47., lon, name='Stop', platform_code=code,
                      station_ref='850001', references=(Reference('uic', '850001', 'station'),))


def test_swiss_station_reference_preserves_multiple_links_and_duplicate_propagation():
    a, b = swiss_stop('a', 8., 'A'), swiss_stop('b', 8.00001, 'A')
    source = SourceState([a, b], {a.key: [a.key, b.key], b.key: [a.key, b.key]})
    output = match(source, [OsmNode('1', 47., 8., uic_ref='850001')], SWITZERLAND)
    assert {(row.source_node.key, row.osm_node.node_id, row.match_type) for row in output.matched} == {
        ('atlas:a', '1', 'exact'), ('atlas:b', '1', 'duplicate_propagation'),
    }
    assert output.unmatched_source == []
    assert output.duplicate_key_map == source.duplicate_key_map


def test_trio_middle_is_effectively_matched_with_no_unmatched_problem():
    source = [swiss_stop('a', 8., 'A'), swiss_stop('b', 8.0001, 'B')]
    osm = [
        OsmNode('1', 47., 8., uic_ref='850001', public_transport='platform'),
        OsmNode('2', 47., 8.0001, uic_ref='850001', public_transport='platform'),
        OsmNode('3', 47., 8.00005, uic_ref='850001', public_transport='stop_position'),
    ]
    output = match(source, osm, SWITZERLAND)
    assert {row.osm_node.node_id for row in output.matched} == {'1', '2'}
    assert output.effectively_matched_osm_ids == ['3']
    assert output.osm_stop_units[0].stop_kind == 'trio'
    assert not [problem for problem in output.problems if problem.problem_type == 'unmatched']


def test_matched_distance_problem_is_calculated_before_any_app_import():
    source = [swiss_stop('far', 8., 'A')]
    output = match(source, [OsmNode('1', 47., 8.01, uic_ref='850001')], SWITZERLAND)
    assert output.matched[0].problems[0].problem_type == 'distance'
    assert output.problems[0].source_keys == ('atlas:far',)
    assert output.problems[0].priority == 1


def test_zero_distance_ratio_candidate_does_not_divide_by_zero():
    profile = MatchingProfile(predicate_names=('nearest_ratio',))
    output = match([SourceStop('demo', '1', 52., 13.)],
                   [OsmNode('1', 52., 13.), OsmNode('2', 52.0002, 13.)], profile)
    assert output.matched[0].osm_node.node_id == '1'


@pytest.mark.parametrize('lat,lon', [(float('nan'), 13.), (52., float('inf')), (91., 13.)])
def test_invalid_positions_are_rejected(lat, lon):
    with pytest.raises(ValueError, match='coordinates'):
        SourceStop('demo', '1', lat, lon)


def test_duplicate_source_keys_fail_before_matching():
    node = SourceStop('demo', '1', 52., 13.)
    with pytest.raises(ValueError, match='Duplicate source keys'):
        match([node, node], [])


def test_conflicting_stop_identifiers_are_diagnosed_without_arbitrary_exact_link():
    sources = [SourceStop('feed', key, 52., 13., references=(Reference('feed-stop', 'x'),)) for key in ['a', 'b']]
    profile = MatchingProfile(predicate_names=('exact',), reference_rules=(ReferenceRule('feed-stop', 'gtfs:stop_id'),))
    output = match(sources, [OsmNode('1', 52., 13., tags={'gtfs:stop_id': 'x'})], profile)
    assert not output.matched
    diagnostic = next(row for row in output.diagnostics if row['code'] == 'ambiguous_exact_reference')
    assert diagnostic['source_keys'] == ['feed:a', 'feed:b']


def test_source_duplicate_groups_must_be_disjoint():
    nodes = [SourceStop('feed', key, 52., 13.) for key in ['a', 'b', 'c']]
    with pytest.raises(ValueError, match='overlapping groups'):
        SourceState(nodes, {'feed:a': ['feed:a', 'feed:b'], 'feed:b': ['feed:b', 'feed:c']})


def test_quality_statistics_accept_missing_groups_and_equatorial_coordinates():
    from transport_matcher.statistics import compute_quality_metrics
    output = match([SourceStop('equator', '1', 0., 0., name='Stop')], [OsmNode('1', 0., 0., name='Stop')])
    metrics = compute_quality_metrics(output.matched, output.all_osm_nodes)
    assert metrics['cross_predicate_consistency']['total_evaluated'] == 1
    assert metrics['cross_predicate_consistency']['consistent_with_nearest'] == 1


def test_core_import_boundary_has_no_app_or_parser_dependencies():
    import ast
    import transport_matcher.core
    root = Path(transport_matcher.core.__file__).parent
    forbidden = {'backend', 'flask', 'sqlalchemy', 'pandas', 'requests', 'os', 'pathlib'}
    for path in root.rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            assert not {module.split('.')[0] for module in modules} & forbidden, str(path)


def test_quality_statistics_treat_co_located_elements_as_equally_close():
    from transport_matcher.statistics import compute_quality_metrics
    output = match([SourceStop('demo', '1', 52., 13., name='Target')],
                   [OsmNode('1', 52., 13., name='Other'), OsmNode('2', 52., 13., name='Target')])
    metrics = compute_quality_metrics(output.matched, output.all_osm_nodes)
    assert metrics['distance_quality']['not_matched_to_closest']['count'] == 0


def test_generic_name_problem_compares_osm_name_and_swiss_retains_uic_name_policy():
    source = [SourceStop('demo', '1', 52., 13., name='Expected')]
    osm = [OsmNode('1', 52., 13., name='Different', public_transport='platform')]
    generic = match(source, osm, MatchingProfile(predicate_names=('nearest_single',)))
    assert generic.matched[0].match_type == 'distance_matching_3a'
    assert [problem.problem_type for problem in generic.problems] == ['attributes']
    swiss = match(source, osm, replace(SWITZERLAND, predicate_names=('nearest_single',)))
    assert swiss.problems == []


def test_custom_station_reference_groups_without_rewriting_osm_tags():
    profile = MatchingProfile(
        osm_station_ref_tag='ref:station', station_reference_matching=True, osm_grouping=True,
        reference_rules=(ReferenceRule('local-station', 'ref:station', scope='station'),),
        predicate_names=('exact',),
    )
    source = [SourceStop('agency', key, 47., lon, station_ref='X', platform_code=code,
                         references=(Reference('local-station', 'X', 'station'),))
              for key, lon, code in [('a', 8., 'A'), ('b', 8.001, 'B')]]
    osm = [OsmNode(identifier, 47., lon, local_ref=code, public_transport=kind,
                   tags={'ref:station': 'X', 'uic_ref': 'unrelated-original-value'})
           for identifier, lon, code, kind in [('1', 8., 'A', 'platform'), ('2', 8.00001, 'A', 'stop_position'),
                                               ('3', 8.001, 'B', 'platform'), ('4', 8.00101, 'B', 'stop_position')]]
    output = match(source, osm, profile)
    assert len(output.matched) == 4
    assert [unit.stop_kind for unit in output.osm_stop_units] == ['pair', 'pair']
    assert all(node.station_ref == 'X' for node in output.all_osm_nodes)
    assert all(node.uic_ref == node.tags['uic_ref'] == 'unrelated-original-value' for node in output.all_osm_nodes)
    assert not [problem for problem in output.problems if problem.problem_type == 'attributes']


def test_station_group_proximity_does_not_treat_equal_unscoped_values_as_evidence():
    profile = MatchingProfile(
        predicate_names=('group_proximity',), station_reference_matching=True,
        reference_rules=(ReferenceRule('uic', 'uic_ref', scope='station', source_namespace='agency-a',
                                      osm_scope_tag='network', osm_scope_value='A'),),
    )
    source = [SourceStop('agency-a', '1', 52., 13., station_ref='X', references=(Reference('uic', 'X', 'station'),))]
    osm = [OsmNode('1', 52., 13., tags={'uic_ref': 'X', 'network': 'B'})]
    assert match(source, osm, profile).matched == []
    source_without_reference = [replace(source[0], references=())]
    matching_osm = [OsmNode('1', 52., 13., tags={'uic_ref': 'X', 'network': 'A'})]
    assert match(source_without_reference, matching_osm, profile).matched == []


def test_exact_reference_builds_osm_index_once_for_many_identifiers(monkeypatch):
    from transport_matcher.core.state import OsmState
    calls = []
    original = OsmState.get_all_unmatched_grouped
    def counted(state, key):
        calls.append(key)
        return original(state, key)
    monkeypatch.setattr(OsmState, 'get_all_unmatched_grouped', counted)
    sources = [SourceStop('feed', str(i), 52., 13., references=(Reference('feed-stop', str(i)),)) for i in range(100)]
    osm = [OsmNode(str(i), 52., 13., tags={'gtfs:stop_id': str(i)}) for i in range(100)]
    profile = MatchingProfile(predicate_names=('exact',), reference_rules=(ReferenceRule('feed-stop', 'gtfs:stop_id'),))
    output = match(sources, osm, profile)
    assert len(output.matched) == 100
    assert calls == ['gtfs:stop_id']


def test_name_alias_index_preserves_swiss_occurrences_and_generic_tag_order():
    nodes = [
        OsmNode('1', 52., 13., tags={'name': 'Central;Centre', 'uic_name': 'Central;Centre', 'gtfs:name': 'Central GTFS'}),
        OsmNode('2', 52., 13., tags={'name': 'Central;Centre', 'uic_name': 'Other'}),
    ]
    swiss = OsmState.from_records(nodes, preserve_name_alias_multiplicity=True)
    generic = OsmState.from_records(nodes)
    assert list(swiss._name_index) == list(generic._name_index) == ['Central;Centre', 'Central GTFS', 'Other']
    assert [row['node_id'] for row in swiss._name_index['Central;Centre']] == ['1', '1', '2']
    assert [row['node_id'] for row in generic._name_index['Central;Centre']] == ['1', '2']
    assert 'Central' not in swiss._name_index and 'Centre' not in generic._name_index


def test_swiss_name_matching_retains_repeated_alias_candidate_cardinality():
    source = [SourceStop('atlas', 'one', 47., 8., name='Stop;Alias')]
    osm = [OsmNode('1', 47., 8., tags={'name': 'Stop;Alias', 'uic_name': 'Stop;Alias'})]
    swiss = match(source, osm, replace(SWITZERLAND, predicate_names=('name',)))
    generic = match(source, osm, MatchingProfile(predicate_names=('name',)))
    # Original Swiss parser presented two alias occurrences to NameMatchPredicate;
    # with no platform code this remained ambiguous and passed to later rules.
    assert swiss.matched == []
    assert [row.osm_node.node_id for row in generic.matched] == ['1']


def test_swiss_name_pair_grouping_preserves_alias_occurrence_counts():
    source = [SourceStop('atlas', 'one', 47., 8., name='Stop', station_ref='u1',
                         references=(Reference('uic', 'u1', 'station'),))]
    osm = [
        OsmNode('1', 47., 8., tags={'public_transport': 'platform', 'name': 'Stop', 'uic_name': 'Stop'}),
        OsmNode('2', 47., 8.00001, tags={'public_transport': 'stop_position', 'name': 'Stop'}),
    ]
    swiss = match(source, osm, replace(SWITZERLAND, predicate_names=()))
    deduplicated = match(source, osm, replace(SWITZERLAND, predicate_names=(), preserve_name_alias_multiplicity=False))
    assert [unit.stop_kind for unit in swiss.osm_stop_units] == ['single', 'single']
    assert [unit.stop_kind for unit in deduplicated.osm_stop_units] == ['pair']


def test_group_proximity_retains_station_reference_evidence_from_osm_sibling():
    source = [SourceStop('atlas', 'one', 47., 8., name='Station', station_ref='u1',
                         references=(Reference('uic', 'u1', 'station'),))]
    osm = [OsmNode('1', 47., 8., name='Station', public_transport='platform'),
           OsmNode('2', 47., 8.00001, name='Station', uic_ref='u1', public_transport='stop_position')]
    result = match(source, osm, replace(SWITZERLAND, predicate_names=('group_proximity',)))
    assert result.osm_stop_units[0].group_kind == 'osm_pair_name'
    assert [(row.osm_node.node_id, row.match_type) for row in result.matched] == [
        ('1', 'distance_matching_1_uic_ref'), ('2', 'osm_group_propagation'),
    ]
