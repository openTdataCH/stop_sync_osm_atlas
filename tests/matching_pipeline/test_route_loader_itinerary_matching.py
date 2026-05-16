from matching_and_import_db.database.route_loader import (
    _align_stop_sequences,
    _resolve_osm_stop_fields,
    _score_itinerary_pair,
)


def test_resolve_osm_stop_fields_prefers_stop_match_over_raw_uic_key():
    resolved = _resolve_osm_stop_fields(
        'osm-1',
        {
            'uic_ref': '8500001',
            'canonical_stop_key': 'uic:8500001',
            'stop_label': 'Stop A',
        },
        {
            'osm_node_lookup': {},
            'matched_osm_to_sloid': {'osm-1': 'ch:1:sloid:8500001:1'},
            'unique_atlas_sloid_by_uic': {'8500001': 'ch:1:sloid:8500001:9'},
            'atlas_stop_lookup': {},
        },
    )

    assert resolved['canonical_stop_key'] == 'ch:1:sloid:8500001:1'


def test_align_stop_sequences_counts_variant_sloid_matches_and_keeps_order():
    atlas_calls = [
        {
            'source_sloid': 'ch:1:sloid:A:1',
            'source_sloid_variants': '["ch:1:sloid:A:1", "ch:1:sloid:A:2"]',
            'canonical_stop_key': 'ch:1:sloid:A:1',
            'uic_ref': '8500001',
        },
        {
            'source_sloid': 'ch:1:sloid:B:1',
            'source_sloid_variants': None,
            'canonical_stop_key': 'ch:1:sloid:B:1',
            'uic_ref': '8500002',
        },
        {
            'source_sloid': 'ch:1:sloid:C:1',
            'source_sloid_variants': None,
            'canonical_stop_key': 'ch:1:sloid:C:1',
            'uic_ref': '8500003',
        },
    ]
    osm_calls = [
        {
            'canonical_stop_key': 'ch:1:sloid:A:2',
            'uic_ref': '8500001',
        },
        {
            'canonical_stop_key': 'osm:unmatched',
            'uic_ref': '8500009',
        },
        {
            'canonical_stop_key': 'ch:1:sloid:C:1',
            'uic_ref': '8500003',
        },
    ]

    alignments, matched_stop_count = _align_stop_sequences(atlas_calls, osm_calls)

    assert matched_stop_count == 2
    alignment_types = [alignment['alignment_type'] for alignment in alignments]
    assert alignment_types.count('resolved_sloid_match') == 2
    assert alignment_types.count('atlas_only') == 1
    assert alignment_types.count('osm_only') == 1
    assert alignment_types[0] == 'resolved_sloid_match'
    assert alignment_types[-1] == 'resolved_sloid_match'


def test_score_itinerary_pair_requires_exact_direction_and_80_percent_stop_ratio():
    atlas_itinerary = {'direction_id': '0'}
    osm_itinerary = {'direction_id': '0'}
    atlas_calls = [
        {'source_sloid': 'ch:1:sloid:1', 'source_sloid_variants': None, 'canonical_stop_key': 'ch:1:sloid:1', 'uic_ref': '8500001'},
        {'source_sloid': 'ch:1:sloid:2', 'source_sloid_variants': None, 'canonical_stop_key': 'ch:1:sloid:2', 'uic_ref': '8500002'},
        {'source_sloid': 'ch:1:sloid:3', 'source_sloid_variants': None, 'canonical_stop_key': 'ch:1:sloid:3', 'uic_ref': '8500003'},
        {'source_sloid': 'ch:1:sloid:4', 'source_sloid_variants': None, 'canonical_stop_key': 'ch:1:sloid:4', 'uic_ref': '8500004'},
        {'source_sloid': 'ch:1:sloid:5', 'source_sloid_variants': None, 'canonical_stop_key': 'ch:1:sloid:5', 'uic_ref': '8500005'},
    ]
    osm_calls = [
        {'canonical_stop_key': 'ch:1:sloid:1', 'uic_ref': '8500001'},
        {'canonical_stop_key': 'ch:1:sloid:2', 'uic_ref': '8500002'},
        {'canonical_stop_key': 'ch:1:sloid:3', 'uic_ref': '8500003'},
        {'canonical_stop_key': 'ch:1:sloid:4', 'uic_ref': '8500004'},
        {'canonical_stop_key': 'osm:unmatched', 'uic_ref': '8509999'},
    ]

    score_row = _score_itinerary_pair(atlas_itinerary, osm_itinerary, atlas_calls, osm_calls)

    assert score_row['matched_stop_count'] == 4
    assert score_row['stop_score'] == 0.8
    assert score_row['direction_score'] == 1.0
    assert score_row['is_eligible'] is True
    assert score_row['match_reason'] == 'ordered_stop_match'


def test_score_itinerary_pair_uses_uic_fallback_only_without_resolved_identity():
    atlas_itinerary = {'direction_id': '1'}
    osm_itinerary = {'direction_id': '1'}
    atlas_calls = [
        {
            'source_sloid': None,
            'source_sloid_variants': None,
            'canonical_stop_key': 'gtfs:stop-1',
            'uic_ref': '8500100',
        }
    ]
    osm_calls = [
        {
            'canonical_stop_key': 'uic:8500100',
            'uic_ref': '8500100',
        }
    ]

    score_row = _score_itinerary_pair(atlas_itinerary, osm_itinerary, atlas_calls, osm_calls)

    assert score_row['matched_stop_count'] == 1
    assert score_row['is_eligible'] is True
    assert score_row['alignments'][0]['alignment_type'] == 'uic_match'