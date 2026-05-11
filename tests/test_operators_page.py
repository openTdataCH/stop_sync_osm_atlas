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


def test_operators_page_forwards_filters_to_loader(client, monkeypatch):
    captured = {}

    def _fake_loader(**kwargs):
        captured.update(kwargs)
        return [], _DummyPagination(page=kwargs['page'], per_page=kwargs['per_page'], total=0)

    monkeypatch.setattr(operators_module, '_load_operators_view', _fake_loader)

    response = client.get('/operators?q=SBB&coverage=no_osm_matches&per_page=50&page=2')

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