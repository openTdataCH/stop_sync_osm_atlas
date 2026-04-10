from unittest.mock import patch

from backend.services.global_stats import compute_global_stats_payload
from backend.queries.helpers import build_atlas_duplicate_membership_condition


def _compile_expression(expr):
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def test_compute_global_stats_payload_uses_materialized_rows_for_broad_filters():
    dummy_session = object()
    expected_payload = {
        'total_atlas_stops': 1,
        'matched_atlas_stops': 1,
        'total_osm_stops': 1,
        'matched_osm_stops': 1,
        'total_osm_nodes': 1,
        'matched_osm_nodes': 1,
        'matched_pairs_count': 1,
        'unmatched_entities_count': 0,
    }

    with patch('backend.services.global_stats._compute_global_stats_materialized', return_value=expected_payload) as mocked_materialized:
        with patch('backend.services.global_stats._compute_global_stats_sql', return_value={}) as mocked_sql:
            payload = compute_global_stats_payload({'transport_types': 'platform'}, dummy_session)

    mocked_materialized.assert_called_once_with({'transport_types': 'platform'}, dummy_session)
    mocked_sql.assert_not_called()
    assert payload == expected_payload


def test_compute_global_stats_payload_falls_back_to_sql_for_identifier_search():
    dummy_session = object()
    expected_payload = {
        'total_atlas_stops': 2,
        'matched_atlas_stops': 1,
        'total_osm_stops': 2,
        'matched_osm_stops': 1,
        'total_osm_nodes': 2,
        'matched_osm_nodes': 1,
        'matched_pairs_count': 1,
        'unmatched_entities_count': 2,
    }

    args = {
        'station_filter': '8503000',
        'filter_types': 'station',
    }

    with patch('backend.services.global_stats._compute_global_stats_materialized', return_value={}) as mocked_materialized:
        with patch('backend.services.global_stats._compute_global_stats_sql', return_value=expected_payload) as mocked_sql:
            payload = compute_global_stats_payload(args, dummy_session)

    mocked_materialized.assert_not_called()
    mocked_sql.assert_called_once_with(args, dummy_session)
    assert payload == expected_payload


def test_compute_global_stats_payload_falls_back_to_sql_for_top_n():
    dummy_session = object()
    expected_payload = {
        'total_atlas_stops': 3,
        'matched_atlas_stops': 3,
        'total_osm_stops': 3,
        'matched_osm_stops': 3,
        'total_osm_nodes': 3,
        'matched_osm_nodes': 3,
        'matched_pairs_count': 3,
        'unmatched_entities_count': 0,
    }

    args = {
        'top_n': '25',
        'stop_filter': 'matched',
    }

    with patch('backend.services.global_stats._compute_global_stats_materialized', return_value={}) as mocked_materialized:
        with patch('backend.services.global_stats._compute_global_stats_sql', return_value=expected_payload) as mocked_sql:
            payload = compute_global_stats_payload(args, dummy_session)

    mocked_materialized.assert_not_called()
    mocked_sql.assert_called_once_with(args, dummy_session)
    assert payload == expected_payload


def test_compute_global_stats_payload_falls_back_to_sql_when_materialized_table_missing():
    dummy_session = object()
    expected_payload = {
        'total_atlas_stops': 4,
        'matched_atlas_stops': 3,
        'total_osm_stops': 4,
        'matched_osm_stops': 3,
        'total_osm_nodes': 4,
        'matched_osm_nodes': 3,
        'matched_pairs_count': 3,
        'unmatched_entities_count': 2,
    }

    with patch('backend.services.global_stats._compute_global_stats_materialized', side_effect=RuntimeError('relation does not exist')):
        with patch('backend.services.global_stats.is_missing_table_error', return_value=True):
            with patch('backend.services.global_stats._compute_global_stats_sql', return_value=expected_payload) as mocked_sql:
                payload = compute_global_stats_payload({'transport_types': 'station'}, dummy_session)

    mocked_sql.assert_called_once_with({'transport_types': 'station'}, dummy_session)
    assert payload == expected_payload


def test_duplicate_membership_condition_uses_structural_membership_not_jsonb_null_check():
    sql = _compile_expression(build_atlas_duplicate_membership_condition())

    # Non-representative duplicate members
    assert 'representative_sloid IS NOT NULL' in sql
    # Representative rows with at least one sibling member
    assert 'EXISTS' in sql
    assert 'representative_sloid = atlas_stops.sloid' in sql
    # Guard against regressing to JSONB null semantics
    assert 'duplicate_group_sloids' not in sql
