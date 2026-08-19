def test_routes_subpages_use_page_tabs_and_keep_mobile_version(client):
    response = client.get('/routes/gtfs-stop-id-sloid')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<nav class="c-page-tabs" aria-label="Routes pages" style="--page-tabs-count: 3">' in html
    assert html.count('c-page-tabs__tab') == 3
    assert 'SLOID <span aria-hidden="true">↔</span> GTFS stop_id' in html
    assert 'c-page-tabs__tab is-active' in html
    assert 'aria-current="page"' in html
    assert 'navbar-section__toggle' not in html
    assert 'routesNavbarMenu' not in html
    assert 'class="navbar-version navbar-version--brand"' in html
    assert 'class="nav-item navbar-mobile-version d-lg-none"' in html
    assert html.index('>Docs</a>') < html.index('navbar-mobile-version') < html.index('navbarDataUpdated')


def test_data_subpages_use_page_tabs_without_navbar_dropdown(client):
    response = client.get('/data/export')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<nav class="c-page-tabs" aria-label="Data pages" style="--page-tabs-count: 2">' in html
    assert html.count('c-page-tabs__tab') == 2
    assert 'c-page-tabs__tab is-active' in html
    assert 'aria-current="page"' in html
    assert 'navbar-section__toggle' not in html
    assert 'dataNavbarMenu' not in html
