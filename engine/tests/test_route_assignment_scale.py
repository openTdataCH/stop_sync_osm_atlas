from transport_matcher.routes import _choose_best_itinerary_pairs

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
