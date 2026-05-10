import re

from backend.blueprints import operators as operators_module


class _DummyPagination:
    def __init__(self, page=1, per_page=20, total=1):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = 1 if total else 0
        self.has_prev = False
        self.has_next = False
        self.prev_num = 1
        self.next_num = 1

    def iter_pages(self, **_kwargs):
        return [1] if self.total else []


def test_operators_page_renders_operator_cards(client, monkeypatch):
    monkeypatch.setattr(
        operators_module,
        '_load_operators_view',
        lambda **_kwargs: (
            [{
                'atlas_business_org_abbr': 'SBB',
                'atlas_business_org_name': 'Schweizerische Bundesbahnen SBB',
                'sboid': '11',
                'atlas_stop_count': 12,
                'matched_stop_count': 9,
                'unmatched_atlas_stop_count': 3,
                'missing_osm_operator_count': 1,
                'osm_operator_count': 2,
                'has_osm_matches': True,
                'has_matched_stops': True,
                'osm_operators': [
                    {'osm_operator': 'SBB', 'matched_stop_count': 7},
                    {'osm_operator': 'BLS', 'matched_stop_count': 2},
                ],
            }],
            _DummyPagination(total=1),
        ),
    )

    response = client.get('/data/operators')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Schweizerische Bundesbahnen SBB' in html
    assert 'Abbr: SBB' in html
    assert 'SBOID: 11' in html
    assert 'BLS' in html
    assert 'matched osm operators' in html.lower()
    assert 'href="/data/operators"' in html
    assert 'href="/data/analytics"' in html
    assert 'href="/data/export"' in html
    assert re.search(r'class="nav-link[^\"]* active[^\"]*" href="/data"', html)
    assert re.search(r'class="c-page-tabs__tab is-active"[^>]*>\s*Operators\s*</a>', html)


def test_operators_page_forwards_filters_to_loader(client, monkeypatch):
    captured = {}

    def _fake_loader(**kwargs):
        captured.update(kwargs)
        return [], _DummyPagination(page=kwargs['page'], per_page=kwargs['per_page'], total=0)

    monkeypatch.setattr(operators_module, '_load_operators_view', _fake_loader)

    response = client.get('/data/operators?q=SBB&coverage=no_osm_matches&per_page=50&page=2')

    assert response.status_code == 200
    assert captured == {
        'coverage_filter': 'no_osm_matches',
        'q': 'SBB',
        'page': 2,
        'per_page': 50,
    }


def test_data_root_redirects_to_analytics(client):
    response = client.get('/data')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/data/analytics')