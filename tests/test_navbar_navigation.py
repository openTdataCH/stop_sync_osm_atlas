import re


def test_navbar_groups_secondary_routes_and_moves_mobile_version(client):
    response = client.get('/routes/gtfs-stop-id-sloid')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'aria-label="Show Routes pages"' in html
    assert 'aria-controls="routesNavbarMenu"' in html
    assert 'aria-label="Routes pages"' in html
    assert 'fas fa-chevron-down navbar-section__chevron' in html
    assert re.search(
        r'aria-controls="routesNavbarMenu"[\s\S]*?'
        r'</button>\s*<ul id="routesNavbarMenu"',
        html,
    )
    assert 'nav-link dropdown-toggle navbar-section__toggle' not in html
    assert re.search(
        r'class="dropdown-item active"[^>]*aria-current="page"[^>]*>'
        r'GTFS stop_id <span aria-hidden="true">↔</span> SLOID',
        html,
    )
    assert 'class="navbar-version navbar-version--brand"' in html
    assert 'class="nav-item navbar-mobile-version d-lg-none"' in html
    assert html.index('>Docs</a>') < html.index('navbar-mobile-version') < html.index('navbarDataUpdated')
    assert 'c-page-tabs' not in html


def test_navbar_groups_export_under_data_without_page_tabs(client):
    response = client.get('/data/export')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'aria-label="Show Data pages"' in html
    assert 'aria-controls="dataNavbarMenu"' in html
    assert 'aria-label="Data pages"' in html
    assert re.search(
        r'aria-controls="dataNavbarMenu"[\s\S]*?'
        r'</button>\s*<ul id="dataNavbarMenu"',
        html,
    )
    assert re.search(
        r'class="dropdown-item active"[^>]*aria-current="page"[^>]*>Export data</a>',
        html,
    )
    assert 'c-page-tabs' not in html
