from backend.models import StopsMatched
from backend.app import app as backend_app
from backend.query_builder import QueryBuilder
from backend.queries.helpers import build_match_method_conditions, build_stop_scope_condition, parse_filter_params, resolve_stop_type_match_filters


def _compile_expression(expr):
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def test_matched_methods_apply_without_master_stop_type():
    resolved = resolve_stop_type_match_filters(None, 'exact,name')

    assert resolved['include_matched'] is True
    assert resolved['matched_methods'] == ['exact', 'name']
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


def test_scope_condition_for_exact_only_targets_matched_exact_rows():
    resolved = resolve_stop_type_match_filters(None, 'exact')

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert "match_type = 'exact'" in sql
    assert "atlas_unmatched" not in sql


def test_scope_condition_for_master_matched_without_methods_is_not_narrowed():
    resolved = resolve_stop_type_match_filters('matched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert "match_type = 'exact'" not in sql
    assert "distance_matching_" not in sql
    assert "route_gtfs" not in sql


def test_route_match_condition_includes_unified_route_variants():
    sql = _compile_expression(build_match_method_conditions(StopsMatched, ['route_gtfs']))

    assert "route_gtfs%" in sql
    assert "route_unified_gtfs%" in sql


def test_parse_filter_params_uses_osm_group_types_without_gate():
    filters = parse_filter_params({'osm_group_types': 'osm_group_uic,osm_group_name'})

    assert filters['osm_group_types'] == ['osm_pair_uic', 'osm_pair_name']


def test_parse_filter_params_normalizes_osm_group_all_selection():
    filters = parse_filter_params({'osm_group_types': 'all'})

    assert 'osm_group_types' in filters
    assert filters['osm_group_types'] == []


def test_parse_filter_params_normalizes_perfect_count_group_aliases():
    filters = parse_filter_params(
        {'osm_group_types': 'osm_group_uic_equal,osm_group_name_equal,osm_group_tram_equal'}
    )

    assert filters['osm_group_types'] == [
        'osm_pair_uic_equal_15m',
        'osm_pair_name_equal_15m',
        'osm_pair_tram_equal_15m',
    ]


def test_query_builder_osm_groups_apply_without_legacy_toggle():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(StopsMatched.query, {'osm_group_types': ['osm_pair_uic']}).statement
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
                {'transport_types': ['platform'], 'osm_group_types': ['osm_pair_uic']}
            ).statement
        )

    assert 'osm_public_transport' in sql
    assert 'stops_matched.osm_node_id IN' in sql
    assert ' AND ' in sql


def test_query_builder_trio_only_filter_excludes_pair_type_predicate():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(StopsMatched.query, {'osm_group_types': ['osm_trio']}).statement
        )

    assert 'stops_matched.osm_node_id IN' in sql
    assert "osm_stops.stop_kind = 'pair'" not in sql
    assert "osm_stops.stop_kind = 'trio'" in sql


def test_query_builder_supports_perfect_count_pair_group_types():
    query_builder = QueryBuilder(None)

    with backend_app.app_context():
        sql = _compile_expression(
            query_builder.apply_common_filters(
                StopsMatched.query,
                {'osm_group_types': ['osm_pair_uic_equal_15m']}
            ).statement
        )

    assert 'stops_matched.osm_node_id IN' in sql
    assert 'osm_stops.group_kind IN' in sql
    assert 'osm_pair_uic_equal_15m' in sql


def test_scope_condition_matched_includes_trio_middle_effective_matches():
    resolved = resolve_stop_type_match_filters('matched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'matched'" in sql
    assert 'trio_middle' in sql
    assert 'trio_side' in sql
    assert "stop_type = 'osm_unmatched'" in sql


def test_scope_condition_osm_unmatched_excludes_trio_middle_effective_matches():
    resolved = resolve_stop_type_match_filters('osm_unmatched', None)

    sql = _compile_expression(build_stop_scope_condition(StopsMatched, resolved))

    assert "stop_type = 'osm_unmatched'" in sql
    assert 'NOT' in sql
    assert 'trio_middle' in sql
    assert 'trio_side' in sql