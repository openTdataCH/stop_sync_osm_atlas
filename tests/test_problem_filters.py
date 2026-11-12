"""Problems by area and the map's Problems filter (backend/services/problem_filters.py)."""

import pytest

from backend.models import AtlasStop, OsmNode, Problem, StopsMatched
from backend.query_builder import apply_common_filters
from backend.queries.helpers import parse_filter_params
from backend.services.problem_filters import parse_area


def add_stop(session, sloid=None, osm_node_id=None, atlas_at=None, osm_at=None, problems=()):
    if sloid:
        session.add(AtlasStop(sloid=sloid))
    if osm_node_id:
        session.add(OsmNode(osm_node_id=osm_node_id))
    stop = StopsMatched(
        sloid=sloid, osm_node_id=osm_node_id,
        stop_type='matched' if sloid and osm_node_id else ('atlas_unmatched' if sloid else 'osm_unmatched'),
        atlas_lat=atlas_at and atlas_at[0], atlas_lon=atlas_at and atlas_at[1],
        osm_lat=osm_at and osm_at[0], osm_lon=osm_at and osm_at[1],
    )
    session.add(stop)
    session.flush()
    for problem_type, priority in problems:
        session.add(Problem(stop_id=stop.id, problem_type=problem_type, priority=priority))


# The area used below: around Bern, west 7.3, south 46.9, east 7.5, north 47.0.
BERN = '7.3,46.9,7.5,47.0'


@pytest.fixture
def stops(problems_db):
    session = problems_db
    add_stop(session, sloid='bern', atlas_at=(46.95, 7.44), problems=[('distance', 1)])
    add_stop(session, osm_node_id='1', osm_at=(46.94, 7.40), problems=[('unmatched', 3)])
    # A matched pair with only its OSM side in the area is in the area.
    add_stop(session, sloid='edge', osm_node_id='2', atlas_at=(47.10, 7.44), osm_at=(46.99, 7.44),
             problems=[('attributes', 2)])
    add_stop(session, sloid='zurich', atlas_at=(47.37, 8.54), problems=[('distance', 1), ('attributes', 3)])
    add_stop(session, sloid='clean', atlas_at=(46.95, 7.45))
    session.commit()
    return session


def problem_stops(client, **params):
    response = client.get('/api/problems', query_string={'limit': 50, **params})
    assert response.status_code == 200, response.get_json()
    return sorted({p['sloid'] or p['osm_node_id'] for p in response.get_json()['problems']})


@pytest.mark.parametrize('text, area', [
    (None, None),
    ('', None),
    ('7.3,46.9,7.5,47.0', (7.3, 46.9, 7.5, 47.0)),
    (' 7.3, 46.9 ,7.5,47 ', (7.3, 46.9, 7.5, 47.0)),
])
def test_area_is_west_south_east_north(text, area):
    assert parse_area(text) == area


@pytest.mark.parametrize('text', ['7.3,46.9,7.5', '7.5,46.9,7.3,47.0', '7.3,47.0,7.5,46.9', 'a,b,c,d', '7.3,46.9,7.5,95'])
def test_malformed_areas_are_refused(text):
    with pytest.raises(ValueError):
        parse_area(text)


def test_problems_page_keeps_the_problems_inside_the_area(client, stops):
    assert problem_stops(client) == ['1', 'bern', 'edge', 'zurich']
    assert problem_stops(client, bbox=BERN) == ['1', 'bern', 'edge']
    assert problem_stops(client, bbox=BERN, priority='1') == ['bern']
    assert problem_stops(client, bbox=BERN, problem_type='attributes') == ['edge']


def test_problem_counts_follow_the_area(client, stops):
    stats = client.get('/api/problems/stats', query_string={'bbox': BERN}).get_json()

    assert (stats['distance']['all'], stats['unmatched']['all'], stats['attributes']['all']) == (1, 1, 1)
    assert stats['all']['all'] == 3



def test_the_list_counts_stops_and_problems_apart(client, stops):
    # Zurich has two problems: the list has four entries, one per stop, and five problems, as the type counts say.
    listed = client.get('/api/problems', query_string={'limit': 50}).get_json()
    assert (listed['total'], listed['problem_count']) == (4, 5)
    assert client.get('/api/problems/stats').get_json()['all']['all'] == 5
    p1 = client.get('/api/problems', query_string={'priority': '1'}).get_json()
    assert (p1['total'], p1['problem_count']) == (2, 2)

def test_a_malformed_area_is_an_error_not_every_problem(client, stops):
    for path in ('/api/problems', '/api/problems/stats'):
        response = client.get(path, query_string={'bbox': '7.5,46.9,7.3,47.0'})
        assert response.status_code == 400
        assert 'bbox' in response.get_json()['error']


def map_entries(args):
    query = apply_common_filters(StopsMatched.query, parse_filter_params(args))
    return sorted(row.sloid or row.osm_node_id for row in query.all())


def test_map_problems_filter_keeps_entries_with_such_a_problem(stops):
    assert map_entries({}) == ['1', 'bern', 'clean', 'edge', 'zurich']
    assert map_entries({'problem_type': 'all'}) == ['1', 'bern', 'edge', 'zurich']
    assert map_entries({'problem_type': 'distance,unmatched'}) == ['1', 'bern', 'zurich']
    assert map_entries({'priority': '3'}) == ['1', 'zurich']
    # Type and priority describe the same problem: zurich's distance problem is P1, not P3.
    assert map_entries({'problem_type': 'distance', 'priority': '3'}) == []
    assert map_entries({'problem_type': 'attributes', 'priority': '2,3'}) == ['edge', 'zurich']
