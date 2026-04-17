import re


def _extract_h1(html: str) -> str:
    match = re.search(r"<h1>(.*?)</h1>", html, flags=re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def test_routes_page_defaults_to_matched_tab(client):
    response = client.get('/routes')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert _extract_h1(html) == 'Matched Routes'
    assert 'No matched routes to display' in html
    assert 'tab=atlas' in html
    assert 'tab=osm' in html


def test_routes_page_invalid_tab_falls_back_to_matched(client):
    response = client.get('/routes?tab=unknown')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert _extract_h1(html) == 'Matched Routes'
    assert 'No matched routes to display' in html


def test_routes_page_atlas_tab_renders_atlas_view(client):
    response = client.get('/routes?tab=atlas')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert _extract_h1(html) == 'ATLAS Routes'
    assert 'No ATLAS routes to display' in html


def test_routes_page_osm_tab_renders_osm_view(client):
    response = client.get('/routes?tab=osm')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert _extract_h1(html) == 'OSM Routes'
    assert 'No OSM routes to display' in html
