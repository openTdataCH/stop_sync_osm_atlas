from backend.blueprints import routes as routes_module


def test_routes_gtfs_stop_id_sloid_tab_renders(client):
    response = client.get('/routes/gtfs-stop-id-sloid')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'GTFS stop_id' in html
    assert 'SLOID' in html
    assert 'routesGtfsStopIdSloidMap' in html
    assert 'routesGtfsStopIdSloidConfig' in html
    assert 'css/components/popup.css' in html
    assert 'js/components/popup-utils.js' in html
    assert 'js/components/popup-renderer.js' in html


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