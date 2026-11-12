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


def test_an_unfocused_request_lists_stops_by_their_most_urgent_problem(client, ranked_stops):
    plain = get_problems(client)
    assert 'focus_found' not in plain
    assert (plain['page'], plain['total']) == (1, 5)
    # Page 1 holds the stops a and b with all their problems, b's P1 problem before its P3 problem.
    assert ids(plain) == [('ch:1:sloid:a', None), ('ch:1:sloid:b', None), ('ch:1:sloid:b', None)]
    assert [(row['problem'], row['priority']) for row in plain['problems']] == [
        ('distance', 1), ('unmatched', 1), ('attributes', 3)]


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
                duplicate_group_sloids=[f'ch:1:sloid:{index}x', f'ch:1:sloid:{index}y'],
            )
    session.commit()

    payload = get_problems(client, problem_type='duplicates', limit=1, focus_sloid='ch:1:sloid:2y')

    assert payload['focus_found'] is True
    assert payload['page'] == 3
    assert {member['sloid'] for member in payload['problems'][0]['members']} == {'ch:1:sloid:2x', 'ch:1:sloid:2y'}


def test_a_duplicate_group_lists_the_member_matched_by_propagation(client, problems_db):
    # The engine flags the member a rule matched, not the copy that took its match by propagation (E4.1).
    group = ['ch:1:sloid:30749:0:2351', 'ch:1:sloid:30749:0:3439']
    add_stop(problems_db, sloid=group[1], osm_node_id='332083940', problems=[('duplicates', 2)],
             uic_ref='8501118', atlas_designation='B', duplicate_group_sloids=group)
    add_stop(problems_db, sloid=group[0], osm_node_id='332083940', problems=[('distance', 1)],
             uic_ref='8501118', atlas_designation='B', duplicate_group_sloids=group)
    problems_db.commit()

    payload = get_problems(client, problem_type='duplicates', focus_sloid=group[0])

    assert payload['focus_found'] is True
    assert payload['total'] == 1
    [listed] = payload['problems']
    assert (listed['group_type'], listed['priority']) == ('atlas', 2)
    assert [(member['sloid'], member['priority']) for member in listed['members']] == [(group[1], 2), (group[0], None)]
    # An ATLAS group is P2: a P3 filter leaves it out, a P2 filter keeps it.
    assert get_problems(client, problem_type='duplicates', priority='3')['total'] == 0
    assert get_problems(client, problem_type='duplicates', priority='2')['total'] == 1
