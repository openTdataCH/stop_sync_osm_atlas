from backend.models import Problem, StopsMatched
from backend.services.stats_export import compute_db_stats


def test_compute_db_stats_includes_contradicts_route_matching(sqlite_tables):
    session = sqlite_tables(StopsMatched, Problem)
    stop = StopsMatched(
        sloid='s1',
        stop_type='matched',
        match_type='gtfs_shared_route',
        atlas_lat=47.0,
        atlas_lon=8.0,
        osm_node_id='n1',
        osm_lat=47.0001,
        osm_lon=8.0001,
        distance_m=8.0,
        matching_notes='test',
    )
    session.add(stop)
    session.flush()
    session.add(Problem(stop_id=stop.id, problem_type='contradicts_route_matching', priority=2))
    session.commit()

    stats = compute_db_stats(session)

    assert stats['contradicts_route_matching'] == 1
    assert stats['stops_with_problems'] == 1
    assert stats['clean_entries'] == 0
    assert stats['by_priority'][2]['contradicts_route_matching'] == 1
