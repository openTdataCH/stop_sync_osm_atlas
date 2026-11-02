import re

import pytest

from backend.blueprints import operators as operators_module
from backend.models import AtlasStop, OsmNode, StopsMatched


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


@pytest.mark.parametrize(('matched', 'values', 'missing', 'expected'), [
    (0, 0, 0, ('no-matches', 'No matched stops')),
    (5, 0, 5, ('untagged', 'Not tagged')),
    (5, 2, 1, ('mixed', '2 different values')),
    (5, 1, 2, ('partial', 'Partly tagged')),
    (5, 1, 0, ('consistent', 'Consistent')),
])
def test_operator_tag_status(matched, values, missing, expected):
    assert operators_module._operator_tag_status(matched, values, missing) == expected


def test_operator_card_breaks_down_matched_stops_by_operator_value(client, monkeypatch):
    operator = operators_module._build_operator_row(
        type('Operator', (), {'atlas_business_org_abbr': 'ASM', 'atlas_business_org_name': 'Aare Seeland mobil', 'sboid': 'ch:1:sboid:100020'})(),
        {'ASM': 38},
        {'ASM': {'matched_atlas_stop_count': 32, 'matched_osm_stop_count': 32, 'missing_osm_operator_count': 15, 'missing_osm_operator_wikidata_count': 32}},
        {'ASM': [
            {'osm_operator': 'asm', 'matched_stop_count': 16},
            {'osm_operator': 'aare seeland mobil', 'matched_stop_count': 1},
        ]},
        {},
        True,
    )
    monkeypatch.setattr(operators_module, '_load_operators_view', lambda **kwargs: ([operator], _DummyPagination(), True))

    response = client.get('/operators')

    assert response.status_code == 200
    assert '2 different values' in response.text
    assert re.findall(r'class="operator-breakdown__segment [^"]+" style="flex-grow: (\d+);', response.text) == ['16', '1', '15']
    # Two values keep the two greens furthest apart, in the bar and in the list swatches.
    assert re.findall(r'--operator-value-shade: (\d+)%', response.text) == ['100', '0', '100', '0']
    assert response.text.count('operator-breakdown__row--missing') == 2


def test_match_counts_count_each_atlas_and_osm_stop_once(sqlite_tables):
    session = sqlite_tables(AtlasStop, StopsMatched, OsmNode)
    session.add_all([AtlasStop(sloid=sloid, atlas_business_org_abbr='EX') for sloid in ('s1', 's2')])
    # s1 matches two OSM stops; OSM stop "b" matches both ATLAS stops.
    session.add_all([StopsMatched(id=id_, sloid=sloid, osm_node_id=node, stop_type='matched')
                     for id_, sloid, node in ((1, 's1', 'a'), (2, 's1', 'b'), (3, 's2', 'b'), (4, 's2', 'c'))])
    session.add_all([OsmNode(osm_node_id='a', osm_operator='Example', osm_operator_wikidata='Q1'),
                     OsmNode(osm_node_id='b', osm_operator='Example'),
                     OsmNode(osm_node_id='c', osm_operator='')])
    session.commit()

    counts = operators_module._load_match_counts(['EX'], True)
    values = operators_module._load_osm_operators(['EX'])

    assert counts == {'EX': {
        'matched_atlas_stop_count': 2,
        'matched_osm_stop_count': 3,
        'missing_osm_operator_count': 1,
        'missing_osm_operator_wikidata_count': 2,
    }}
    assert values == {'EX': [{'osm_operator': 'Example', 'matched_stop_count': 2}]}
