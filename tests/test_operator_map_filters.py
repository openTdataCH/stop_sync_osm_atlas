import html
import re

import pytest
from urllib.parse import parse_qs, urlparse

from backend.blueprints import operators as operators_module
from backend.models import AtlasStop, OsmNode, StopsMatched
from backend.queries.helpers import parse_filter_params
from backend.query_builder import QueryBuilder
from tests.test_operators_page import _DummyPagination


def _matching_stop_ids(filters):
    query = QueryBuilder(None).apply_common_filters(StopsMatched.query.with_entities(StopsMatched.id), filters)
    return sorted(stop_id for (stop_id,) in query.all())


def test_wikidata_filter_selects_exact_values_and_combines_with_osm_operator(sqlite_tables):
    filters = parse_filter_params({
        'osm_operator_wikidata': ' Q1, ,Q2 ', 'osm_operator': 'Example',
    })
    assert filters['osm_operator_wikidata'] == ['Q1', 'Q2']
    session = sqlite_tables(StopsMatched, OsmNode)
    session.add_all([StopsMatched(id=id_, osm_node_id=node)
                     for id_, node in ((1, 'a'), (2, 'b'), (3, 'c'), (4, 'd'), (5, None), (6, 'e'))])
    session.add_all([OsmNode(osm_node_id=node, osm_operator=operator, osm_operator_wikidata=wikidata)
                     for node, operator, wikidata in (('a', 'Example', 'Q1'), ('b', 'Example', 'Q2'),
                                                      ('c', 'Other', 'Q1'), ('d', 'Example', 'Q10'),
                                                      ('e', 'Example', None))])
    session.commit()
    assert _matching_stop_ids(filters) == [1, 2]


def test_operator_cards_link_to_matching_map_filters(client, monkeypatch):
    operator = operators_module._build_operator_row(
        type('Operator', (), {'atlas_business_org_abbr': 'EX', 'atlas_business_org_name': 'Example', 'sboid': None})(),
        {'EX': 3}, {'EX': {'matched_atlas_stop_count': 3, 'matched_osm_stop_count': 3, 'missing_osm_operator_wikidata_count': 2}},
        {'EX': [{'osm_operator': 'Example & Co', 'matched_stop_count': 3}]},
        {'EX': [{'osm_operator_wikidata': 'Q1', 'matched_stop_count': 3}]}, True,
    )
    monkeypatch.setattr(operators_module, '_load_operators_view', lambda **kwargs: ([operator], _DummyPagination(), True))
    response = client.get('/operators')
    assert response.status_code == 200
    links = re.findall(r'class="operator-breakdown__map-link" href="([^"]+)"', response.text)
    assert [parse_qs(urlparse(html.unescape(link)).query) for link in links] == [
        {'osm_operator': ['Example & Co']}, {'osm_operator_wikidata': ['Q1']},
        {'atlas_operator': ['EX'], 'missing_osm_operator_wikidata': ['true']},
    ]
    assert 'https://www.wikidata.org/wiki/Q1' in response.text


def test_wikidata_options_are_distinct_sorted_and_nonempty(sqlite_tables, client):
    session = sqlite_tables(OsmNode)
    session.add_all([OsmNode(osm_node_id=str(index), osm_operator_wikidata=value)
                     for index, value in enumerate(('Q2', 'Q1', 'Q2', None, ''))])
    session.commit()
    response = client.get('/api/osm_operator_wikidata')
    assert response.status_code == 200
    assert response.json == {'operators': ['Q1', 'Q2'], 'total': 2}


def test_wikidata_options_tolerate_uninitialized_database(client):
    response = client.get('/api/osm_operator_wikidata')
    assert response.status_code == 200
    assert response.json == {'operators': [], 'total': 0}


@pytest.mark.parametrize(('operator_filter', 'expected'), [
    ({'atlas_operator': 'EX'}, [1, 2]),
    ({'osm_operator': 'Example'}, [1, 2, 6]),
])
def test_missing_wikidata_combines_with_operator_and_excludes_source_only_stops(sqlite_tables, operator_filter, expected):
    filters = parse_filter_params({'missing_osm_operator_wikidata': 'true', **operator_filter})
    session = sqlite_tables(StopsMatched, OsmNode, AtlasStop)
    session.add_all([StopsMatched(id=id_, osm_node_id=node, sloid=sloid)
                     for id_, node, sloid in ((1, 'a', 's1'), (2, 'b', 's2'), (3, 'c', 's3'),
                                              (4, 'd', 's4'), (5, None, 's5'), (6, 'e', None))])
    session.add_all([OsmNode(osm_node_id=node, osm_operator=operator, osm_operator_wikidata=wikidata)
                     for node, operator, wikidata in (('a', 'Example', None), ('b', 'Example', ''),
                                                      ('c', 'Example', 'Q1'), ('d', 'Other', None),
                                                      ('e', 'Example', ''))])
    session.add_all([AtlasStop(sloid=sloid, atlas_business_org_abbr=operator)
                     for sloid, operator in (('s1', 'EX'), ('s2', 'EX'), ('s3', 'EX'), ('s4', 'OTHER'), ('s5', 'EX'))])
    session.commit()
    assert _matching_stop_ids(filters) == expected


def test_missing_wikidata_false_does_not_activate_filter():
    assert 'missing_osm_operator_wikidata' not in parse_filter_params({'missing_osm_operator_wikidata': 'false'})
