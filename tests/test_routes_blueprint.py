from types import SimpleNamespace

from flask import render_template

from backend.blueprints import routes as routes_module
from backend.blueprints.routes import _build_direction_group, _partition_route_items, _route_sort_key
from backend.extensions import db
from backend.models import LineFamily, LineFamilyMatch


class _TemplatePagination:
    def __init__(self):
        self.total = 1
        self.has_prev = False
        self.has_next = False
        self.page = 1
        self.pages = 1
        self.prev_num = 1
        self.next_num = 1

    def iter_pages(self, **_kwargs):
        return [1]


def test_build_direction_group_keeps_variant_sloids_and_osm_relation_id():
    atlas_itinerary = SimpleNamespace(
        direction_id='0',
        display_name='Luzern -> Sursee',
        representative_headsign='Sursee',
    )
    osm_itinerary = SimpleNamespace(
        direction_id='0',
        display_name='Luzern - Sursee',
        representative_headsign='Sursee',
        to_name='Sursee',
        source_itinerary_id='777',
    )
    atlas_calls = [
        SimpleNamespace(
            source_sloid='ch:1:sloid:A',
            source_sloid_variants='["ch:1:sloid:A", "ch:1:sloid:C"]',
            source_node_id=None,
            uic_ref='8501000',
            stop_label='Luzern',
            stop_sequence=1,
            stop_lat=None,
            stop_lon=None,
        )
    ]
    osm_calls = [
        SimpleNamespace(
            source_sloid=None,
            source_sloid_variants=None,
            source_node_id='123',
            uic_ref='8501000',
            stop_label='Luzern',
            stop_sequence=1,
            stop_lat=None,
            stop_lon=None,
        )
    ]

    direction_group = _build_direction_group(atlas_itinerary, osm_itinerary, atlas_calls, osm_calls)

    assert direction_group['osm_relation_id'] == '777'
    assert direction_group['atlas_headsign'] == 'Sursee'
    assert direction_group['osm_to_name'] == 'Sursee'
    assert direction_group['atlas_uic_groups'][0]['member_count'] == 2
    assert direction_group['atlas_uic_groups'][0]['members'][0]['stop_ids'] == ['ch:1:sloid:A', 'ch:1:sloid:C']


def test_routes_template_uses_route_master_link_and_itinerary_relation(app):
    route_rows = [
        {
            'display_mode': 'matched',
            'is_matched': True,
            'match_label': 'Matched',
            'atlas_route_id': '91-1-A-j26-1',
            'atlas_route_display_id': 'S1',
            'atlas_route_short_name': '91',
            'atlas_route_long_name': 'Luzern - Sursee',
            'atlas_route_name': 'Luzern - Sursee',
            'atlas_route_type': 'rail',
            'atlas_family_origin': 'atlas_gtfs',
            'atlas_route_operator': 'agency-1',
            'atlas_gtfs_route_id': '91-1-A-j26-1',
            'atlas_normalized_route_id': '911aj261',
            'atlas_line_id': '91-1-A-j26-1',
            'atlas_operators_summary': None,
            'osm_route_name': 'Luzern - Sursee',
            'osm_gtfs_route_id': '91-1-A-j26-1',
            'osm_route_display_id': '91-1-A-j26-1',
            'osm_route_id_label': 'GTFS ID',
            'osm_route_master_id': '999',
            'osm_route_id': '555',
            'osm_ref': 'S1',
            'osm_route_type': 'train',
            'osm_family_origin': 'route_master',
            'osm_operator': 'SBB',
            'osm_operator_wikidata': 'Q123',
            'osm_network': 'S-Bahn Schweiz',
            'osm_network_wikidata': 'Q456',
            'osm_normalized_route_id': '911aj261',
            'is_non_gtfs': False,
            'variant_count': 1,
            'atlas_variant_count': 1,
            'osm_variant_count': 1,
            'matched_variant_count': 1,
            'direction_groups': [
                {
                    'direction_id': '0',
                    'direction_label': 'Luzern -> Sursee',
                    'representative_headsign': 'Sursee',
                    'atlas_headsign': 'Sursee',
                    'osm_to_name': 'Sursee',
                    'osm_relation_id': '777',
                    'has_atlas_variant': True,
                    'has_osm_variant': True,
                    'is_matched': True,
                    'atlas_uic_groups': [
                        {
                            'uic_ref': '8501000',
                            'stop_label': 'Luzern',
                            'member_count': 2,
                            'members': [
                                {
                                    'stop_id': 'ch:1:sloid:A',
                                    'stop_ids': ['ch:1:sloid:A', 'ch:1:sloid:C'],
                                    'stop_label': 'Luzern',
                                    'stop_sequence': 1,
                                    'lat': None,
                                    'lon': None,
                                }
                            ],
                        }
                    ],
                    'osm_uic_groups': [],
                }
            ],
            'map_filter': None,
        }
    ]

    with app.test_request_context('/routes'):
        rendered = render_template(
            'pages/routes.html',
            active_view='routes',
            listing_endpoint='routes.routes_page',
            route_rows=route_rows,
            pagination=_TemplatePagination(),
            range_start=1,
            range_end=1,
            atlas_operator_query='',
            osm_operator_query='',
            matched_filter='all',
            match_filter_labels={'all': 'All'},
            q='',
            search_placeholder='Search route',
            per_page=10,
            per_page_options=[10],
            available_atlas_operators=[],
            selected_atlas_operators=[],
            available_osm_operators=[],
            selected_osm_operators=[],
        )

    assert 'View route master 999 on OSM' in rendered
    assert 'https://www.openstreetmap.org/relation/999' in rendered
    assert 'View itinerary relation 777 on OSM' in rendered
    assert 'GTFS ID: 91-1-A-j26-1' in rendered
    assert 'Route master ID' in rendered
    assert 'Operator Wikidata' in rendered
    assert 'SLOIDs: ch:1:sloid:A, ch:1:sloid:C' in rendered
    assert 'ATLAS variants: 1 | OSM variants: 1 | Matched: 1' in rendered
    assert 'Subroutes and itineraries are experimental.' in rendered
    assert 'should not yet be treated as a canonical OSM mapping target.' in rendered
    assert 'OSM to_name:' in rendered
    assert 'js/components/map-core.js' in rendered
    assert 'js/components/header-summary.js' in rendered
    assert 'js/pages/routes.js' in rendered


def test_routes_template_labels_variant_direction_and_headsign(app):
    route_rows = [
        {
            'display_mode': 'osm_only',
            'is_matched': False,
            'match_label': 'Unmatched OSM',
            'atlas_route_id': None,
            'atlas_route_short_name': None,
            'atlas_route_long_name': None,
            'atlas_route_name': None,
            'atlas_operators_summary': None,
            'osm_route_name': 'Route 31',
            'osm_gtfs_route_id': '31',
            'osm_route_display_id': '31',
            'osm_route_id_label': 'GTFS ID',
            'osm_route_master_id': None,
            'osm_route_id': '300',
            'is_non_gtfs': False,
            'variant_count': 1,
            'atlas_variant_count': 0,
            'osm_variant_count': 1,
            'matched_variant_count': 0,
            'direction_groups': [
                {
                    'direction_id': '0',
                    'direction_label': 'Unique Variant Label',
                    'representative_headsign': 'Unique Variant Label',
                    'atlas_headsign': None,
                    'osm_to_name': 'Unique Variant Label',
                    'osm_relation_id': '300',
                    'has_atlas_variant': False,
                    'has_osm_variant': True,
                    'is_matched': False,
                    'atlas_uic_groups': [],
                    'osm_uic_groups': [],
                    'match_status': 'unmatched-osm',
                    'match_label': 'Unmatched OSM variant',
                }
            ],
            'map_filter': None,
        }
    ]

    with app.test_request_context('/routes'):
        rendered = render_template(
            'pages/routes.html',
            active_view='routes',
            listing_endpoint='routes.routes_page',
            route_rows=route_rows,
            pagination=_TemplatePagination(),
            range_start=1,
            range_end=1,
            atlas_operator_query='',
            osm_operator_query='',
            matched_filter='all',
            match_filter_labels={'all': 'All'},
            q='',
            search_placeholder='Search route',
            per_page=10,
            per_page_options=[10],
            available_atlas_operators=[],
            selected_atlas_operators=[],
            available_osm_operators=[],
            selected_osm_operators=[],
        )

    assert 'Dir: 0' in rendered
    assert 'Unique Variant Label' in rendered
    assert 'to_name:' in rendered
    assert rendered.count('Unique Variant Label') >= 2


def test_partition_route_items_separates_non_gtfs_routes():
    gtfs_items, non_gtfs_items = _partition_route_items([
        {'sort_route_id': '11', 'is_non_gtfs': False},
        {'sort_route_id': '006', 'is_non_gtfs': True},
    ])

    assert [item['sort_route_id'] for item in gtfs_items] == ['11']
    assert [item['sort_route_id'] for item in non_gtfs_items] == ['006']


def test_load_line_family_rows_queries_only_required_columns(monkeypatch):
    captured = {}

    class _FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return []

    def _fake_query(*args):
        captured['args'] = args
        return _FakeQuery()

    monkeypatch.setattr(routes_module.db.session, 'query', _fake_query)

    routes_module._load_line_family_rows('atlas')

    assert captured['args'][0] is not routes_module.LineFamily
    assert len(captured['args']) > 1


def test_query_route_page_filters_orders_and_paginates_in_sql(app, monkeypatch):
    with app.app_context():
        LineFamily.__table__.create(db.engine)
        LineFamilyMatch.__table__.create(db.engine)
        db.session.add_all([
            LineFamily(
                id=1,
                source='atlas',
                source_family_id='atlas-z',
                display_route_id='Z',
            ),
            LineFamily(
                id=2,
                source='atlas',
                source_family_id='atlas-a',
                display_route_id='A',
            ),
            LineFamily(
                id=10,
                source='osm',
                source_family_id='osm-z',
                display_route_id='Z',
                operator='SBB',
            ),
            LineFamily(
                id=11,
                source='osm',
                source_family_id='osm-b',
                display_route_id='B',
                operator='BLS',
            ),
            LineFamily(
                id=12,
                source='osm',
                source_family_id='osm-non-gtfs',
                display_route_id='N',
                is_non_gtfs=True,
            ),
            LineFamilyMatch(
                id=100,
                atlas_line_family_id=1,
                osm_line_family_id=10,
            ),
        ])
        db.session.commit()
        monkeypatch.setattr(routes_module, '_load_atlas_operator_map', lambda _ids: {})

        first_page, total = routes_module._query_route_page(page=1, per_page=2)
        second_page, second_total = routes_module._query_route_page(page=2, per_page=2)
        osm_filtered, filtered_total = routes_module._query_route_page(
            page=1,
            per_page=10,
            osm_operators=['BLS'],
        )
        osm_or_filtered, osm_or_total = routes_module._query_route_page(
            page=1,
            per_page=10,
            osm_operators=['BLS', 'SBB'],
        )
        non_gtfs, non_gtfs_total = routes_module._query_route_page(
            page=1,
            per_page=10,
            non_gtfs_only=True,
        )

    assert total == 3
    assert second_total == 3
    assert [item['display_mode'] for item in first_page] == ['matched', 'atlas_only']
    assert [item['display_mode'] for item in second_page] == ['osm_only']
    assert [item['osm_route_display_id'] for item in osm_filtered] == ['B']
    assert filtered_total == 1
    assert {item['osm_route_display_id'] for item in osm_or_filtered} == {'B', 'Z'}
    assert osm_or_total == 2
    assert [item['osm_route_display_id'] for item in non_gtfs] == ['N']
    assert non_gtfs_total == 1


def test_parse_multi_filter_splits_comma_separated_and_repeated_values(app):
    with app.test_request_context(
        '/routes?atlas_operator=AAGL,AAGR&atlas_operator=AAGL'
    ):
        selected = routes_module._parse_multi_filter('atlas_operator')

    assert selected == ['AAGL', 'AAGR']


def test_routes_page_uses_sql_page_loader(client, monkeypatch):
    captured = {}

    def _fake_query_route_page(**kwargs):
        captured.update(kwargs)
        return [], 321

    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': False})
    monkeypatch.setattr(routes_module, '_query_route_page', _fake_query_route_page)
    monkeypatch.setattr(routes_module, '_load_available_atlas_operators', lambda: [])
    monkeypatch.setattr(routes_module, '_load_available_osm_route_operators', lambda: [])
    monkeypatch.setattr(routes_module, '_build_route_rows', lambda items: items)

    response = client.get(
        '/routes?page=7&per_page=20&matched=unmatched_osm'
        '&atlas_operator=BLS,SBB&osm_operator=BLS&q=night'
    )

    assert response.status_code == 200
    assert captured == {
        'page': 7,
        'per_page': 20,
        'q': 'night',
        'matched_filter': 'unmatched_osm',
        'atlas_operators': ['BLS', 'SBB'],
        'osm_operators': ['BLS'],
    }


def test_routes_return_503_before_database_access_during_maintenance(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'get_status', lambda: {
        'blocking_maintenance': True,
        'phase': 'import',
        'message': 'Replacing route tables',
    })
    monkeypatch.setattr(
        routes_module,
        '_query_route_page',
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError('database queried')),
    )

    html_response = client.get('/routes')
    api_response = client.get('/api/routes/gtfs-stop-id-sloid/summary')

    assert html_response.status_code == 503
    assert html_response.headers['Retry-After'] == '30'
    assert b'Replacing route tables' in html_response.data
    assert api_response.status_code == 503
    assert api_response.json == {
        'error': 'Replacing route tables',
        'phase': 'import',
        'retry_after_seconds': 30,
    }


def test_routes_return_controlled_503_for_database_timeout(client, monkeypatch):
    class _LockTimeout(Exception):
        sqlstate = '55P03'

    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': False})
    monkeypatch.setattr(
        routes_module,
        '_query_route_page',
        lambda **_kwargs: (_ for _ in ()).throw(_LockTimeout()),
    )

    response = client.get('/routes')

    assert response.status_code == 503
    assert response.headers['Retry-After'] == '30'
    assert b'Route data is temporarily busy' in response.data


def test_route_sort_key_places_matched_routes_first():
    items = [
        {'display_mode': 'osm_only', 'sort_route_id': '999'},
        {'display_mode': 'matched', 'sort_route_id': 'zzz'},
        {'display_mode': 'atlas_only', 'sort_route_id': '001'},
        {'display_mode': 'matched', 'sort_route_id': 'aaa'},
    ]

    sorted_items = sorted(items, key=_route_sort_key)

    assert [item['display_mode'] for item in sorted_items[:2]] == ['matched', 'matched']


def test_non_gtfs_routes_template_uses_route_ref_label_and_notice(app):
    route_rows = [
        {
            'display_mode': 'osm_only',
            'is_matched': False,
            'match_label': 'Non-GTFS OSM',
            'atlas_route_id': None,
            'atlas_route_short_name': None,
            'atlas_route_long_name': None,
            'atlas_route_name': None,
            'atlas_operators_summary': None,
            'osm_route_name': 'Flixbus 006',
            'osm_gtfs_route_id': None,
            'osm_route_display_id': '006',
            'osm_route_id_label': 'Route ref',
            'osm_route_master_id': None,
            'osm_route_id': '6006',
            'is_non_gtfs': True,
            'variant_count': 0,
            'atlas_variant_count': 0,
            'osm_variant_count': 0,
            'matched_variant_count': 0,
            'direction_groups': [],
            'map_filter': None,
        }
    ]

    with app.test_request_context('/routes/non-gtfs'):
        rendered = render_template(
            'pages/routes.html',
            active_view='non_gtfs_routes',
            listing_endpoint='routes.non_gtfs_routes_page',
            route_rows=route_rows,
            pagination=_TemplatePagination(),
            range_start=1,
            range_end=1,
            atlas_operator_query='',
            osm_operator_query='',
            matched_filter='all',
            match_filter_labels={'all': 'All'},
            q='',
            search_placeholder='Search route',
            per_page=10,
            per_page_options=[10],
            available_atlas_operators=[],
            selected_atlas_operators=[],
            available_osm_operators=[],
            selected_osm_operators=[],
        )

    assert 'Non-GTFS routes' in rendered
    assert 'We do not attempt to match these routes.' in rendered
    assert 'Route ref: 006' in rendered
    assert 'GTFS ID: 006' not in rendered
    assert 'Excluded from route matching.' in rendered
    assert 'Subroutes and itineraries are experimental.' not in rendered
