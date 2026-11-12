"""Route permalinks: a linked variant's page, canonical parameters, rendered ids."""

import pytest
from flask import render_template

from backend.pages import routes as route_pages
from backend.services import route_listing
from backend.extensions import db
from backend.models import Itinerary, LineFamily, LineFamilyMatch
from tests.test_routes_blueprint import _TemplatePagination

MATCHED_ATLAS = '91-1-Z-j26-1:0:Zürich HB'


@pytest.fixture
def route_list(app, monkeypatch):
    """Cards in list order: matched Z, ATLAS-only A, OSM-only B; plus non-GTFS N."""
    with app.app_context():
        for model in (LineFamily, LineFamilyMatch, Itinerary):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([
            LineFamily(id=1, source='gtfs', source_family_id='atlas-z', display_route_id='Z'),
            LineFamily(id=2, source='gtfs', source_family_id='atlas-a', display_route_id='A'),
            LineFamily(id=10, source='osm', source_family_id='osm-z', display_route_id='Z'),
            LineFamily(id=11, source='osm', source_family_id='osm-b', display_route_id='B'),
            LineFamily(id=12, source='osm', source_family_id='osm-n', display_route_id='N', is_non_gtfs=True),
            LineFamilyMatch(id=100, gtfs_line_family_id=1, osm_line_family_id=10),
            Itinerary(id=1, source='gtfs', line_family_id=1, source_itinerary_id=MATCHED_ATLAS),
            Itinerary(id=2, source='gtfs', line_family_id=2, source_itinerary_id='91-1-A-j26-1:0:Bern'),
            Itinerary(id=3, source='osm', line_family_id=10, source_itinerary_id='1010'),
            Itinerary(id=4, source='osm', line_family_id=11, source_itinerary_id='1011'),
            Itinerary(id=5, source='osm', line_family_id=12, source_itinerary_id='1012'),
        ])
        db.session.commit()
        monkeypatch.setattr(route_listing, '_load_atlas_operator_map', lambda _ids: {})
        yield


def locate(gtfs_variant=None, osm_variant=None, per_page=1, **filters):
    return route_listing.locate_route_variant_page(
        gtfs_variant=gtfs_variant, osm_variant=osm_variant, per_page=per_page, **filters,
    )


def test_a_variant_is_found_on_the_page_of_its_card_in_list_order(route_list):
    order = [item['display_mode'] for item in route_listing.query_route_page(page=1, per_page=10)[0]]
    assert order == ['matched', 'gtfs_only', 'osm_only']

    assert locate(gtfs_variant=MATCHED_ATLAS, osm_variant='1010') == 1
    assert locate(gtfs_variant='91-1-A-j26-1:0:Bern') == 2
    assert locate(osm_variant='1011') == 3
    assert locate(osm_variant='1011', per_page=2) == 2
    assert locate(osm_variant='1012', non_gtfs_only=True) == 1


def test_a_variant_outside_the_filters_or_the_snapshot_is_not_found(route_list):
    assert locate(osm_variant='1011', matched_filter='matched') is None
    assert locate(osm_variant='1012') is None  # non-GTFS routes are not in /routes
    assert locate(osm_variant='999') is None
    assert locate(gtfs_variant=MATCHED_ATLAS, osm_variant='1011') is None
    assert locate() is None


@pytest.fixture
def fake_listing(monkeypatch):
    captured = {}

    def query_route_page(**kwargs):
        captured.update(kwargs)
        return [], 30

    monkeypatch.setattr(route_listing, 'query_route_page', query_route_page)
    monkeypatch.setattr(route_listing, 'load_available_atlas_operators', lambda: [])
    monkeypatch.setattr(route_listing, 'load_available_osm_route_operators', lambda: [])
    monkeypatch.setattr(route_listing, 'build_route_rows', lambda items: items)
    return captured


def test_the_server_redirects_a_variant_link_to_the_page_that_holds_it(client, monkeypatch, fake_listing):
    calls = []
    monkeypatch.setattr(route_listing, 'locate_route_variant_page', lambda **kwargs: calls.append(kwargs) or 3)

    response = client.get('/routes?matched=unmatched_osm&osm_variant=1011')

    assert response.status_code == 308
    assert response.headers['Location'].endswith('/routes?page=3&matched=unmatched_osm&osm_variant=1011')
    assert calls[0]['matched_filter'] == 'unmatched_osm'
    assert calls[0]['per_page'] == route_pages.ROUTES_DEFAULT_PER_PAGE

    response = client.get('/routes?page=3&matched=unmatched_osm&osm_variant=1011')
    assert response.status_code == 200
    assert fake_listing['page'] == 3


def test_a_missing_variant_keeps_the_requested_page(client, monkeypatch, fake_listing):
    monkeypatch.setattr(route_listing, 'locate_route_variant_page', lambda **kwargs: None)

    response = client.get('/routes?page=2&osm_variant=999')

    assert response.status_code == 200
    assert fake_listing['page'] == 2


def test_variant_parameters_use_the_canonical_encoding(client, monkeypatch, fake_listing):
    monkeypatch.setattr(route_listing, 'locate_route_variant_page', lambda **kwargs: None)

    response = client.get('/routes?gtfs_variant=91-1-Z-j26-1:0:Zürich HB&utm=x')

    assert response.status_code == 308
    # static/js/shared/permalinks.js writes the same text (encodeParams(..., ',')).
    assert response.headers['Location'].endswith('/routes?gtfs_variant=91-1-Z-j26-1%3A0%3AZ%C3%BCrich+HB')

    non_gtfs = client.get('/routes/non-gtfs?osm_variant=1012&gtfs_variant=x')
    assert non_gtfs.status_code == 308
    assert non_gtfs.headers['Location'].endswith('/routes/non-gtfs?osm_variant=1012')


def test_the_gtfs_map_keeps_readable_stop_parameters(client, monkeypatch):

    redirected = client.get('/routes/gtfs-stop-id-sloid?sloid=ch%3A1%3Asloid%3A7&other=1')
    assert redirected.status_code == 308
    assert redirected.headers['Location'].endswith('/routes/gtfs-stop-id-sloid?sloid=ch:1:sloid:7')

    assert client.get('/routes/gtfs-stop-id-sloid?gtfs_stop_id=8507000:0:1').status_code == 200
    assert client.get('/routes/gtfs-stop-id-sloid?sloid=ch:1:sloid:7').status_code == 200


def test_variant_panels_carry_stable_ids_and_a_copy_link(app):
    group = route_listing._build_direction_group(
        Itinerary(id=7, source='gtfs', source_itinerary_id=MATCHED_ATLAS, direction_id='0'),
        Itinerary(id=8, source='osm', source_itinerary_id='2169538', direction_id='0'),
        [], [],
    )
    assert group['gtfs_source_itinerary_id'] == MATCHED_ATLAS
    assert group['osm_relation_id'] == '2169538'

    route = {
        'display_mode': 'matched', 'is_matched': True, 'match_label': 'Matched',
        'osm_route_display_id': 'Z', 'variant_count': 1, 'gtfs_variant_count': 1,
        'osm_variant_count': 1, 'matched_variant_count': 1, 'direction_groups': [group],
        'map_filter': None,
    }
    with app.test_request_context('/routes'):
        rendered = render_template(
            'pages/routes.html',
            active_view='routes',
            listing_endpoint='routes.routes_page',
            route_rows=[route],
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

    assert f'data-gtfs-variant="{MATCHED_ATLAS}"' in rendered
    assert 'data-osm-variant="2169538"' in rendered
    assert 'class="route-copy-link"' in rendered
    assert 'js/shared/permalinks.js' in rendered
