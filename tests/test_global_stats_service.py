from unittest.mock import patch

from backend.services.global_stats import compute_global_stats_payload
from backend.queries.helpers import build_atlas_duplicate_membership_condition


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


def test_duplicate_membership_is_structural_not_the_stored_group_list(problems_db):
    from backend.models import AtlasStop

    problems_db.add_all([
        AtlasStop(sloid='representative'),
        AtlasStop(sloid='member', representative_sloid='representative'),
        AtlasStop(sloid='alone'),
        # A stored group list without members pointing at it does not make a duplicate.
        AtlasStop(sloid='listed_alone', duplicate_group_sloids=['listed_alone', 'gone']),
    ])
    problems_db.commit()

    duplicates = AtlasStop.query.filter(build_atlas_duplicate_membership_condition()).all()
    assert sorted(stop.sloid for stop in duplicates) == ['member', 'representative']
