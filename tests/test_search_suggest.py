"""Search box suggestions: /api/search/suggest and backend/services/stop_suggest.py."""

import pytest

from backend.models import AtlasStop, DatasetPublication, OsmNode, StopsMatched
from backend.services import stop_suggest


@pytest.fixture(autouse=True)
def fresh_index():
    """The index is cached per process; start every test without it."""
    stop_suggest._cache.update(run_id=None, entries=None)
    yield
    stop_suggest._cache.update(run_id=None, entries=None)


def add_entry(session, stop_type, sloid=None, osm_node_id=None, atlas=None, osm=None):
    if sloid and session.get(AtlasStop, sloid) is None:
        session.add(AtlasStop(sloid=sloid, **(atlas or {})))
    if osm_node_id and session.get(OsmNode, osm_node_id) is None:
        session.add(OsmNode(osm_node_id=osm_node_id, **(osm or {})))
    session.add(StopsMatched(sloid=sloid, osm_node_id=osm_node_id, stop_type=stop_type))
    session.flush()


@pytest.fixture
def stops(problems_db):
    session = problems_db
    zurich = {'uic_ref': '8503000', 'atlas_designation_official': 'Zürich HB'}
    add_entry(session, 'matched', 'ch:1:sloid:3000:1', '1', zurich, {'osm_name': 'Zürich Hauptbahnhof'})
    add_entry(session, 'atlas_unmatched', 'ch:1:sloid:3000:2', atlas=zurich)
    add_entry(session, 'atlas_unmatched', 'ch:1:sloid:3088:1',
              atlas={'uic_ref': '8503088', 'atlas_designation_official': 'Zürich HB SZU'})
    add_entry(session, 'atlas_unmatched', 'ch:1:sloid:91367:1',
              atlas={'uic_ref': '8591367', 'atlas_designation_official': 'Zürich, Sihlpost/HB'})
    # An OSM element without a match or a station number is an entry of its own.
    add_entry(session, 'osm_unmatched', osm_node_id='2', osm={'osm_name': 'Zürich HB'})
    # One that carries a station's number is another name of that station.
    add_entry(session, 'osm_unmatched', osm_node_id='3', osm={'osm_name': 'Gleis 7', 'osm_uic_ref': '8503000'})
    add_entry(session, 'osm_disused', osm_node_id='way_4', osm={'osm_name': 'Alte Haltestelle'})
    # The middle of a two-sided stop belongs to a matched stop.
    add_entry(session, 'effectively_matched', osm_node_id='5', osm={'osm_name': 'Mittelinsel'})
    session.commit()
    return session


def suggest(client, query, status=200, **params):
    response = client.get('/api/search/suggest', query_string={'q': query, **params})
    assert response.status_code == status
    return response.get_json()


def refs(payload):
    return [result['ref'] for result in payload['results']]


@pytest.mark.parametrize('text, expected', [
    ('Zürich, HB', 'zurich hb'),
    ('Genève-Aéroport', 'geneve aeroport'),
    ('  St. Gallen  ', 'st gallen'),
    ('Saint-Imier', 'saint imier'),
    (None, ''),
])
def test_names_are_compared_without_case_accents_or_punctuation(text, expected):
    assert stop_suggest.normalize(text) == expected


def test_same_name_first_then_starts_with_then_word_starts_with(client, stops):
    payload = suggest(client, 'zurich hb')

    # The source station before the OSM element of the same name.
    assert refs(payload) == ['8503000', 'node/2', '8503088', '8591367']
    assert payload['results'][0] == {
        'kind': 'station', 'value': '8503000', 'ref': '8503000', 'name': 'Zürich HB',
        'side': 'source', 'matched_name': None, 'stops': 2,
    }
    assert payload['results'][1] == {
        'kind': 'osm', 'value': '2', 'ref': 'node/2', 'name': 'Zürich HB',
        'side': 'osm', 'matched_name': None, 'stop_type': 'osm_unmatched',
    }


def test_words_match_in_any_order(client, stops):
    # Each word starts a word of every name: same rank, so stations come first.
    assert refs(suggest(client, 'hb zur')) == ['8503000', '8503088', '8591367', 'node/2']


def test_stations_are_found_under_their_osm_names(client, stops):
    matched = suggest(client, 'hauptbahnhof')['results']
    with_number = suggest(client, 'gleis')['results']

    assert [(r['ref'], r['matched_name']) for r in matched] == [('8503000', 'Zürich Hauptbahnhof')]
    assert [(r['ref'], r['matched_name']) for r in with_number] == [('8503000', 'Gleis 7')]


def test_numbers_find_stations_in_number_order(client, stops):
    assert refs(suggest(client, '85030')) == ['8503000', '8503088']
    assert refs(suggest(client, '8503088')) == ['8503088']


def test_osm_elements_keep_their_identifier_and_state(client, stops):
    [way] = suggest(client, 'alte halt')['results']

    assert (way['kind'], way['value'], way['ref'], way['stop_type']) == ('osm', 'way_4', 'way/4', 'osm_disused')
    assert suggest(client, 'mittelinsel')['results'] == []


def test_short_unknown_and_limited_queries(client, stops):
    assert suggest(client, 'z')['results'] == []
    assert suggest(client, 'xyz')['results'] == []
    assert refs(suggest(client, 'zurich', limit=2)) == ['8503000', '8503088']
    suggest(client, 'zurich', status=400, limit='many')
    suggest(client, 'z' * 101, status=400)


def test_index_is_rebuilt_when_another_snapshot_is_published(client, stops):
    stops.add(DatasetPublication(run_id='run-1', manifest={}))
    stops.commit()
    assert refs(suggest(client, 'olten')) == []

    add_entry(stops, 'atlas_unmatched', 'ch:1:sloid:218:1',
              atlas={'uic_ref': '8500218', 'atlas_designation_official': 'Olten'})
    stops.commit()
    assert refs(suggest(client, 'olten')) == []  # same snapshot: the cached index

    stops.query(DatasetPublication).update({'run_id': 'run-2'})
    stops.commit()
    assert refs(suggest(client, 'olten')) == ['8500218']
