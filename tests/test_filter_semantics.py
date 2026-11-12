import pytest

from backend.models import AtlasStop, DatasetPublication, OsmNode, OsmStop, OsmStopMember, Problem, StopsMatched
from backend.query_builder import apply_common_filters
from backend.queries.helpers import build_match_method_conditions, build_stop_scope_condition, parse_filter_params, resolve_stop_type_match_filters

# One entry per kind of row the filters tell apart, named by its OSM element:
# (stop_type, match_type, OSM public_transport).
STOPS = {
    'ref_local': ('matched', 'uic_reference_local_ref', 'platform'),
    'ref_one_source': ('matched', 'uic_reference_one_source', 'stop_position'),
    'two_sided': ('matched', 'uic_two_sided_stop', 'platform'),
    'middle': ('effectively_matched', None, None),
    'gtfs': ('matched', 'gtfs_shared_route', 'platform'),
    'candidate': ('matched', 'distance_only_candidate', None),
    'candidate_2': ('matched', 'distance_only_candidate_second_pass', None),
    'atlas_alone': ('atlas_unmatched', 'no_nearby_counterpart', None),
    'osm_alone': ('osm_unmatched', None, 'platform'),
    'disused': ('osm_disused', None, None),
}
# OSM stop units: (stop_kind, group_kind, members).
GROUPS = [
    ('pair', 'ptv2_pair_uic_ref', ['ref_local', 'ref_one_source']),
    ('pair', 'ptv2_pair_uic_ref_equal_count', ['gtfs', 'candidate']),
    ('two_sided_stop', 'ptv2_two_sided_stop', ['middle', 'two_sided']),
]
MATCHED = ['candidate', 'candidate_2', 'gtfs', 'middle', 'ref_local', 'ref_one_source', 'two_sided']


@pytest.fixture
def stops(sqlite_tables):
    session = sqlite_tables(AtlasStop, OsmNode, StopsMatched, Problem, DatasetPublication, OsmStop, OsmStopMember)
    for name, (stop_type, match_type, public_transport) in STOPS.items():
        session.add(OsmNode(osm_node_id=name, osm_public_transport=public_transport))
        session.add(StopsMatched(osm_node_id=name, stop_type=stop_type, match_type=match_type))
    for index, (stop_kind, group_kind, members) in enumerate(GROUPS, start=1):
        session.add(OsmStop(id=index, stop_kind=stop_kind, group_kind=group_kind, representative_node_id=members[0]))
        for member in members:
            session.add(OsmStopMember(osm_stop_id=index, node_id=member, member_role='single'))
    session.commit()
    return session


def _names(query):
    return sorted(row.osm_node_id for row in query.all())


def _in_scope(stop_filter, match_method):
    condition = build_stop_scope_condition(StopsMatched, resolve_stop_type_match_filters(stop_filter, match_method))
    return _names(StopsMatched.query.filter(condition))


def _with_filters(filters):
    return _names(apply_common_filters(StopsMatched.query, filters))


def test_matched_methods_apply_without_master_stop_type():
    resolved = resolve_stop_type_match_filters(None, 'reference,name')

    assert resolved['include_matched'] is True
    assert resolved['matched_methods'] == ['reference', 'name']
    assert resolved['include_atlas_unmatched'] is False
    assert resolved['include_osm_unmatched'] is False


def test_matched_stop_type_without_matched_methods_still_includes_all_matched():
    resolved = resolve_stop_type_match_filters('matched', 'no_nearby_counterpart')

    assert resolved['include_matched'] is True
    assert resolved['matched_methods'] == []
    assert resolved['include_atlas_unmatched'] is True


def test_unmatched_reason_applies_without_master_stop_type():
    resolved = resolve_stop_type_match_filters(None, 'no_nearby_counterpart')

    assert resolved['include_matched'] is False
    assert resolved['include_atlas_unmatched'] is True
    assert resolved['unmatched_reason_filters']['no_nearby_counterpart'] is True
    assert resolved['unmatched_reason_filters']['osm_within_50m'] is False


def test_unknown_stop_type_or_method_still_registers_scope_filter():
    resolved = resolve_stop_type_match_filters('unknown_type', 'unknown_method')

    assert resolved['has_scope_filter'] is True
    assert resolved['include_matched'] is False
    assert resolved['include_atlas_unmatched'] is False
    assert resolved['include_osm_unmatched'] is False


def test_reference_rule_filter_selects_each_of_its_match_types(stops):
    assert _in_scope(None, 'reference') == ['ref_local', 'ref_one_source']


def test_two_sided_stop_rule_filter_also_includes_effectively_matched_middles(stops):
    assert _in_scope(None, 'two_sided_stop') == ['middle', 'two_sided']


def test_matched_stop_type_selects_every_match_and_the_two_sided_middles(stops):
    assert _in_scope('matched', None) == MATCHED


def test_match_type_filter_selects_only_that_branch(stops):
    condition = build_match_method_conditions(StopsMatched, ['gtfs_shared_route'])

    assert _names(StopsMatched.query.filter(condition)) == ['gtfs']


def test_rule_filter_covers_every_pass_of_the_rule(stops):
    condition = build_match_method_conditions(StopsMatched, ['distance_only_candidate'])

    assert _names(StopsMatched.query.filter(condition)) == ['candidate', 'candidate_2']


def test_unknown_match_method_selects_nothing():
    assert build_match_method_conditions(StopsMatched, ['distance_matching_1']) is None


def test_parse_filter_params_uses_osm_group_types_without_gate():
    filters = parse_filter_params({'osm_group_types': 'ptv2_pair_uic_ref,ptv2_pair_name'})

    assert filters['osm_group_types'] == ['ptv2_pair_uic_ref', 'ptv2_pair_name']


def test_parse_filter_params_normalizes_osm_group_all_selection():
    filters = parse_filter_params({'osm_group_types': 'all'})

    assert 'osm_group_types' in filters
    assert filters['osm_group_types'] == []


def test_parse_filter_params_keeps_equal_count_pair_group_types():
    filters = parse_filter_params(
        {'osm_group_types': 'ptv2_pair_uic_ref_equal_count,ptv2_pair_name_equal_count,tram_stop_pair_equal_count'}
    )

    assert filters['osm_group_types'] == [
        'ptv2_pair_uic_ref_equal_count',
        'ptv2_pair_name_equal_count',
        'tram_stop_pair_equal_count',
    ]


def test_osm_group_filter_selects_the_group_members_whatever_their_stop_type(stops):
    assert _with_filters({'osm_group_types': ['ptv2_pair_uic_ref']}) == ['ref_local', 'ref_one_source']
    # 'all' parses to an empty list: every member of a pair or two-sided stop.
    assert _with_filters({'osm_group_types': []}) == ['candidate', 'gtfs', 'middle', 'ref_local', 'ref_one_source', 'two_sided']


def test_transport_and_osm_group_filters_both_apply(stops):
    assert _with_filters({'transport_types': ['platform']}) == ['gtfs', 'osm_alone', 'ref_local', 'two_sided']
    assert _with_filters({'transport_types': ['platform'], 'osm_group_types': ['ptv2_pair_uic_ref']}) == ['ref_local']


def test_two_sided_group_filter_selects_only_two_sided_stops(stops):
    assert _with_filters({'osm_group_types': ['ptv2_two_sided_stop']}) == ['middle', 'two_sided']


def test_equal_count_pair_group_filter_selects_its_pairs(stops):
    assert _with_filters({'osm_group_types': ['ptv2_pair_uic_ref_equal_count']}) == ['candidate', 'gtfs']


def test_osm_unmatched_stop_type_leaves_out_two_sided_middles(stops):
    assert _in_scope('osm_unmatched', None) == ['osm_alone']


def test_osm_disused_is_its_own_stop_type(stops):
    resolved = resolve_stop_type_match_filters('osm_disused', None)

    assert resolved['include_osm_disused'] is True
    assert resolved['include_osm_unmatched'] is False
    assert _in_scope('osm_disused', None) == ['disused']


def test_global_stats_leave_disused_osm_out_unless_selected(stops):
    from backend.services.global_stats import _build_scoped_global_stats_query

    assert 'disused' not in _names(_build_scoped_global_stats_query({}))
    assert _names(_build_scoped_global_stats_query({'stop_filter': 'osm_disused'})) == ['disused']


def test_identifier_filters_keep_whole_identifiers_only(problems_db):
    session = problems_db
    rows = [
        ('ch:1:sloid:10035:0:1', '8510035', '100', None),
        ('ch:1:sloid:10035:0:1955', '8510035', '1001', None),
        (None, None, '6151326225', '8530279;8500819'),  # Saanenwald: one stop, two UIC numbers
        (None, None, '61513262250', '85302790'),
    ]
    for sloid, uic_ref, osm_node_id, osm_uic_ref in rows:
        if sloid:
            session.add(AtlasStop(sloid=sloid, uic_ref=uic_ref))
        session.add(OsmNode(osm_node_id=osm_node_id, osm_uic_ref=osm_uic_ref))
        session.add(StopsMatched(sloid=sloid, osm_node_id=osm_node_id, stop_type='matched' if sloid else 'osm_unmatched'))
    session.commit()

    def kept(value, filter_type):
        query = apply_common_filters(
            StopsMatched.query, {'filter_values': [value], 'filter_types': [filter_type]})
        return sorted(row.osm_node_id for row in query.all())

    assert kept('ch:1:sloid:10035:0:1', 'atlas') == ['100']
    assert kept('100', 'osm') == ['100']
    assert kept('6151326225', 'osm') == ['6151326225']
    assert kept('8510035', 'station') == ['100', '1001']
    assert kept('8530279', 'station') == ['6151326225']
    assert kept('8500819', 'station') == ['6151326225']
    assert kept('850081', 'station') == []


def test_a_propagated_pair_follows_the_rule_of_the_match_it_was_propagated_from(problems_db):
    # (sloid, OSM element, match type). A platform matched by UIC reference and its PTv2 stop position, which took
    # the match by propagation, share the ATLAS stop. A platform matched by GTFS route and the ATLAS duplicate that
    # took its match share the OSM element.
    for sloid, node, match_type in [
        ('ch:1:sloid:1', 'platform', 'uic_reference_one_osm'),
        ('ch:1:sloid:1', 'stop_position', 'osm_pair_propagation'),
        ('ch:1:sloid:2', 'gtfs_platform', 'gtfs_shared_route'),
        ('ch:1:sloid:3', 'gtfs_platform', 'source_duplicate_propagation'),
    ]:
        problems_db.add(StopsMatched(sloid=sloid, osm_node_id=node, stop_type='matched', match_type=match_type))
    problems_db.commit()

    def selected(*methods):
        condition = build_match_method_conditions(StopsMatched, list(methods))
        return sorted((row.sloid, row.osm_node_id) for row in StopsMatched.query.filter(condition))

    assert selected('reference') == [('ch:1:sloid:1', 'platform'), ('ch:1:sloid:1', 'stop_position')]
    assert selected('gtfs_shared_route') == [('ch:1:sloid:2', 'gtfs_platform'), ('ch:1:sloid:3', 'gtfs_platform')]
    assert selected('name') == []
