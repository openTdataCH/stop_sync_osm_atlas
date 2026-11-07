"""/api/stop_popup: stop details for a map popup, by row id or by source id."""

import pytest

from backend.models import AtlasStop, OsmNode, OsmStop, OsmStopMember, StopsMatched


@pytest.fixture
def stops(problems_db, sqlite_tables):
    """Stop A has an unmatched row and a row matched to node 100; node 300 is unmatched."""
    session = sqlite_tables(OsmStop, OsmStopMember)
    session.add_all([
        AtlasStop(sloid='ch:1:sloid:1:0:1', atlas_designation='A'),
        OsmNode(osm_node_id='100', osm_name='Bahnhof'),
        OsmNode(osm_node_id='300', osm_name='Nord'),
    ])
    session.add_all([
        StopsMatched(sloid='ch:1:sloid:1:0:1', stop_type='atlas_unmatched', atlas_lat=47.0, atlas_lon=8.0),
        StopsMatched(sloid='ch:1:sloid:1:0:1', osm_node_id='100', stop_type='matched',
                     match_type='uic_reference_one_osm', atlas_lat=47.0, atlas_lon=8.0, osm_lat=47.0001, osm_lon=8.0001),
        StopsMatched(osm_node_id='300', stop_type='osm_unmatched', osm_lat=47.1, osm_lon=8.1),
    ])
    session.commit()
    return session


def popup(client, query, status=200):
    response = client.get(f'/api/stop_popup?{query}')
    assert response.status_code == status
    return response.get_json()


def test_a_sloid_opens_its_matched_row_before_an_unmatched_one(client, stops):
    stop = popup(client, 'sloid=ch:1:sloid:1:0:1&view_type=atlas')['stop']
    assert (stop['stop_type'], stop['osm_node_id']) == ('matched', '100')


def test_an_osm_node_id_opens_its_row(client, stops):
    stop = popup(client, 'osm_node_id=300&view_type=osm')['stop']
    assert (stop['stop_type'], stop['osm_node_id']) == ('osm_unmatched', '300')


def test_a_row_id_still_wins_over_source_ids(client, stops):
    row = StopsMatched.query.filter_by(stop_type='atlas_unmatched').one()
    stop = popup(client, f'stop_id={row.id}&sloid=ch:1:sloid:1:0:1')['stop']
    assert stop['stop_type'] == 'atlas_unmatched'


def test_unknown_or_missing_identifiers(client, stops):
    popup(client, 'sloid=ch:1:sloid:missing', 404)
    assert 'sloid' in popup(client, 'view_type=atlas', 400)['error']
