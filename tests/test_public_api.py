"""Public API: /api/lookup, stop-link page metadata, /llms.txt and robots.txt."""

import re
from urllib.robotparser import RobotFileParser

import pytest

from backend.models import AtlasStop, DatasetPublication, OsmNode, Problem, StopsMatched
from backend.services.docs_order import doc_sort_key


def add_entry(session, sloid=None, osm_node_id=None, distance_m=None, problems=(), atlas=None, osm=None):
    if sloid and session.get(AtlasStop, sloid) is None:
        session.add(AtlasStop(sloid=sloid, **(atlas or {})))
    if osm_node_id and session.get(OsmNode, osm_node_id) is None:
        session.add(OsmNode(osm_node_id=osm_node_id, **(osm or {})))
    entry = StopsMatched(
        sloid=sloid,
        osm_node_id=osm_node_id,
        stop_type='matched' if sloid and osm_node_id else ('atlas_unmatched' if sloid else 'osm_unmatched'),
        match_type='uic_reference_one_osm' if sloid and osm_node_id else None,
        distance_m=distance_m,
        atlas_lat=47.0 if sloid else None,
        atlas_lon=8.0 if sloid else None,
        osm_lat=47.0001 if osm_node_id else None,
        osm_lon=8.0001 if osm_node_id else None,
    )
    session.add(entry)
    session.flush()
    for problem_type, priority in problems:
        session.add(Problem(stop_id=entry.id, problem_type=problem_type, priority=priority))
    return entry


@pytest.fixture
def stops(problems_db):
    """Node 100 matched to two stops of station 8500001, way 500 matched to one, node 300 unmatched."""
    session = problems_db
    station = {'uic_ref': '8500001', 'atlas_designation_official': 'Bern, Bahnhof', 'atlas_business_org_abbr': 'BLS'}
    node = {'osm_name': 'Bahnhof', 'osm_tags': {'name': 'Bahnhof', 'public_transport': 'platform'}}
    add_entry(session, 'ch:1:sloid:1:0:2', '100', 55.94, [('distance', 2)], {**station, 'atlas_designation': 'B'}, node)
    add_entry(session, 'ch:1:sloid:1:0:1', '100', 0.92, [('attributes', 3), ('duplicates', 1)],
              {**station, 'atlas_designation': 'A'}, node)
    add_entry(session, 'ch:1:sloid:9', 'way_500', 3.0)
    add_entry(session, osm_node_id='300', osm={'osm_name': 'Bahnhof Nord', 'osm_uic_ref': '8500001'})
    session.commit()
    return session


def lookup(client, query, status=200):
    response = client.get(f'/api/lookup?{query}')
    assert response.status_code == status
    return response.get_json()


def matches(payload):
    return [(r['source'] and r['source']['sloid'], r['osm'] and r['osm']['id']) for r in payload['results']]


def test_lookup_lists_every_match_closest_first(client, stops):
    payload = lookup(client, 'osm=node/100')

    assert payload['query'] == {'osm': 'node/100'}
    assert payload['count'] == 2 and payload['truncated'] is False
    assert matches(payload) == [('ch:1:sloid:1:0:1', 'node/100'), ('ch:1:sloid:1:0:2', 'node/100')]

    closest = payload['results'][0]
    assert closest['stop_type'] == 'matched' and closest['distance_m'] == 0.9
    assert closest['problems'] == [{'type': 'duplicates', 'priority': 1}, {'type': 'attributes', 'priority': 3}]
    assert closest['source'] == {
        'sloid': 'ch:1:sloid:1:0:1', 'name': 'Bern, Bahnhof', 'designation': 'A', 'uic_ref': '8500001',
        'operator': 'BLS', 'lat': 47.0, 'lon': 8.0, 'map_url': '/?sloid=ch:1:sloid:1:0:1',
    }
    assert closest['osm']['url'] == 'https://www.openstreetmap.org/node/100'
    assert closest['osm']['map_url'] == '/?osm=node/100'
    assert closest['osm']['tags'] == {'name': 'Bahnhof', 'public_transport': 'platform'}
    assert 'id' not in closest  # database row numbers change with every import


def test_lookup_converts_ways_and_narrows_by_several_parameters(client, stops):
    assert matches(lookup(client, 'osm=way/500')) == [('ch:1:sloid:9', 'way/500')]
    assert matches(lookup(client, 'sloid=ch:1:sloid:1:0:2&osm=node/100')) == [('ch:1:sloid:1:0:2', 'node/100')]
    assert lookup(client, 'sloid=ch:1:sloid:9&osm=node/100')['count'] == 0


def test_lookup_by_station_finds_both_sources(client, stops):
    payload = lookup(client, 'uic_ref=8500001')

    assert matches(payload) == [('ch:1:sloid:1:0:1', 'node/100'), ('ch:1:sloid:1:0:2', 'node/100'), (None, 'node/300')]
    assert payload['results'][2]['stop_type'] == 'osm_unmatched'
    assert payload['results'][2]['distance_m'] is None


def test_unknown_stop_is_an_empty_result_not_an_error(client, stops):
    payload = lookup(client, 'osm=node/999')

    assert payload['count'] == 0 and payload['results'] == []
    assert payload['snapshot'] is None


@pytest.mark.parametrize('query', ['', 'osm=', 'osm=100', 'osm=relation/1', 'osm=node/1/2', 'q=bern'])
def test_lookup_rejects_missing_or_malformed_identifiers(client, query):
    assert '/docs/public_api' in lookup(client, query, status=400)['error']


def test_lookup_names_the_snapshot(client, stops):
    stops.add(DatasetPublication(run_id='run-1', manifest={
        'generated_at': '2026-10-31T19:08:29+00:00',
        'metadata': {'attribution': {'osm': '© OpenStreetMap contributors, ODbL'}},
    }))
    stops.commit()

    payload = lookup(client, 'sloid=ch:1:sloid:9')

    assert payload['source_label'] == 'ATLAS'
    assert payload['snapshot'] == {
        'run_id': 'run-1',
        'generated_at': '2026-10-31T19:08:29+00:00',
        'attribution': {'osm': '© OpenStreetMap contributors, ODbL'},
    }


def test_lookup_answers_503_when_the_database_fails(client):
    response = client.get('/api/lookup?osm=node/100')  # no tables: every query fails

    assert response.status_code == 503
    assert response.headers['Retry-After'] == '60'


def head(html):
    title = re.search(r'<title>(.*?)</title>', html).group(1)
    description = re.search(r'<meta name="description" content="(.*?)">', html).group(1)
    return title, description


def test_stop_links_name_the_stop_in_their_html(client, stops):
    html = client.get('/?osm=node/100').get_data(as_text=True)
    title, description = head(html)

    assert title.startswith('Bahnhof · node/100 | ')
    assert description == ('OSM node/100 &#34;Bahnhof&#34; is matched to ATLAS ch:1:sloid:1:0:1 &#34;Bern, Bahnhof&#34; (0.9 m), '
                           'ATLAS ch:1:sloid:1:0:2 &#34;Bern, Bahnhof&#34; (55.9 m). '
                           'Problems: duplicates P1, distance P2, attributes P3.')
    assert f'<meta property="og:description" content="{description}">' in html
    assert '<link rel="alternate" type="application/json" href="/api/lookup?osm=node/100">' in html
    assert '<p class="visually-hidden">OSM node/100' in html

    unmatched = head(client.get('/?osm=node/300').get_data(as_text=True))[1]
    assert unmatched == 'OSM node/300 &#34;Bahnhof Nord&#34; has no direct ATLAS match (stop type osm_unmatched).'

    pair_title, pair = head(client.get('/problems?sloid=ch:1:sloid:9&osm=way/500').get_data(as_text=True))
    assert pair_title.startswith('ch:1:sloid:9 | Public Transport Data Problems')
    assert pair == 'ATLAS ch:1:sloid:9 is matched to OSM way/500 (3.0 m).'


@pytest.mark.parametrize('path', ['/?osm=node/999', '/?osm=bogus', '/?uic_ref=8500001', '/problems'])
def test_pages_without_a_known_stop_keep_their_usual_head(client, stops, path):
    html = client.get(path).get_data(as_text=True)

    assert ' · ' not in head(html)[0]
    assert 'application/json' not in html


def test_stop_link_pages_render_when_the_database_fails(client):
    response = client.get('/?osm=node/100')

    assert response.status_code == 200
    assert 'application/json' not in response.get_data(as_text=True)


def test_robots_allows_only_the_public_api(client):
    robots = client.get('/robots.txt').get_data(as_text=True)
    parser = RobotFileParser()
    parser.parse(robots.splitlines())

    for path, allowed in [('/', True), ('/?osm=node/1', True), ('/llms.txt', True), ('/docs/public_api', True),
                          ('/api/lookup?osm=node/1', True), ('/api/stop_by_id', False), ('/api/data', False)]:
        assert parser.can_fetch('*', f'https://atlas.osm.ch{path}') is allowed, path


def test_llms_txt_explains_the_lookup_and_links_to_existing_docs(client):
    response = client.get('/llms.txt')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.content_type == 'text/plain; charset=utf-8'
    assert text.startswith('# OSM & ATLAS Synchronization\n')
    assert '`GET /api/lookup`' in text and '`osm=node/<id>`' in text
    doc_links = re.findall(r'\]\((/docs/[a-z_]+)\)', text)
    assert '/docs/public_api' in doc_links
    for link in doc_links:
        assert client.get(link).status_code == 200, link


def test_doc_sort_key_orders_pages_by_section_number():
    names = ['Changelog.md', '2.10 Public API.md', '2.3.1 Study.md', '2.9 Permalinks.md', '2. Web app.md',
             '2.1 Map.md', '10. Later.md', '2.3 Stats.md']

    assert sorted(names, key=doc_sort_key) == [
        '2. Web app.md', '2.1 Map.md', '2.3 Stats.md', '2.3.1 Study.md', '2.9 Permalinks.md',
        '2.10 Public API.md', '10. Later.md', 'Changelog.md',
    ]
