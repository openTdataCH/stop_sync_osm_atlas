from backend.models import StopsMatched
from backend.app import app as backend_app
from backend.query_builder import QueryBuilder
from backend.queries.helpers import build_match_method_conditions, build_stop_scope_condition, parse_filter_params, resolve_stop_type_match_filters


def _compile_expression(expr):
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


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


def test_scope_condition_for_reference_rule_targets_each_of_its_match_types():
    resolved = resolve_stop_type_match_filters(None, 'reference')

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert "match_type IN ('uic_reference_local_ref', 'uic_reference_one_osm', 'uic_reference_one_source')" in sql
    assert "atlas_unmatched" not in sql


def test_two_sided_stop_rule_filter_also_includes_effectively_matched_middles():
    resolved = resolve_stop_type_match_filters(None, 'two_sided_stop')

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "match_type IN ('uic_two_sided_stop')" in sql
    assert "stop_type = 'effectively_matched'" in sql


def test_scope_condition_for_master_matched_without_methods_is_not_narrowed():
    resolved = resolve_stop_type_match_filters('matched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert "match_type" not in sql


def test_match_type_filter_selects_only_that_branch():
    sql = _compile_expression(build_match_method_conditions(StopsMatched, ['gtfs_shared_route']))

    assert "match_type IN ('gtfs_shared_route')" in sql


def test_rule_filter_covers_every_pass_of_the_rule():
    sql = _compile_expression(build_match_method_conditions(StopsMatched, ['distance_only_candidate']))

    assert "match_type IN ('distance_only_candidate', 'distance_only_candidate_second_pass')" in sql


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


def test_query_builder_osm_groups_apply_without_legacy_toggle():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(StopsMatched.query, {'osm_group_types': ['ptv2_pair_uic_ref']}).statement
        )

    assert 'stops_matched.osm_node_id IN' in sql
    assert 'osm_stops.group_kind IN' in sql
    assert "stops_matched.stop_type != 'matched'" not in sql


def test_query_builder_combines_transport_and_osm_group_with_and():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(
                StopsMatched.query,
                {'transport_types': ['platform'], 'osm_group_types': ['ptv2_pair_uic_ref']}
            ).statement
        )

    assert 'osm_public_transport' in sql
    assert 'stops_matched.osm_node_id IN' in sql
    assert ' AND ' in sql


def test_query_builder_two_sided_only_filter_excludes_pair_type_predicate():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(StopsMatched.query, {'osm_group_types': ['ptv2_two_sided_stop']}).statement
        )

    assert 'stops_matched.osm_node_id IN' in sql
    assert "osm_stops.stop_kind = 'pair'" not in sql
    assert "osm_stops.stop_kind = 'two_sided_stop'" in sql


def test_query_builder_supports_equal_count_pair_group_types():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(
                StopsMatched.query,
                {'osm_group_types': ['ptv2_pair_uic_ref_equal_count']}
            ).statement
        )

    assert 'stops_matched.osm_node_id IN' in sql
    assert 'osm_stops.group_kind IN' in sql
    assert 'ptv2_pair_uic_ref_equal_count' in sql


def test_scope_condition_matched_includes_two_sided_middle_effective_matches():
    resolved = resolve_stop_type_match_filters('matched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert "stop_type = 'effectively_matched'" in sql


def test_scope_condition_osm_unmatched_excludes_two_sided_middle_effective_matches():
    resolved = resolve_stop_type_match_filters('osm_unmatched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'osm_unmatched'" in sql
    assert "stop_type = 'effectively_matched'" not in sql

def test_scope_condition_osm_disused_is_its_own_stop_type():
    resolved = resolve_stop_type_match_filters('osm_disused', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert resolved['include_osm_disused'] is True
    assert resolved['include_osm_unmatched'] is False
    assert sql == "stops_matched.stop_type = 'osm_disused'"


def test_global_stats_leave_disused_osm_out_unless_selected():
    from backend.services.global_stats import _build_scoped_global_stats_query

    with backend_app.app_context():
        unfiltered = str(_build_scoped_global_stats_query({}).statement.compile(compile_kwargs={"literal_binds": True}))
        selected = str(_build_scoped_global_stats_query({'stop_filter': 'osm_disused'}).statement.compile(
            compile_kwargs={"literal_binds": True}))

    assert "stops_matched.stop_type != 'osm_disused'" in unfiltered
    assert "!= 'osm_disused'" not in selected


def test_identifier_filters_keep_whole_identifiers_only(problems_db):
    from backend.models import AtlasStop, OsmNode

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
        query = QueryBuilder(None).apply_common_filters(
            StopsMatched.query, {'filter_values': [value], 'filter_types': [filter_type]})
        return sorted(row.osm_node_id for row in query.all())

    assert kept('ch:1:sloid:10035:0:1', 'atlas') == ['100']
    assert kept('100', 'osm') == ['100']
    assert kept('6151326225', 'osm') == ['6151326225']
    assert kept('8510035', 'station') == ['100', '1001']
    assert kept('8530279', 'station') == ['6151326225']
    assert kept('8500819', 'station') == ['6151326225']
    assert kept('850081', 'station') == []
