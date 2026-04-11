from unittest.mock import patch

from backend.services.global_stats import compute_global_stats_payload
from backend.queries.helpers import build_atlas_duplicate_membership_condition


def _compile_expression(expr):
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def test_compute_global_stats_payload_uses_sql_source_of_truth():
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

    with patch('backend.services.global_stats._compute_global_stats_sql', return_value=expected_payload) as mocked_sql:
        payload = compute_global_stats_payload({}, dummy_session)

    mocked_sql.assert_called_once_with({}, dummy_session)
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
