from backend.blueprints import routes as routes_module


def test_routes_gtfs_stop_id_sloid_tab_renders(client):
    response = client.get('/routes/gtfs-stop-id-sloid')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'GTFS stop_id' in html
    assert 'SLOID' in html
    assert 'routesGtfsStopIdSloidMap' in html
    assert 'routesGtfsStopIdSloidConfig' in html
    assert 'routesGtfsStopIdSloidStatus' in html
    assert 'routesGtfsStopIdSloidRetry' in html
    assert 'class="zoom-banner d-none"' in html
    assert 'Updating map' not in html
    assert 'routesGtfsStopIdSloidSearchForm' in html
    assert 'routesGtfsStopIdSloidSearchInput' in html
    assert 'placeholder="Search stops..."' in html
    assert 'routes-page--gtfs-map' in html
    assert 'routes-container--gtfs-map' in html
    assert 'searchUrl' in html
    assert 'css/components/popup.css' in html
    assert 'js/components/popup-utils.js' in html
    assert 'js/components/popup-renderer.js' in html
    assert 'js/components/map-core.js' in html
    assert 'js/components/map-viewport-loader.js' in html
    assert 'js/components/map-layer-registry.js' in html
    assert 'js/components/map-popup-controller.js' in html
    assert 'js/components/filter-chip-utils.js' in html


def test_routes_gtfs_stop_id_sloid_summary_api(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'build_gtfs_stop_id_sloid_summary', lambda: {
        'algorithm_version': 'strict_plus_coordinate_proximity_plus_unique_number',
        'total_gtfs_stops': 10,
        'matched_gtfs_stops': 7,
        'unmatched_gtfs_stops': 3,
        'gtfs_coverage_percent': 70.0,
        'total_atlas_stops': 12,
        'matched_atlas_stops': 8,
        'unmatched_atlas_stops': 4,
        'atlas_coverage_percent': 66.7,
        'assignments': {
            'strict': 4,
            'coordinate_proximity': 3,
            'unique_number_fallback': 1,
            'total': 8,
        },
    })

    response = client.get('/api/routes/gtfs-stop-id-sloid/summary')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_gtfs_stops'] == 10
    assert payload['assignments']['coordinate_proximity'] == 3


def test_routes_gtfs_stop_id_sloid_map_api(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'build_gtfs_stop_id_sloid_map_payload', lambda *_args: {
        'gtfs_stops': [{'stop_id': '8500:0:1'}],
        'atlas_stops': [{'sloid': 'S1'}],
        'matches': [{'stop_id': '8500:0:1', 'sloid': 'S1'}],
        'meta': {'gtfs_returned': 1, 'atlas_returned': 1, 'matches_returned': 1},
    })

    response = client.get('/api/routes/gtfs-stop-id-sloid/map?min_lat=46&min_lon=7&max_lat=47&max_lon=8&zoom=12')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['meta']['matches_returned'] == 1
    assert payload['atlas_stops'][0]['sloid'] == 'S1'


def test_routes_gtfs_stop_id_sloid_map_api_forwards_identifier_search(client, monkeypatch):
    captured = {}

    def build_payload(*args):
        captured['args'] = args
        return {'gtfs_stops': [], 'atlas_stops': [], 'matches': [], 'meta': {}}

    monkeypatch.setattr(routes_module, 'build_gtfs_stop_id_sloid_map_payload', build_payload)

    response = client.get(
        '/api/routes/gtfs-stop-id-sloid/map'
        '?min_lat=46&min_lon=7&max_lat=47&max_lon=8&zoom=12'
        '&search_kind=sloid&search_value=ch%3A1%3Asloid%3A92000'
    )

    assert response.status_code == 200
    assert captured['args'][5:7] == ('sloid', 'ch:1:sloid:92000')
    assert captured['args'][7:] == (None, True)


def test_routes_gtfs_stop_id_sloid_map_api_forwards_shared_zoom_limit(client, monkeypatch):
    captured = []

    def build_payload(*args):
        captured.append(args)
        return {'gtfs_stops': [], 'atlas_stops': [], 'matches': [], 'meta': {}}

    monkeypatch.setattr(routes_module, 'build_gtfs_stop_id_sloid_map_payload', build_payload)
    base_url = '/api/routes/gtfs-stop-id-sloid/map?min_lat=46&min_lon=7&max_lat=47&max_lon=8&zoom=14'

    assert client.get(base_url + '&limit=1800').status_code == 200
    assert captured[-1][7] == 1800
    assert captured[-1][8] is True
    assert client.get(base_url + '&limit=all').status_code == 200
    assert captured[-1][7] == 'all'
    assert client.get(base_url + '&limit=1800&include_matches=0').status_code == 200
    assert captured[-1][8] is False
    assert client.get(base_url + '&limit=0').status_code == 400
    assert client.get(base_url + '&include_matches=maybe').status_code == 400


def test_routes_gtfs_stop_id_sloid_search_api_returns_mappable_targets(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'find_gtfs_stop_id_sloid_targets', lambda kind, value: [{
        'entity_type': 'gtfs',
        'identifier': value,
        'lat': 46.95,
        'lon': 7.44,
    }])

    response = client.get(
        '/api/routes/gtfs-stop-id-sloid/search?kind=gtfs_stop_id&value=8507000%3A0%3A1'
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['search'] == {'kind': 'gtfs_stop_id', 'value': '8507000:0:1'}
    assert payload['targets'][0]['entity_type'] == 'gtfs'


def test_routes_gtfs_stop_id_sloid_search_api_validates_and_reports_missing(client, monkeypatch):
    assert client.get('/api/routes/gtfs-stop-id-sloid/search?kind=unknown&value=x').status_code == 400

    monkeypatch.setattr(routes_module, 'find_gtfs_stop_id_sloid_targets', lambda *_args: [])
    response = client.get('/api/routes/gtfs-stop-id-sloid/search?kind=uic&value=8507000')

    assert response.status_code == 404
    assert 'No mappable stop' in response.get_json()['error']


def test_routes_gtfs_stop_id_sloid_popup_api(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'build_gtfs_stop_popup', lambda stop_id: {
        'entity_type': 'gtfs',
        'stop_id': stop_id,
    })

    response = client.get('/api/routes/gtfs-stop-id-sloid/popup?entity_type=gtfs&stop_id=8500:0:1')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['entity_type'] == 'gtfs'
    assert payload['stop_id'] == '8500:0:1'
