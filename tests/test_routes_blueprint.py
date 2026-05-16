from types import SimpleNamespace

from flask import render_template

from backend.blueprints import routes as routes_module
from backend.blueprints.routes import _build_direction_group, _partition_route_items, _route_sort_key


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
    assert direction_group['atlas_uic_groups'][0]['member_count'] == 2
    assert direction_group['atlas_uic_groups'][0]['members'][0]['stop_ids'] == ['ch:1:sloid:A', 'ch:1:sloid:C']


def test_routes_template_uses_route_master_link_and_itinerary_relation(app):
    route_rows = [
        {
            'display_mode': 'matched',
            'is_matched': True,
            'match_label': 'Matched',
            'atlas_route_id': '91-1-A-j26-1',
            'atlas_route_short_name': '91',
            'atlas_route_long_name': 'Luzern - Sursee',
            'atlas_route_name': 'Luzern - Sursee',
            'atlas_operators_summary': None,
            'osm_route_name': 'Luzern - Sursee',
            'osm_gtfs_route_id': '91-1-A-j26-1',
            'osm_route_display_id': '91-1-A-j26-1',
            'osm_route_id_label': 'GTFS ID',
            'osm_route_master_id': '999',
            'osm_route_id': '555',
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
                    'osm_relation_id': '777',
                    'has_atlas_variant': True,
                    'has_osm_variant': True,
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
    assert 'SLOIDs: ch:1:sloid:A, ch:1:sloid:C' in rendered
    assert 'ATLAS variants: 1 | OSM variants: 1 | Matched: 1' in rendered


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

    assert 'Non GTFS routes' in rendered
    assert 'We do not attempt to match these routes.' in rendered
    assert 'Route ref: 006' in rendered
    assert 'GTFS ID: 006' not in rendered
    assert 'Excluded from route matching.' in rendered