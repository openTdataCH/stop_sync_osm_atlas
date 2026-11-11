"""The map's route filter narrowed to route variants (atlas_variant / osm_variant)."""
import json

import pytest

from backend.models import Itinerary, ItineraryMatch, LineFamily, LineFamilyMatch, StopCall
from backend.queries.helpers import parse_filter_params, parse_route_variants
from backend import query_builder
from backend.services.transport_routes import get_stops_for_route, list_route_variants

HB = '91-10-A-j26-1:0:Zürich HB'
SELNAU = '91-10-A-j26-1:0:Zürich Selnau'
NOTHING = {'gtfs': None, 'osm': None}


@pytest.fixture
def variant_db(sqlite_tables):
    """The S10: two ATLAS variants per direction and the OSM relations, plus another line."""
    session = sqlite_tables(LineFamily, LineFamilyMatch, Itinerary, ItineraryMatch, StopCall)
    session.add_all([
        LineFamily(id=1, source='gtfs', source_family_id='91-10-A-j26-1', gtfs_route_id='91-10-A-j26-1',
                   normalized_route_id='91-10-A-jXX-1', ref='S10'),
        LineFamily(id=2, source='osm', source_family_id='osm-s10', ref='S10'),
        LineFamily(id=3, source='gtfs', source_family_id='91-9-j26-1', gtfs_route_id='91-9-j26-1'),
        LineFamilyMatch(id=1, gtfs_line_family_id=1, osm_line_family_id=2),
    ])
    variants = [
        # id, source, family, key, direction, name, stops (SLOIDs or OSM nodes)
        (11, 'gtfs', 1, HB, '0', 'Uetliberg -> Zürich HB', ['uetliberg', 'selnau-1', 'hb']),
        (12, 'gtfs', 1, SELNAU, '0', 'Uetliberg -> Zürich Selnau', ['uetliberg', 'selnau-2']),
        (13, 'gtfs', 1, '91-10-A-j26-1:1:Uetliberg', '1', 'Zürich Selnau -> Uetliberg', ['selnau-2', 'uetliberg']),
        (21, 'osm', 2, '1561015', '0', 'Uetliberg -> Selnau', ['n-uetliberg', 'n-selnau-1']),
        (22, 'osm', 2, '1561012', '1', 'Selnau -> Uetliberg', ['n-selnau-2', 'n-uetliberg']),
        (31, 'gtfs', 3, '91-9-j26-1:0:Wabern', '0', 'Tram 9', ['wabern']),
    ]
    for itinerary_id, source, family, key, direction, name, stops in variants:
        session.add(Itinerary(id=itinerary_id, source=source, line_family_id=family, source_itinerary_id=key,
                              direction_id=direction, display_name=name, canonical_stop_count=len(stops)))
        for sequence, stop in enumerate(stops, 1):
            session.add(StopCall(
                itinerary_id=itinerary_id, stop_sequence=sequence,
                source_sloid=stop if source == 'gtfs' else None,
                source_node_id=stop if source == 'osm' else None,
                stop_lat=47.0 + itinerary_id / 1000 + sequence / 100, stop_lon=8.0 + sequence / 100,
            ))
    session.add_all([
        ItineraryMatch(id=1, gtfs_itinerary_id=11, osm_itinerary_id=21),
        ItineraryMatch(id=2, gtfs_itinerary_id=13, osm_itinerary_id=22),
    ])
    session.commit()
    return session


def _stops(result):
    return sorted(result['atlas_sloids']), sorted(result['osm_nodes'])


def test_route_filter_without_variants_keeps_the_whole_line_or_one_direction(variant_db):
    assert _stops(get_stops_for_route('91-10-A-j26-1')) == (
        ['hb', 'selnau-1', 'selnau-2', 'uetliberg'], ['n-selnau-1', 'n-selnau-2', 'n-uetliberg'])
    assert _stops(get_stops_for_route('91-10-A-j26-1', '0')) == (
        ['hb', 'selnau-1', 'selnau-2', 'uetliberg'], ['n-selnau-1', 'n-uetliberg'])


def test_variants_narrow_the_route_to_exactly_their_stops_whatever_the_direction(variant_db):
    variants = {'gtfs': SELNAU, 'osm': '1561015'}
    expected = (['selnau-2', 'uetliberg'], ['n-selnau-1', 'n-uetliberg'])
    assert _stops(get_stops_for_route('91-10-A-j26-1', None, variants)) == expected
    assert _stops(get_stops_for_route('91-10-A-j26-1', '1', variants)) == expected
    assert _stops(get_stops_for_route('91-10-A-j26-1', None, {'gtfs': None, 'osm': '1561012'})) == (
        [], ['n-selnau-2', 'n-uetliberg'])


def test_an_atlas_variant_key_survives_a_new_timetable(variant_db):
    variants = {'gtfs': '91-10-A-j25-1:0:Zürich Selnau', 'osm': None}
    assert _stops(get_stops_for_route('91-10-A-j25-1', None, variants)) == (['selnau-2', 'uetliberg'], [])
    # Only the year is ignored: the headsign must still be the same.
    assert _stops(get_stops_for_route('91-10-A-j26-1', None, {'gtfs': '91-10-A-j25-1:0:Zürich', 'osm': None})) == ([], [])


@pytest.mark.parametrize('variants', [NOTHING, {'gtfs': 'missing', 'osm': None}, {'gtfs': None, 'osm': '999'}])
def test_variants_that_name_nothing_never_widen_to_the_whole_line(variant_db, variants):
    assert _stops(get_stops_for_route('91-10-A-j26-1', None, variants)) == ([], [])


def test_variants_of_two_lines_are_both_shown(variant_db):
    # The routes page compares any ATLAS variant with any OSM variant.
    variants = {'gtfs': '91-9-j26-1:0:Wabern', 'osm': '1561015'}
    assert _stops(get_stops_for_route('91-10-A-j26-1', None, variants)) == (['wabern'], ['n-selnau-1', 'n-uetliberg'])


def test_route_variants_list_engine_pairs_first_in_each_direction(variant_db):
    result = list_route_variants('91-10-A-j26-1')
    assert result['route_id'] == '91-10-A-j26-1'
    assert result['selected'] is None and result['bounds'] is None
    assert [(entry['direction_id'], entry['gtfs'] and entry['gtfs']['key'], entry['osm'] and entry['osm']['key'])
            for entry in result['variants']] == [
        ('0', HB, '1561015'), ('0', SELNAU, None), ('1', '91-10-A-j26-1:1:Uetliberg', '1561012'),
    ]
    assert result['variants'][0]['gtfs'] == {
        'key': HB, 'name': 'Uetliberg -> Zürich HB', 'direction_id': '0', 'stop_count': 3,
    }


def test_a_variant_link_names_its_line_and_its_variants_with_current_keys(variant_db):
    result = list_route_variants(variants={'gtfs': '91-10-A-j25-1:0:Zürich Selnau', 'osm': '1561015'})
    assert result['route_id'] == '91-10-A-j26-1'
    assert result['selected']['gtfs']['key'] == SELNAU
    assert result['selected']['osm']['name'] == 'Uetliberg -> Selnau'
    # Both variants' stops: the ATLAS one starts furthest south, the OSM one ends furthest north.
    assert result['bounds'] == [[pytest.approx(47.022), 8.01], [pytest.approx(47.041), 8.02]]
    # An OSM variant names the ATLAS line its line is linked to.
    assert list_route_variants(variants={'gtfs': None, 'osm': '1561012'})['route_id'] == '91-10-A-j26-1'
    with pytest.raises(LookupError):
        list_route_variants(variants={'gtfs': 'missing', 'osm': None})


def test_route_variants_api(app, variant_db):
    client = app.test_client()
    response = client.get('/api/routes/variants', query_string={'atlas_variant': SELNAU, 'osm_variant': '1561015'})
    assert response.status_code == 200
    assert response.json['selected']['gtfs']['key'] == SELNAU
    assert client.get('/api/routes/variants?route_id=91-10-A-j26-1').json['variants'][1]['gtfs']['key'] == SELNAU
    assert client.get('/api/routes/variants?osm_variant=999').status_code == 404
    assert client.get('/api/routes/variants').status_code == 400
    assert client.get('/api/routes/variants', query_string={'route_id': 'x' * 256}).status_code == 400


def test_route_variants_parameter_is_positional_and_malformed_input_names_nothing():
    assert parse_route_variants(None, 2) == [None, None]
    assert parse_route_variants(json.dumps([None, {'gtfs': 'Bern, Bahnhof', 'osm': 7}]), 2) == [
        None, {'gtfs': 'Bern, Bahnhof', 'osm': None}]
    assert parse_route_variants('[5]', 2) == [NOTHING, None]
    assert parse_route_variants('not json', 2) == [NOTHING, NOTHING]
    assert parse_route_variants('{"gtfs": "a"}', 1) == [NOTHING]
    # The key of the GTFS side before release 0.7.
    assert parse_route_variants(json.dumps([{'atlas': 'Bern', 'osm': '7'}]), 1) == [{'gtfs': 'Bern', 'osm': '7'}]


def test_route_directions_keep_their_position_and_variants_reach_the_route_lookup(monkeypatch):
    filters = parse_filter_params({
        'station_filter': 'A,B', 'filter_types': 'route,route', 'route_directions': ',1',
        'route_variants': json.dumps([{'osm': '5'}, None]),
    })
    assert filters['route_directions'] == ['', '1']
    calls = []

    def route_lookup(route_id, direction, variants):
        calls.append((route_id, direction, variants))
        return {'atlas_sloids': [], 'osm_nodes': ['5']}

    monkeypatch.setattr(query_builder, 'get_stops_for_route', route_lookup)
    query_builder.search_token_conditions(filters)
    assert calls == [('A', None, {'gtfs': None, 'osm': '5'}), ('B', '1', None)]
