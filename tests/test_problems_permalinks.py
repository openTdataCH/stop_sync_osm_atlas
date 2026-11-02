"""Problem permalinks: /api/problems serves the page holding a linked stop."""

import pytest

from backend.models import AtlasStop, OsmNode, Problem, StopsMatched


def add_stop(session, sloid=None, osm_node_id=None, problems=(), **atlas):
    if sloid and session.get(AtlasStop, sloid) is None:
        session.add(AtlasStop(sloid=sloid, **atlas))
    if osm_node_id and session.get(OsmNode, osm_node_id) is None:
        session.add(OsmNode(osm_node_id=osm_node_id))
    stop = StopsMatched(
        sloid=sloid,
        osm_node_id=osm_node_id,
        stop_type='matched' if sloid and osm_node_id else ('atlas_unmatched' if sloid else 'osm_unmatched'),
        atlas_lat=47.0 if sloid else None,
        atlas_lon=8.0 if sloid else None,
        osm_lat=47.0 if osm_node_id else None,
        osm_lon=8.0 if osm_node_id else None,
    )
    session.add(stop)
    session.flush()
    for problem_type, priority in problems:
        session.add(Problem(stop_id=stop.id, problem_type=problem_type, priority=priority))
    return stop


@pytest.fixture
def ranked_stops(problems_db):
    """Five stops in Problems-page order: P1 a, P1 b, P2 c (a pair), P3 d, P3 way e."""
    session = problems_db
    add_stop(session, sloid='ch:1:sloid:a', problems=[('distance', 1)], atlas_business_org_abbr='OPA')
    add_stop(session, sloid='ch:1:sloid:b', problems=[('unmatched', 1), ('attributes', 3)], atlas_business_org_abbr='OPB')
    add_stop(session, sloid='ch:1:sloid:c', osm_node_id='300', problems=[('attributes', 2)], atlas_business_org_abbr='OPA')
    add_stop(session, sloid='ch:1:sloid:c', osm_node_id='301', problems=[('distance', 3)])
    add_stop(session, osm_node_id='way_500', problems=[('unmatched', 3)])
    session.commit()
    return session


def get_problems(client, **params):
    response = client.get('/api/problems', query_string={'limit': 2, **params})
    assert response.status_code == 200
    return response.get_json()


def ids(payload):
    return [(row['sloid'], row['osm_node_id']) for row in payload['problems']]


def test_focus_serves_the_page_holding_the_stop(client, ranked_stops):
    payload = get_problems(client, focus_osm_node_id='way_500')

    assert payload['page'] == 3
    assert payload['focus_found'] is True
    assert ids(payload) == [(None, 'way_500')]


def test_both_identifiers_name_one_pair_and_one_names_its_first_entry(client, ranked_stops):
    pair = get_problems(client, focus_sloid='ch:1:sloid:c', focus_osm_node_id='301')
    assert pair['page'] == 2
    assert ('ch:1:sloid:c', '301') in ids(pair)

    first_of_stop = get_problems(client, focus_sloid='ch:1:sloid:c')
    assert first_of_stop['page'] == 2
    assert ids(first_of_stop)[0] == ('ch:1:sloid:c', '300')


def test_focus_respects_the_filters(client, ranked_stops):
    filtered = get_problems(client, problem_type='attributes', focus_sloid='ch:1:sloid:b')
    assert filtered['focus_found'] is True
    assert filtered['page'] == 1  # attributes only: b (P3) comes after c (P2), both on page 1

    excluded = get_problems(client, atlas_operator='OPA', focus_sloid='ch:1:sloid:b', page=2)
    assert excluded['focus_found'] is False
    assert excluded['page'] == 2


def test_descending_priority_and_unfocused_requests(client, ranked_stops):
    # Descending: [c/301 (P3), way (P3)], [c/300 (P2), a (P1)], [b (P1)].
    descending = get_problems(client, sort_order='desc', focus_sloid='ch:1:sloid:a')
    assert descending['page'] == 2
    assert ('ch:1:sloid:a', None) in ids(descending)

    plain = get_problems(client)
    assert 'focus_found' not in plain
    assert plain['page'] == 1

    by_distance = get_problems(client, problem_type='distance', sort_by='distance', focus_sloid='ch:1:sloid:a')
    assert by_distance['focus_found'] is False


def test_focus_finds_a_duplicate_group_by_any_member(client, problems_db):
    session = problems_db
    for index in range(3):
        for member in ('x', 'y'):
            add_stop(
                session,
                sloid=f'ch:1:sloid:{index}{member}',
                problems=[('duplicates', 2)],
                uic_ref=f'850000{index}',
                atlas_designation='A',
            )
    session.commit()

    payload = get_problems(client, problem_type='duplicates', limit=1, focus_sloid='ch:1:sloid:2y')

    assert payload['focus_found'] is True
    assert payload['page'] == 3
    assert {member['sloid'] for member in payload['problems'][0]['members']} == {'ch:1:sloid:2x', 'ch:1:sloid:2y'}
