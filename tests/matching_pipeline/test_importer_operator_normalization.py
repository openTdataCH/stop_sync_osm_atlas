from matching_and_import_db.database import importer as importer_mod
from matching_and_import_db.database.route_loader import _choose_best_itinerary_pairs
from matching_and_import_db.models import AtlasNode, MatchingOutput


class _DummyProblemContext:
    duplicate_osm_group_map = {}

    def nearest_osm_distance(self, *_args, **_kwargs):
        return None


def test_build_fast_insert_payloads_normalizes_blank_atlas_operator_abbr(monkeypatch):
    monkeypatch.setattr(importer_mod, 'evaluate_unmatched_problems', lambda *args, **kwargs: [])
    monkeypatch.setattr(importer_mod, '_build_gtfs_insert_payloads', lambda: ([], []))

    atlas_node = AtlasNode(
        sloid='ch:1:sloid:test',
        lat=47.0,
        lon=8.0,
        uic_ref='8500000',
        designation='1',
        designation_official='Test Stop',
        business_org_abbr='   ',
        business_org_id='',
        business_org_name='',
    )

    result = MatchingOutput(
        matched=[],
        unmatched_atlas=[atlas_node],
        unmatched_osm=[],
        duplicate_sloid_map={},
        osm_stop_units=[],
        all_osm_nodes=[],
    )

    payload = importer_mod.build_fast_insert_payloads(
        result,
        {
            'problem_ctx': _DummyProblemContext(),
            'matched_problem_map': {},
            'unmatched_atlas_problem_map': {},
            'unmatched_osm_problem_map': {},
        },
        route_artifacts={
            'all_route_data': {},
            'route_write_payload': {
                'atlas_line_families': [],
                'atlas_itineraries': [],
                'atlas_itinerary_stop_calls': [],
                'osm_route_masters': [],
                'osm_route_master_tags': [],
                'osm_route_master_members': [],
                'osm_route_relations': [],
                'osm_route_relation_tags': [],
                'osm_route_relation_members': [],
                'osm_route_relation_stops': [],
                'line_families': [],
                'itineraries': [],
                'stop_calls': [],
                'line_family_matches': [],
                'itinerary_matches': [],
                'matched_routes': 0,
            },
        },
    )

    assert payload['atlas_stops'][0]['atlas_business_org_abbr'] is None
    assert payload['atlas_operators'] == []


def test_split_import_payloads_separates_static_dynamic_groups():
    payload_groups = importer_mod.split_import_payloads({
        'atlas_stops': [{'sloid': 's1'}],
        'gtfs_stops_raw': [{'stop_id': 'stop-1'}],
        'osm_nodes': [{'osm_node_id': 'n1'}],
        'line_families': [{'id': 1}],
        'problem_rows': [(1, 'test_problem', 'high')],
        'matched_routes': 4,
        'no_nearby_osm_sloids': {'s1'},
    })

    assert payload_groups.static['atlas_stops'] == [{'sloid': 's1'}]
    assert payload_groups.static['gtfs_stops_raw'] == [{'stop_id': 'stop-1'}]
    assert payload_groups.dynamic['osm_nodes'] == [{'osm_node_id': 'n1'}]
    assert payload_groups.dynamic['line_families'] == [{'id': 1}]
    assert payload_groups.dynamic['problem_rows'] == [(1, 'test_problem', 'high')]
    assert payload_groups.meta['matched_routes'] == 4
    assert payload_groups.meta['no_nearby_osm_sloids'] == {'s1'}


def test_validate_refresh_payloads_rejects_empty_stop_rows():
    try:
        importer_mod._validate_refresh_payloads({'stops_matched': []})
    except RuntimeError as exc:
        assert 'payload contains no stops_matched rows' in str(exc)
    else:
        raise AssertionError('Expected empty stops_matched payload to be rejected')


def test_filter_gtfs_identity_rows_drops_unknown_resolved_sloids():
    rows = importer_mod._filter_gtfs_identity_rows_to_known_sloids(
        [
            {
                'stop_id': 'stop-1',
                'resolved_sloid': 'known-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'details_json': {},
            },
            {
                'stop_id': 'stop-2',
                'resolved_sloid': 'missing-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'distance_m': 3.0,
                'atlas_lat': 46.0,
                'atlas_lon': 7.0,
                'details_json': {'platform_code': '1'},
            },
            {
                'stop_id': 'stop-3',
                'resolved_sloid': 'also-missing-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'details_json': "{'platform_code': '2'}",
            },
        ],
        {'known-sloid'},
    )

    assert rows[0]['resolved_sloid'] == 'known-sloid'
    assert rows[1]['resolved_sloid'] is None
    assert rows[1]['resolution_method'] == 'unmatched'
    assert rows[1]['confidence'] == 0.0
    assert rows[1]['atlas_lat'] is None
    assert rows[1]['details_json']['dropped_resolved_sloid'] == 'missing-sloid'
    assert rows[2]['resolved_sloid'] is None
    assert rows[2]['details_json']['platform_code'] == '2'
    assert rows[2]['details_json']['dropped_resolved_sloid'] == 'also-missing-sloid'


def test_get_refresh_scope_tables_for_atlas_cached_reuses_static_tables():
    rewritten_tables, reused_tables = importer_mod.get_refresh_scope_tables(importer_mod.PipelineRunType.ATLAS_CACHED)

    assert 'atlas_stops' in reused_tables
    assert 'gtfs_stops_raw' in reused_tables
    assert 'atlas_line_families' in reused_tables
    assert 'osm_nodes' in rewritten_tables
    assert 'line_families' in rewritten_tables
    assert 'atlas_stops' not in rewritten_tables


def test_get_refresh_scope_tables_for_atlas_cached_bootstrap_rewrites_static_tables():
    rewritten_tables, reused_tables = importer_mod.get_refresh_scope_tables(
        importer_mod.PipelineRunType.ATLAS_CACHED_BOOTSTRAP
    )

    assert 'atlas_stops' in rewritten_tables
    assert 'gtfs_stops_raw' in rewritten_tables
    assert 'atlas_line_families' in rewritten_tables
    assert reused_tables == []


def test_choose_best_itinerary_pairs_handles_large_atlas_small_osm_without_recursion_error():
    atlas_itineraries = [
        {'id': itinerary_id}
        for itinerary_id in range(1, 1501)
    ]
    osm_itineraries = [
        {'id': 10_001},
        {'id': 10_002},
    ]
    pair_scores = {}
    for atlas_itinerary in atlas_itineraries:
        for osm_itinerary in osm_itineraries:
            score = 0.0
            if atlas_itinerary['id'] == 5 and osm_itinerary['id'] == 10_001:
                score = 0.9
            elif atlas_itinerary['id'] == 999 and osm_itinerary['id'] == 10_002:
                score = 0.8
            pair_scores[(atlas_itinerary['id'], osm_itinerary['id'])] = {
                'overall_score': score,
            }

    chosen_pairs = _choose_best_itinerary_pairs(atlas_itineraries, osm_itineraries, pair_scores)

    assert len(chosen_pairs) == 2
    assert {(atlas_row['id'], osm_row['id']) for atlas_row, osm_row, _ in chosen_pairs} == {
        (5, 10_001),
        (999, 10_002),
    }
