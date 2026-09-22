import json
from types import SimpleNamespace

import pytest

from backend.blueprints import routes as routes_module
from backend.extensions import db
from backend.models import Itinerary, ItineraryMatch, LineFamily, StopCall
from backend.services.route_comparison import (
    _identity,
    _identity_index,
    _matching_positions,
    _ordered_match_count,
    compare_stop_calls,
)


def _call(sequence, identity=None, *, uic=None, variants=None, source_stop_id=None):
    return SimpleNamespace(
        id=sequence, stop_sequence=sequence, source_sloid=identity,
        source_sloid_variants=json.dumps(variants) if variants is not None else None,
        source_stop_id=source_stop_id, source_node_id=f'node-{sequence}',
        uic_ref=uic, stop_label=f'Stop {sequence}', stop_lat=47.0, stop_lon=8.0,
    )


def _compare(atlas, osm, atlas_direction='0', osm_direction='0'):
    return compare_stop_calls(
        atlas, osm, SimpleNamespace(direction_id=atlas_direction),
        SimpleNamespace(direction_id=osm_direction),
    )


def test_alignment_preserves_order_gaps_and_every_stop_occurrence():
    atlas = [_call(index, name) for index, name in enumerate(['A', 'B', 'C', 'D'], 1)]
    osm = [_call(index, name) for index, name in enumerate(['A', 'X', 'C', 'D', 'Y'], 1)]
    result = _compare(atlas, osm)

    assert result['matched_stop_count'] == 3
    assert result['stop_ratio'] == 0.6
    assert result['percentage'] == 60
    assert [row['atlas']['id'] for row in result['rows'] if row['atlas']] == [1, 2, 3, 4]
    assert [row['osm']['id'] for row in result['rows'] if row['osm']] == [1, 2, 3, 4, 5]
    assert sum(row['match_type'] is not None for row in result['rows']) == 3
    assert all(row['match_type'] is not None for row in result['rows'] if row['atlas'] and row['osm'])


def test_reversed_order_does_not_count_every_shared_stop():
    result = _compare([_call(1, 'A'), _call(2, 'B'), _call(3, 'C')],
                      [_call(1, 'C'), _call(2, 'B'), _call(3, 'A')])
    assert result['matched_stop_count'] == 1
    assert result['percentage'] == 33.3


def test_repeated_visits_are_matched_one_to_one_in_order():
    result = _compare([_call(1, 'A'), _call(2, 'B'), _call(3, 'A')],
                      [_call(1, 'A'), _call(2, 'A')])
    assert result['matched_stop_count'] == 2
    assert [row['atlas']['id'] for row in result['rows'] if row['match_type']] == [1, 3]
    assert result['percentage'] == 66.7


@pytest.mark.parametrize(('atlas', 'osm', 'expected_type'), [
    (_call(1, 'A', uic='1'), _call(1, 'B', uic='1'), None),
    (_call(1, 'A', uic='1', variants=['B']), _call(1, 'B', uic='2'), 'resolved_sloid_match'),
    (_call(1, 'A', uic='1'), _call(1, uic='1'), 'uic_match'),
    (_call(1, uic='1'), _call(1, 'B', uic='1'), 'uic_match'),
    (_call(1, uic='1'), _call(1, uic='1'), 'uic_match'),
    (_call(1, source_stop_id='opaque'), _call(1, source_stop_id='opaque'), None),
    (_call(1), _call(1), None),
])
def test_only_resolved_identity_or_nonconflicting_uic_can_match(atlas, osm, expected_type):
    result = _compare([atlas], [osm])
    assert result['matched_stop_count'] == int(expected_type is not None)
    assert [row['match_type'] for row in result['rows'] if row['match_type']] == (
        [expected_type] if expected_type else []
    )


def test_opaque_source_id_is_displayed_without_becoming_match_identity():
    call = _call(1, source_stop_id='feed:stop/opaque')
    call.canonical_stop_key = 'feed:stop/opaque'
    result = _compare([call], [_call(1, 'feed:stop/opaque')])
    assert result['matched_stop_count'] == 0
    atlas_stop = next(row['atlas'] for row in result['rows'] if row['atlas'])
    assert atlas_stop['stop_ids'] == ['feed:stop/opaque']


@pytest.mark.parametrize('variants', ['not-json', '"A"', '{"A": true}'])
def test_invalid_variants_do_not_establish_resolved_identity(variants):
    call = _call(1, uic='station')
    call.source_sloid_variants = variants
    result = _compare([call], [_call(1, 'B', uic='station')])
    assert result['rows'][0]['match_type'] == 'uic_match'


@pytest.mark.parametrize(('atlas_direction', 'osm_direction', 'status'), [
    ('0', '0', 'match'), ('0', '1', 'conflict'), (None, '0', 'unknown'), (' ', None, 'unknown'),
])
def test_direction_status_does_not_hide_stop_agreement(atlas_direction, osm_direction, status):
    result = _compare([_call(1, 'A')], [_call(1, 'A')], atlas_direction, osm_direction)
    assert result['direction_status'] == status
    assert result['percentage'] == 100


def test_empty_sequences_and_single_selection_have_no_misleading_percentage():
    assert _compare([], [])['percentage'] is None
    assert _compare([], [_call(1, 'A')])['percentage'] == 0
    result = compare_stop_calls([_call(1, 'A')], [], SimpleNamespace(direction_id='0'))
    assert result['percentage'] is None
    assert result['stop_ratio'] is None
    assert result['atlas_stop_count'] == 1
    assert result['osm_stop_count'] == 0
    assert result['rows'][0]['osm'] is None


@pytest.fixture
def comparison_db(app, monkeypatch):
    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': False})
    with app.app_context():
        for model in (LineFamily, Itinerary, StopCall, ItineraryMatch):
            model.__table__.create(db.engine)
        db.session.add_all([
            LineFamily(id=1, source='atlas', source_family_id='atlas-north', display_route_id='A',
                       public_name='North line', operator='Metro North'),
            LineFamily(id=2, source='osm', source_family_id='osm-north', display_route_id='A',
                       public_name='OSM North', operator='Metro North', ref='S1'),
            LineFamily(id=3, source='atlas', source_family_id='atlas-south', display_route_id='Z',
                       public_name='South line'),
            LineFamily(id=4, source='osm', source_family_id='osm-south', display_route_id='Z',
                       public_name='OSM South'),
            LineFamily(id=5, source='osm', source_family_id='non-gtfs', display_route_id='B',
                       is_non_gtfs=True),
        ])
        for source, offset, family_id in [('atlas', 100, 1), ('osm', 200, 2)]:
            for index in range(1, 5):
                db.session.add(Itinerary(
                    id=offset + index, source=source, line_family_id=family_id if index < 4 else family_id + 2,
                    source_itinerary_id=f'{source}-{index}', display_name=f'Variant {index}', direction_id='0',
                ))
        db.session.add(Itinerary(id=299, source='osm', line_family_id=5, source_itinerary_id='excluded'))
        db.session.add(ItineraryMatch(id=1, atlas_itinerary_id=101, osm_itinerary_id=201))
        for itinerary_id, identities in [(101, ['A']), (201, ['A']), (102, ['A', 'B', 'C']),
                                         (202, ['A', 'C'])]:
            for sequence, identity in enumerate(identities, 1):
                db.session.add(StopCall(
                    itinerary_id=itinerary_id, stop_sequence=sequence, source_sloid=identity,
                    source_node_id=str(sequence) if itinerary_id > 200 else None,
                    stop_label=f'Stop {identity}', stop_lat=47.0, stop_lon=8.0,
                ))
        db.session.commit()
    return app.test_client()


def test_api_compares_arbitrary_unmatched_pair(comparison_db):
    response = comparison_db.get('/api/routes/comparison?atlas_itinerary_id=102&osm_itinerary_id=202')
    assert response.status_code == 200
    result = response.json
    assert result['atlas'] == {
        'id': 102, 'family_id': 1, 'route_name': 'North line', 'route_id': 'A',
        'display_name': 'Variant 2', 'direction_id': '0', 'is_matched': False,
    }
    assert result['osm']['id'] == 202
    assert result['matched_stop_count'] == 2
    assert result['atlas_stop_count'] == 3
    assert result['osm_stop_count'] == 2
    assert result['percentage'] == 66.7
    assert result['is_saved_match'] is False
    assert result['rows'][1]['osm'] is None


def test_api_distinguishes_saved_match_from_preview_and_supports_one_side(comparison_db):
    saved = comparison_db.get('/api/routes/comparison?atlas_itinerary_id=101&osm_itinerary_id=201').json
    preview = comparison_db.get('/api/routes/comparison?atlas_itinerary_id=101&osm_itinerary_id=202').json
    one_side = comparison_db.get('/api/routes/comparison?osm_itinerary_id=202').json
    assert saved['is_saved_match'] is True
    assert saved['atlas']['is_matched'] is True
    assert preview['is_saved_match'] is False
    assert preview['atlas']['is_matched'] is True
    assert one_side['atlas'] is None
    assert one_side['percentage'] is None
    assert len(one_side['rows']) == 2
    assert all(row['atlas'] is None for row in one_side['rows'])


def test_options_filter_by_itinerary_and_page_in_sql(comparison_db):
    first = comparison_db.get('/api/routes/comparison/options?source=atlas&per_page=2').json
    second = comparison_db.get('/api/routes/comparison/options?source=atlas&per_page=2&page=2').json
    assert [item['id'] for item in first['items']] == [102, 103]
    assert [item['id'] for item in second['items']] == [104]
    assert (first['page'], first['pages'], first['total']) == (1, 2, 3)
    osm = comparison_db.get('/api/routes/comparison/options?source=osm&unmatched=0').json
    assert [item['id'] for item in osm['items']] == [201, 202, 203, 204]
    assert osm['items'][0]['is_matched'] is True


def test_options_anchor_positions_page_but_does_not_override_search(comparison_db):
    anchored = comparison_db.get('/api/routes/comparison/options?source=atlas&per_page=1&anchor_id=104').json
    assert anchored['page'] == 3
    assert anchored['items'][0]['id'] == 104
    searched = comparison_db.get(
        '/api/routes/comparison/options?source=atlas&per_page=1&anchor_id=104&q=North',
    ).json
    assert searched['page'] == 1
    assert searched['items'][0]['id'] == 102


@pytest.mark.parametrize(('source', 'search', 'expected_ids'), [
    ('atlas', 'atlas-south', [104]), ('osm', 'S1', [202, 203]),
    ('atlas', 'metro north', [102, 103]), ('atlas', 'Variant 3', [103]),
    ('osm', 'osm-4', [204]), ('osm', '%', []),
])
def test_options_search_source_family_ref_operator_and_variant(comparison_db, source, search, expected_ids):
    result = comparison_db.get('/api/routes/comparison/options', query_string={
        'source': source, 'q': search,
    }).json
    assert [item['id'] for item in result['items']] == expected_ids


@pytest.mark.parametrize('query', ['', 'atlas_itinerary_id=0', 'osm_itinerary_id=nope',
                                  'atlas_itinerary_id=-1', 'osm_itinerary_id=999999999999999999999'])
def test_comparison_rejects_invalid_ids(comparison_db, query):
    assert comparison_db.get(f'/api/routes/comparison?{query}').status_code == 400


@pytest.mark.parametrize('query', ['atlas_itinerary_id=201', 'osm_itinerary_id=101',
                                  'osm_itinerary_id=9999', 'osm_itinerary_id=299'])
def test_comparison_rejects_wrong_source_missing_or_excluded_itinerary(comparison_db, query):
    assert comparison_db.get(f'/api/routes/comparison?{query}').status_code == 404


@pytest.mark.parametrize('query', ['', 'source=bad', 'source=atlas&page=0', 'source=atlas&page=bad',
                                  'source=atlas&per_page=101', 'source=atlas&unmatched=yes',
                                  'source=atlas&anchor_id=-1', 'source=atlas&q=' + 'x' * 256])
def test_options_reject_invalid_query(comparison_db, query):
    assert comparison_db.get(f'/api/routes/comparison/options?{query}').status_code == 400


def test_comparison_missing_tables_returns_controlled_retry_response(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': False})
    response = client.get('/api/routes/comparison?atlas_itinerary_id=1')
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '30'
    assert 'not initialized' in response.json['error']


def test_comparison_database_timeout_returns_controlled_retry_response(client, monkeypatch):
    class LockTimeout(Exception):
        sqlstate = '55P03'

    def fail(*_args, **_kwargs):
        raise LockTimeout()

    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': False})
    monkeypatch.setattr(routes_module, 'list_comparison_options', fail)
    response = client.get('/api/routes/comparison/options?source=atlas')
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '30'


def test_comparison_maintenance_guard_runs_before_query(client, monkeypatch):
    monkeypatch.setattr(routes_module, 'get_status', lambda: {'blocking_maintenance': True})
    response = client.get('/api/routes/comparison?atlas_itinerary_id=1')
    assert response.status_code == 503
    assert response.json['phase'] == 'import'


def _add_candidate(client, itinerary_id, identities, *, name=None, direction='0', variants=None, uics=None):
    with client.application.app_context():
        db.session.add(Itinerary(
            id=itinerary_id, source='osm', line_family_id=4, source_itinerary_id=f'osm-{itinerary_id}',
            display_name=name or f'Variant {itinerary_id}', direction_id=direction,
        ))
        for sequence, identity in enumerate(identities, 1):
            db.session.add(StopCall(
                itinerary_id=itinerary_id, stop_sequence=sequence, source_sloid=identity,
                source_sloid_variants=json.dumps(variants[sequence - 1]) if variants else None,
                uic_ref=uics[sequence - 1] if uics else None,
            ))
        db.session.commit()


def test_ranked_options_include_saved_candidates_and_allow_unmatched_filter(comparison_db):
    all_candidates = comparison_db.get(
        '/api/routes/comparison/options?source=osm&fixed_itinerary_id=101',
    ).json
    assert all_candidates['total'] == 4
    assert all_candidates['best']['id'] == 201
    assert all_candidates['best']['percentage'] == 100
    assert all_candidates['best']['is_matched'] is True
    unmatched = comparison_db.get(
        '/api/routes/comparison/options?source=osm&fixed_itinerary_id=101&unmatched=1',
    ).json
    assert unmatched['total'] == 3
    assert unmatched['best']['id'] == 202
    assert unmatched['best']['percentage'] == 50


def test_ranked_options_find_global_best_beyond_first_alphabetical_page(comparison_db):
    for candidate_id in range(300, 335):
        _add_candidate(comparison_db, candidate_id, ['unrelated'], name=f'A candidate {candidate_id}')
    _add_candidate(comparison_db, 399, ['A', 'B', 'C'], name='ZZZ best', direction='1')

    result = comparison_db.get(
        '/api/routes/comparison/options?source=osm&fixed_itinerary_id=102&per_page=2',
    ).json
    assert result['total'] == 40
    assert [item['id'] for item in result['items']] == [399, 202]
    assert result['best']['id'] == 399
    assert result['best']['percentage'] == 100
    assert result['best']['direction_id'] == '1'
    next_page = comparison_db.get(
        '/api/routes/comparison/options?source=osm&fixed_itinerary_id=102&per_page=2&page=2',
    ).json
    assert [item['id'] for item in next_page['items']] == [201, 203]
    assert next_page['best'] == result['best']


def test_ranked_search_preserves_global_best_and_reports_empty_result(comparison_db):
    _add_candidate(comparison_db, 399, ['A', 'B', 'C'], name='Best express')
    for query in ('Variant 2', 'no results anywhere'):
        response = comparison_db.get('/api/routes/comparison/options', query_string={
            'source': 'osm', 'fixed_itinerary_id': 102, 'q': query,
        }).json
        assert response['best']['id'] == 399
        assert response['best']['percentage'] == 100
        assert [item['id'] for item in response['items']] == ([202] if query == 'Variant 2' else [])


def test_ranking_prioritizes_ratio_then_matched_count_then_stable_id(comparison_db):
    _add_candidate(comparison_db, 210, ['A', 'B', 'C', 'X'])
    _add_candidate(comparison_db, 211, ['A', 'B', 'X', 'X', 'X', 'X'])
    _add_candidate(comparison_db, 212, ['A', 'X', 'X'])
    result = comparison_db.get('/api/routes/comparison/options', query_string={
        'source': 'osm', 'fixed_itinerary_id': 102,
    }).json
    assert [item['id'] for item in result['items']] == [210, 202, 211, 201, 212, 203, 204]
    assert result['items'][0]['stop_ratio'] == 0.75
    assert result['items'][2]['matched_stop_count'] == 2
    assert result['items'][3]['matched_stop_count'] == 1


def test_ranked_anchor_locates_candidate_after_scoring(comparison_db):
    result = comparison_db.get('/api/routes/comparison/options', query_string={
        'source': 'osm', 'fixed_itinerary_id': 102, 'per_page': 1, 'anchor_id': 201,
    }).json
    assert result['page'] == 2
    assert result['items'][0]['id'] == 201
    assert result['best']['id'] == 202


def test_ranking_variants_and_uic_follow_comparison_identity_rules(comparison_db):
    with comparison_db.application.app_context():
        for call in db.session.query(StopCall).filter(StopCall.itinerary_id == 102):
            call.uic_ref = str(call.stop_sequence)
        db.session.commit()
    _add_candidate(comparison_db, 210, ['X', 'Y', 'Z'], uics=['1', '2', '3'])
    _add_candidate(comparison_db, 211, [None, None, None], uics=['1', '2', '3'])
    _add_candidate(comparison_db, 212, ['X', 'Y', 'Z'], variants=[['A'], ['B'], ['C']])
    result = comparison_db.get('/api/routes/comparison/options', query_string={
        'source': 'osm', 'fixed_itinerary_id': 102,
    }).json
    scores = {item['id']: item['percentage'] for item in result['items']}
    assert scores[210] == 0
    assert scores[211] == 100
    assert scores[212] == 100
    assert result['best']['id'] == 211
    for item in result['items']:
        comparison = comparison_db.get('/api/routes/comparison', query_string={
            'atlas_itinerary_id': 102, 'osm_itinerary_id': item['id'],
        }).json
        assert item['stop_ratio'] == comparison['stop_ratio']
        assert item['matched_stop_count'] == comparison['matched_stop_count']


def test_sparse_lcs_matches_alignment_on_repetitions_conflicts_and_variants():
    import random

    randomizer = random.Random(8321)
    for _ in range(100):
        sequences = []
        for _side in range(2):
            sequences.append([
                _call(index, randomizer.choice(['A', 'B', 'C', None]),
                      uic=randomizer.choice(['1', '2', None]),
                      variants=randomizer.choice([None, ['B', 'C']]))
                for index in range(randomizer.randrange(10))
            ])
        atlas, osm = sequences
        index = _identity_index([_identity(call) for call in osm])
        score = _ordered_match_count([_matching_positions(_identity(call), index) for call in atlas])
        assert score == _compare(atlas, osm)['matched_stop_count']


def test_batch_best_matches_ranked_options_on_both_sides(comparison_db):
    response = comparison_db.get('/api/routes/comparison/best', query_string={
        'itinerary_id': [101, 102, 202, 104],
    })
    assert response.status_code == 200
    for fixed_id, source in [(101, 'osm'), (102, 'osm'), (202, 'atlas'), (104, 'osm')]:
        options = comparison_db.get('/api/routes/comparison/options', query_string={
            'source': source, 'fixed_itinerary_id': fixed_id,
        }).json
        assert response.json['items'][str(fixed_id)] == options['best']


def test_ranked_empty_calls_and_no_candidates_have_explicit_empty_scores(comparison_db):
    with comparison_db.application.app_context():
        db.session.query(StopCall).delete()
        db.session.commit()
    result = comparison_db.get('/api/routes/comparison/options?source=osm&fixed_itinerary_id=102').json
    assert result['best']['id'] == 201
    assert result['best']['percentage'] is None
    assert result['best']['matched_stop_count'] == 0
    with comparison_db.application.app_context():
        db.session.query(Itinerary).filter(Itinerary.source == 'osm').delete()
        db.session.commit()
    result = comparison_db.get('/api/routes/comparison/options?source=osm&fixed_itinerary_id=102').json
    assert result['best'] is None
    assert result['items'] == []
    assert result['total'] == 0
    assert comparison_db.get('/api/routes/comparison/best?itinerary_id=102').json == {'items': {'102': None}}


@pytest.mark.parametrize(('query', 'status'), [
    ('source=osm&fixed_itinerary_id=201', 400),
    ('source=osm&fixed_itinerary_id=0', 400),
    ('source=osm&fixed_itinerary_id=nope', 400),
    ('source=osm&fixed_itinerary_id=99999', 404),
    ('source=atlas&fixed_itinerary_id=299', 404),
])
def test_ranked_fixed_selection_validation(comparison_db, query, status):
    assert comparison_db.get(f'/api/routes/comparison/options?{query}').status_code == status


@pytest.mark.parametrize(('ids', 'status'), [
    ([], 400), (['nope'], 400), ([0], 400), ([101] * 101, 400), ([99999], 404), ([299], 404),
])
def test_batch_best_validates_bounded_ids(comparison_db, ids, status):
    response = comparison_db.get('/api/routes/comparison/best', query_string={'itinerary_id': ids})
    assert response.status_code == status


def test_batch_best_does_not_query_each_candidate(comparison_db):
    from sqlalchemy import event

    for candidate_id in range(300, 350):
        _add_candidate(comparison_db, candidate_id, ['A', 'B', 'C'])
    statements = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    with comparison_db.application.app_context():
        event.listen(db.engine, 'before_cursor_execute', record_query)
        try:
            response = comparison_db.get('/api/routes/comparison/best', query_string={
                'itinerary_id': [101, 102, 103, 104],
            })
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_query)
    assert response.status_code == 200
    assert len(statements) <= 8
    assert response.json['items']['102']['id'] == 300
