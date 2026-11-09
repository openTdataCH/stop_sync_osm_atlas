"""JSON responses are gzipped for clients that accept it."""

import gzip
import json

import pytest
from flask import jsonify

STOPS = {'stops': [{'id': index, 'sloid': f'ch:1:sloid:{index}'} for index in range(100)]}


@pytest.fixture
def client(app):
    app.add_url_rule('/test/stops', 'test_stops', lambda: jsonify(STOPS))
    app.add_url_rule('/test/small', 'test_small', lambda: jsonify(ok=True))
    app.add_url_rule('/test/page', 'test_page', lambda: '<p>stop</p>' * 500)
    return app.test_client()


def test_gzips_json_for_a_client_that_accepts_it(client):
    response = client.get('/test/stops', headers={'Accept-Encoding': 'gzip, deflate, br'})

    assert response.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in response.vary
    assert response.content_length == len(response.data)
    assert json.loads(gzip.decompress(response.data)) == STOPS


@pytest.mark.parametrize('accept_encoding', [None, 'identity', 'gzip;q=0'])
def test_sends_plain_json_to_a_client_that_does_not(client, accept_encoding):
    headers = {'Accept-Encoding': accept_encoding} if accept_encoding else {}
    response = client.get('/test/stops', headers=headers)

    assert 'Content-Encoding' not in response.headers
    # A cache must not hand this copy to a client that accepts gzip, or the reverse.
    assert 'Accept-Encoding' in response.vary
    assert response.get_json() == STOPS


def test_leaves_small_json_and_other_types_alone(client):
    for path in ('/test/small', '/test/page'):
        response = client.get(path, headers={'Accept-Encoding': 'gzip'})

        assert 'Content-Encoding' not in response.headers
        assert 'Accept-Encoding' not in response.vary
