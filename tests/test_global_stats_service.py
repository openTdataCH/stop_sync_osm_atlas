from backend.models import AtlasStop, OsmNode, OsmStop, OsmStopMember, StopsMatched
from backend.services.global_stats import compute_global_stats_payload
from backend.queries.helpers import build_atlas_duplicate_membership_condition


def test_top_n_counts_only_the_matches_with_the_largest_distance(sqlite_tables):
    session = sqlite_tables(AtlasStop, OsmNode, StopsMatched, OsmStop, OsmStopMember)
    for index, distance in enumerate((5.0, 50.0, 20.0, None)):
        session.add(StopsMatched(sloid=f's{index}', osm_node_id=f'n{index}', stop_type='matched', distance_m=distance))
    session.add(StopsMatched(sloid='alone', stop_type='atlas_unmatched'))
    session.commit()

    everything = compute_global_stats_payload({})
    assert (everything['total_atlas_stops'], everything['matched_pairs_count']) == (5, 4)

    top_two = compute_global_stats_payload({'top_n': '2'})
    assert (top_two['total_atlas_stops'], top_two['matched_pairs_count'], top_two['total_osm_nodes']) == (2, 2, 2)


def test_duplicate_membership_is_structural_not_the_stored_group_list(problems_db):
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
