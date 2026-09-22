import html
import re
import sqlite3

import pytest
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from backend.extensions import db

from backend.app import app as backend_app
from backend.blueprints import operators as operators_module
from backend.models import StopsMatched
from backend.queries.helpers import parse_filter_params
from backend.query_builder import QueryBuilder
from tests.test_operators_page import _DummyPagination


def test_wikidata_filter_selects_exact_values_and_combines_with_osm_operator():
    filters = parse_filter_params({
        'osm_operator_wikidata': ' Q1, ,Q2 ', 'osm_operator': 'Example',
    })
    assert filters['osm_operator_wikidata'] == ['Q1', 'Q2']
    with backend_app.app_context():
        query = QueryBuilder(None).apply_common_filters(
            StopsMatched.query.with_entities(StopsMatched.id), filters,
        )
        sql = str(query.statement.compile(compile_kwargs={'literal_binds': True}))
    with sqlite3.connect(':memory:') as connection:
        connection.executescript('''
            CREATE TABLE stops_matched (id INTEGER, osm_node_id TEXT);
            CREATE TABLE osm_nodes (osm_node_id TEXT, osm_operator TEXT, osm_operator_wikidata TEXT);
            INSERT INTO stops_matched VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, 'd'), (5, NULL), (6, 'e');
            INSERT INTO osm_nodes VALUES ('a', 'Example', 'Q1'), ('b', 'Example', 'Q2'),
                ('c', 'Other', 'Q1'), ('d', 'Example', 'Q10'), ('e', 'Example', NULL);
        ''')
        assert connection.execute(sql).fetchall() == [(1,), (2,)]


def test_operator_cards_link_to_matching_map_filters(client, monkeypatch):
    operator = operators_module._build_operator_row(
        type('Operator', (), {'atlas_business_org_abbr': 'EX', 'atlas_business_org_name': 'Example', 'sboid': None})(),
        {'EX': 3}, {'EX': {'matched_stop_count': 3, 'missing_osm_operator_wikidata_count': 2}},
        {'EX': [{'osm_operator': 'Example & Co', 'matched_stop_count': 3}]},
        {'EX': [{'osm_operator_wikidata': 'Q1', 'matched_stop_count': 3}]}, True,
    )
    monkeypatch.setattr(operators_module, '_load_operators_view', lambda **kwargs: ([operator], _DummyPagination(), True))
    response = client.get('/operators')
    assert response.status_code == 200
    links = re.findall(r'class="operator-node__map-link" href="([^"]+)"', response.text)
    assert [parse_qs(urlparse(html.unescape(link)).query) for link in links] == [
        {'osm_operator': ['Example & Co']}, {'osm_operator_wikidata': ['Q1']},
    ]
    assert 'https://www.wikidata.org/wiki/Q1' in response.text
    missing_link = re.search(r'class="operator-card__coverage-link" href="([^"]+)"', response.text)
    assert parse_qs(urlparse(html.unescape(missing_link.group(1))).query) == {
        'atlas_operator': ['EX'], 'missing_osm_operator_wikidata': ['true'],
    }


def test_wikidata_options_are_distinct_sorted_and_nonempty(app, client):
    with app.app_context():
        db.session.execute(text('CREATE TABLE osm_nodes (osm_operator_wikidata TEXT)'))
        db.session.execute(text("INSERT INTO osm_nodes VALUES ('Q2'), ('Q1'), ('Q2'), (NULL), ('')"))
        db.session.commit()
    response = client.get('/api/osm_operator_wikidata')
    assert response.status_code == 200
    assert response.json == {'operators': ['Q1', 'Q2'], 'total': 2}


def test_wikidata_options_tolerate_uninitialized_database(client):
    response = client.get('/api/osm_operator_wikidata')
    assert response.status_code == 200
    assert response.json == {'operators': [], 'total': 0}


@pytest.mark.parametrize(('operator_filter', 'expected'), [
    ({'atlas_operator': 'EX'}, [(1,), (2,)]),
    ({'osm_operator': 'Example'}, [(1,), (2,), (6,)]),
])
def test_missing_wikidata_combines_with_operator_and_excludes_source_only_stops(operator_filter, expected):
    filters = parse_filter_params({'missing_osm_operator_wikidata': 'true', **operator_filter})
    with backend_app.app_context():
        query = QueryBuilder(None).apply_common_filters(
            StopsMatched.query.with_entities(StopsMatched.id), filters,
        )
        sql = str(query.statement.compile(compile_kwargs={'literal_binds': True}))
    with sqlite3.connect(':memory:') as connection:
        connection.executescript("""
            CREATE TABLE stops_matched (id INTEGER, osm_node_id TEXT, sloid TEXT);
            CREATE TABLE osm_nodes (osm_node_id TEXT, osm_operator TEXT, osm_operator_wikidata TEXT);
            CREATE TABLE atlas_stops (sloid TEXT, atlas_business_org_abbr TEXT);
            INSERT INTO stops_matched VALUES (1, 'a', 's1'), (2, 'b', 's2'), (3, 'c', 's3'),
                (4, 'd', 's4'), (5, NULL, 's5'), (6, 'e', NULL);
            INSERT INTO osm_nodes VALUES ('a', 'Example', NULL), ('b', 'Example', ''),
                ('c', 'Example', 'Q1'), ('d', 'Other', NULL), ('e', 'Example', '');
            INSERT INTO atlas_stops VALUES ('s1', 'EX'), ('s2', 'EX'), ('s3', 'EX'),
                ('s4', 'OTHER'), ('s5', 'EX');
        """)
        assert connection.execute(sql).fetchall() == expected


def test_missing_wikidata_false_does_not_activate_filter():
    assert 'missing_osm_operator_wikidata' not in parse_filter_params({'missing_osm_operator_wikidata': 'false'})
