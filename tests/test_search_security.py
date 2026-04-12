from backend.blueprints import search as search_module


def test_search_empty_query_returns_empty_results(client):
    response = client.get('/api/search')

    assert response.status_code == 200
    assert response.get_json() == {"osm": [], "atlas": []}


def test_search_short_query_returns_empty_results_without_db_query(client):
    response = client.get('/api/search?q=ab')

    assert response.status_code == 200
    assert response.get_json() == {"osm": [], "atlas": []}


def test_search_long_query_is_rejected(client):
    too_long_query = 'a' * (search_module.SEARCH_MAX_QUERY_LENGTH + 1)

    response = client.get(f'/api/search?q={too_long_query}')

    assert response.status_code == 400
    payload = response.get_json()
    assert "error" in payload
    assert str(search_module.SEARCH_MAX_QUERY_LENGTH) in payload["error"]


def test_escape_like_literal_escapes_wildcards_and_escape_char():
    escaped = search_module._escape_like_literal(r"a%b_c\z")

    assert escaped == r"a\%b\_c\\z"
