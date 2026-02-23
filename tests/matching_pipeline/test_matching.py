"""
Unit tests for the matching pipeline.

Tests cover:
- Utility functions (haversine_distance, is_osm_station)
- Route matching helpers (_normalize_route_id_for_matching, _normalize_direction_id)
- Pipeline framework (make_match, run_pipeline, compute_no_nearby_osm)
- Exact matching predicate
- Name matching predicate
- Distance matching helpers (bipartite_match)
"""

import pytest
import pandas as pd
from collections import defaultdict


def _make_ctx(atlas_df, osm_nodes, uic_ref_dict, name_index):
    """Helper to build a MatchingContext from test data in the new API."""
    from matching_process.pipeline import MatchingContext
    from matching_process.state import AtlasState, OsmIndex

    atlas_state = AtlasState(
        atlas_df=atlas_df,
        duplicate_sloid_map={},
    )
    osm_idx = OsmIndex(
        xml_nodes=osm_nodes,
        uic_ref_dict=uic_ref_dict,
        name_index=name_index,
    )
    return MatchingContext(atlas=atlas_state, osm=osm_idx)


# =============================================================================
# Tests for matching_process/utils.py
# =============================================================================


class TestHaversineDistance:
    """Tests for the haversine_distance function."""

    def test_same_point_returns_zero(self):
        """Two identical points should have zero distance."""
        from matching_process.utils import haversine_distance

        distance = haversine_distance(47.0, 8.0, 47.0, 8.0)
        assert distance is not None
        assert distance == pytest.approx(0.0, abs=0.001)

    def test_known_distance_zurich_bern(self, known_coordinates):
        """Test with known distance between Zürich and Bern."""
        from matching_process.utils import haversine_distance

        coords = known_coordinates['zurich_bern']
        lat1, lon1 = coords['point1']
        lat2, lon2 = coords['point2']

        distance_m = haversine_distance(lat1, lon1, lat2, lon2)
        distance_km = distance_m / 1000

        assert distance_km == pytest.approx(
            coords['expected_distance_km'],
            abs=coords['tolerance_km']
        )

    def test_short_distance(self, known_coordinates):
        """Test short distance calculation (< 100m)."""
        from matching_process.utils import haversine_distance

        coords = known_coordinates['short_distance']
        lat1, lon1 = coords['point1']
        lat2, lon2 = coords['point2']

        distance_m = haversine_distance(lat1, lon1, lat2, lon2)

        # Should be approximately 15 meters
        assert distance_m == pytest.approx(15, abs=5)

    def test_invalid_input_returns_none(self):
        """Invalid inputs should return None, not raise exceptions."""
        from matching_process.utils import haversine_distance

        assert haversine_distance('invalid', 8.0, 47.0, 8.0) is None
        assert haversine_distance(47.0, None, 47.0, 8.0) is None
        assert haversine_distance(47.0, 8.0, 'bad', 8.0) is None

    def test_string_numbers_work(self):
        """String representations of numbers should work."""
        from matching_process.utils import haversine_distance

        distance = haversine_distance('47.0', '8.0', '47.0', '8.0')
        assert distance is not None
        assert distance == pytest.approx(0.0, abs=0.001)


class TestIsOsmStation:
    """Tests for the is_osm_station function."""

    def test_railway_station_is_station(self):
        from matching_process.utils import is_osm_station
        node = {'tags': {'railway': 'station'}}
        assert is_osm_station(node) is True

    def test_public_transport_station_is_station(self):
        from matching_process.utils import is_osm_station
        node = {'tags': {'public_transport': 'station'}}
        assert is_osm_station(node) is True

    def test_aerialway_station_is_not_station(self):
        from matching_process.utils import is_osm_station
        node = {'tags': {'aerialway': 'station'}}
        assert is_osm_station(node) is False

    def test_stop_position_is_not_station(self):
        from matching_process.utils import is_osm_station
        node = {'tags': {'public_transport': 'stop_position'}}
        assert is_osm_station(node) is False

    def test_empty_tags_is_not_station(self):
        from matching_process.utils import is_osm_station
        assert is_osm_station({'tags': {}}) is False
        assert is_osm_station({}) is False

    def test_combined_tags_railway_and_aerialway(self):
        """When both railway=station and aerialway=station present, aerialway takes precedence."""
        from matching_process.utils import is_osm_station
        node = {'tags': {'railway': 'station', 'aerialway': 'station'}}
        assert is_osm_station(node) is False


# =============================================================================
# Tests for route matching helpers
# =============================================================================


class TestNormalizeRouteId:
    """Tests for route ID normalization."""

    def test_normalize_journey_numbers(self):
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        assert _normalize_route_id_for_matching('route-j25') == 'route-jXX'
        assert _normalize_route_id_for_matching('route-j123') == 'route-jXX'
        assert _normalize_route_id_for_matching('IC-j1') == 'IC-jXX'

    def test_no_journey_number_unchanged(self):
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        assert _normalize_route_id_for_matching('route123') == 'route123'
        assert _normalize_route_id_for_matching('IC') == 'IC'

    def test_none_input(self):
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        assert _normalize_route_id_for_matching(None) is None
        assert _normalize_route_id_for_matching('') is None

    def test_multiple_journey_patterns(self):
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        assert _normalize_route_id_for_matching('route-j1-j2') == 'route-jXX-jXX'


class TestNormalizeDirectionId:
    """Tests for direction ID normalization."""

    def test_integer_string(self):
        from matching_process.route_matching_unified import _normalize_direction_id
        assert _normalize_direction_id('123') == '123'
        assert _normalize_direction_id('1') == '1'

    def test_float_to_int_string(self):
        from matching_process.route_matching_unified import _normalize_direction_id
        assert _normalize_direction_id(123.0) == '123'
        assert _normalize_direction_id('123.0') == '123'

    def test_nan_returns_none(self):
        from matching_process.route_matching_unified import _normalize_direction_id
        assert _normalize_direction_id(pd.NA) is None
        assert _normalize_direction_id(float('nan')) is None

    def test_invalid_value_returns_none(self):
        from matching_process.route_matching_unified import _normalize_direction_id
        assert _normalize_direction_id('invalid') is None


# =============================================================================
# Tests for pipeline framework (make_match, run_pipeline, compute_no_nearby_osm)
# =============================================================================


class TestMakeMatch:
    """Tests for the make_match helper."""

    def test_creates_valid_record(self):
        from matching_process.pipeline import make_match

        atlas_entry = {
            'sloid': 'ch:1:sloid:1',
            'number': '8503000',
            'designation': '1',
            'designationOfficial': 'Zürich HB',
            'wgs84North': 47.3769,
            'wgs84East': 8.5417,
            'servicePointBusinessOrganisationAbbreviationEn': 'SBB',
        }
        osm_node = {
            'node_id': 'osm_1', 'lat': 47.3770, 'lon': 8.5418,
            'tags': {'name': 'Zürich HB', 'uic_ref': '8503000'},
        }

        record = make_match(atlas_entry, osm_node, 'exact', 'test note', pool_size=3)

        assert record['sloid'] == 'ch:1:sloid:1'
        assert record['osm_node_id'] == 'osm_1'
        assert record['match_type'] == 'exact'
        assert record['matching_notes'] == 'test note'
        assert record['candidate_pool_size'] == 3
        assert record['distance_m'] is not None
        assert record['distance_m'] >= 0
        # Very close points should have a small distance
        assert record['distance_m'] < 200

    def test_atlas_fields_extracted(self):
        from matching_process.pipeline import make_match

        atlas_entry = {
            'sloid': 'ch:1:sloid:1',
            'number': '8503000',
            'designation': '5',
            'designationOfficial': 'Zürich HB',
            'wgs84North': 47.3769,
            'wgs84East': 8.5417,
            'servicePointBusinessOrganisationAbbreviationEn': 'SBB',
        }
        osm_node = {
            'node_id': 'osm_1', 'lat': 47.3769, 'lon': 8.5417,
            'tags': {},
        }

        record = make_match(atlas_entry, osm_node, 'test', 'note')

        assert record['csv_designation'] == '5'
        assert record['csv_designation_official'] == 'Zürich HB'
        assert record['csv_business_org_abbr'] == 'SBB'


class TestPipelineRunner:
    """Tests for the run_pipeline function."""

    def test_empty_predicates_returns_all_unmatched(self, matching_context):
        from matching_process.pipeline import run_pipeline

        output = run_pipeline([], matching_context)

        assert len(output.matched) == 0
        assert len(output.unmatched_atlas) == 3  # 3 atlas entries from fixture

    def test_simple_predicate_runs(self, matching_context):
        from matching_process.pipeline import run_pipeline, make_match

        def always_match_first(ctx):
            """Dummy predicate that matches the first unmatched row."""
            unmatched = ctx.atlas.get_unmatched_records()
            row = unmatched[0]
            # Pick first available OSM node
            osm = next(iter(ctx.osm._all_nodes.values()))
            return [make_match(row, osm, 'test_pred', 'test')]

        output = run_pipeline([always_match_first], matching_context)

        assert len(output.matched) == 1
        assert output.matched[0]['match_type'] == 'test_pred'
        # 3 atlas entries, 1 matched → 2 unmatched
        assert len(output.unmatched_atlas) == 2

    def test_runner_updates_tracking_sets(self, matching_context):
        from matching_process.pipeline import run_pipeline, make_match

        def match_one(ctx):
            unmatched = ctx.atlas.get_unmatched_records()
            row = unmatched[0]
            osm = next(iter(ctx.osm._all_nodes.values()))
            return [make_match(row, osm, 'test', 'note')]

        run_pipeline([match_one], matching_context)

        assert len(matching_context.atlas.matched_ids) == 1
        assert len(matching_context.osm.used_ids) >= 1

    def test_multiple_predicates_chain(self, matching_context):
        from matching_process.pipeline import run_pipeline, make_match

        call_order = []

        def pred_a(ctx):
            call_order.append('a')
            unmatched = ctx.atlas.get_unmatched_records()
            row = unmatched[0]
            osm = list(ctx.osm._all_nodes.values())[0]
            return [make_match(row, osm, 'pred_a', 'note')]

        def pred_b(ctx):
            call_order.append('b')
            unmatched = ctx.atlas.get_unmatched_records()
            row = unmatched[0]
            osm = list(ctx.osm._all_nodes.values())[1]
            return [make_match(row, osm, 'pred_b', 'note')]

        output = run_pipeline([pred_a, pred_b], matching_context)

        assert call_order == ['a', 'b']
        assert len(output.matched) == 2
        # First match is pred_a, second is pred_b
        assert output.matched[0]['match_type'] == 'pred_a'
        assert output.matched[1]['match_type'] == 'pred_b'

    def test_skips_predicate_when_all_matched(self, matching_context):
        """If all ATLAS entries are matched, remaining predicates are skipped."""
        from matching_process.pipeline import run_pipeline, make_match

        def match_all(ctx):
            results = []
            unmatched = ctx.atlas.get_unmatched_records()
            osm_list = list(ctx.osm._all_nodes.values())
            for i, row in enumerate(unmatched):
                results.append(make_match(
                    row, osm_list[i % len(osm_list)], 'bulk', 'note'))
            return results

        was_called = []

        def should_not_run(ctx):
            was_called.append(True)
            return []

        run_pipeline([match_all, should_not_run], matching_context)

        assert len(was_called) == 0


class TestComputeNoNearbyOsm:
    """Tests for the compute_no_nearby_osm function."""

    def test_far_away_entry_detected(self):
        from matching_process.pipeline import compute_no_nearby_osm

        # An ATLAS entry far from any OSM node
        unmatched = [{'sloid': 'far_away', 'wgs84North': 0.0, 'wgs84East': 0.0}]
        osm_nodes = {
            (47.0, 8.0): {
                'node_id': 'n1', 'lat': 47.0, 'lon': 8.0,
                'tags': {}, 'local_ref': None,
            }
        }

        result = compute_no_nearby_osm(unmatched, osm_nodes, radius=50)

        assert 'far_away' in result

    def test_nearby_entry_not_flagged(self):
        from matching_process.pipeline import compute_no_nearby_osm

        # ATLAS entry very close to an OSM node
        unmatched = [{'sloid': 'close', 'wgs84North': 47.0001, 'wgs84East': 8.0001}]
        osm_nodes = {
            (47.0, 8.0): {
                'node_id': 'n1', 'lat': 47.0, 'lon': 8.0,
                'tags': {}, 'local_ref': None,
            }
        }

        result = compute_no_nearby_osm(unmatched, osm_nodes, radius=50)

        assert 'close' not in result

    def test_empty_unmatched(self):
        from matching_process.pipeline import compute_no_nearby_osm

        result = compute_no_nearby_osm([], {(47.0, 8.0): {
            'node_id': 'n1', 'lat': 47.0, 'lon': 8.0,
            'tags': {}, 'local_ref': None,
        }}, radius=50)

        assert result == set()


# =============================================================================
# Tests for exact matching predicate
# =============================================================================


class TestExactMatching:
    """Tests for exact UIC-based matching predicate."""

    def test_no_matching_uic(self, matching_context):
        """ATLAS entries with no matching UIC should produce no matches."""
        from matching_process.exact_matching import exact_uic

        # Clear the uic_ref_dict so nothing matches
        matching_context.osm._uic_ref_dict = {}

        matches = exact_uic(matching_context)
        assert len(matches) == 0

    def test_single_osm_for_uic(self):
        """When only one OSM node has the UIC, all ATLAS entries with that UIC match it."""
        from matching_process.exact_matching import exact_uic

        atlas_df = pd.DataFrame({
            'sloid': ['s1'],
            'number': ['8503000'],
            'designation': ['1'],
            'designationOfficial': ['Zürich HB'],
            'wgs84North': [47.3769],
            'wgs84East': [8.5417],
            'uic_ref': ['8503000'],
            'servicePointBusinessOrganisationAbbreviationEn': ['SBB'],
        })

        osm_node = {
            'node_id': 'osm_1', 'lat': 47.3770, 'lon': 8.5418,
            'tags': {'name': 'Zürich HB', 'uic_ref': '8503000'},
            'local_ref': None,
        }

        osm_nodes = {(47.3770, 8.5418): osm_node}
        uic_dict = {'8503000': [osm_node]}

        ctx = _make_ctx(atlas_df, osm_nodes, uic_dict, {})

        matches = exact_uic(ctx)

        assert len(matches) == 1
        assert matches[0]['sloid'] == 's1'
        assert matches[0]['osm_node_id'] == 'osm_1'
        assert matches[0]['match_type'] == 'exact'

    def test_match_record_structure(self, matching_context):
        """Verify exact matching returns properly structured match records."""
        from matching_process.exact_matching import exact_uic

        matches = exact_uic(matching_context)

        for match in matches:
            assert 'sloid' in match
            assert 'osm_node_id' in match
            assert 'match_type' in match
            assert match['match_type'] == 'exact'
            assert 'distance_m' in match
            assert 'matching_notes' in match

    def test_used_osm_ids_updated(self, matching_context):
        """Matched OSM IDs should be added to ctx.osm.used_ids."""
        from matching_process.exact_matching import exact_uic

        matches = exact_uic(matching_context)

        for match in matches:
            assert match['osm_node_id'] in matching_context.osm.used_ids

    def test_many_to_many_refines_by_local_ref(self):
        """Multiple ATLAS + multiple OSM should refine by designation == local_ref."""
        from matching_process.exact_matching import exact_uic

        atlas_df = pd.DataFrame({
            'sloid': ['s1', 's2'],
            'number': ['8503000', '8503000'],
            'designation': ['1', '2'],
            'designationOfficial': ['Zürich HB', 'Zürich HB'],
            'wgs84North': [47.3769, 47.3769],
            'wgs84East': [8.5417, 8.5417],
            'uic_ref': ['8503000', '8503000'],
            'servicePointBusinessOrganisationAbbreviationEn': ['SBB', 'SBB'],
        })

        osm_a = {
            'node_id': 'osm_a', 'lat': 47.3770, 'lon': 8.5418,
            'tags': {'uic_ref': '8503000'}, 'local_ref': '1',
        }
        osm_b = {
            'node_id': 'osm_b', 'lat': 47.3771, 'lon': 8.5419,
            'tags': {'uic_ref': '8503000'}, 'local_ref': '2',
        }

        osm_nodes = {
            (47.3770, 8.5418): osm_a,
            (47.3771, 8.5419): osm_b,
        }
        uic_dict = {'8503000': [osm_a, osm_b]}

        ctx = _make_ctx(atlas_df, osm_nodes, uic_dict, {})

        matches = exact_uic(ctx)

        assert len(matches) == 2
        matched_pairs = {(m['sloid'], m['osm_node_id']) for m in matches}
        assert ('s1', 'osm_a') in matched_pairs
        assert ('s2', 'osm_b') in matched_pairs


# =============================================================================
# Tests for name matching predicate
# =============================================================================


class TestNameMatching:
    """Tests for name-based matching predicate."""

    def test_no_name_match(self, matching_context):
        """No matching names should result in no matches."""
        from matching_process.name_matching import name_match

        matching_context.osm._name_index = {}

        matches = name_match(matching_context)
        assert len(matches) == 0

    def test_single_candidate_matched(self):
        """A single candidate for a name should be matched directly."""
        from matching_process.name_matching import name_match

        atlas_df = pd.DataFrame({
            'sloid': ['s1'],
            'number': ['8503000'],
            'designation': ['1'],
            'designationOfficial': ['Zürich HB'],
            'wgs84North': [47.3769],
            'wgs84East': [8.5417],
            'uic_ref': ['8503000'],
            'servicePointBusinessOrganisationAbbreviationEn': ['SBB'],
        })

        osm_node = {
            'node_id': 'osm_1', 'lat': 47.3770, 'lon': 8.5418,
            'tags': {'name': 'Zürich HB'}, 'local_ref': None,
        }

        osm_nodes = {(47.3770, 8.5418): osm_node}
        name_idx = {'Zürich HB': [osm_node]}

        ctx = _make_ctx(atlas_df, osm_nodes, {}, name_idx)

        matches = name_match(ctx)

        assert len(matches) == 1
        assert matches[0]['sloid'] == 's1'
        assert matches[0]['match_type'] == 'name'

    def test_multiple_candidates_refines_by_local_ref(self):
        """Multiple name candidates should refine by designation == local_ref."""
        from matching_process.name_matching import name_match

        atlas_df = pd.DataFrame({
            'sloid': ['s1'],
            'number': ['8503000'],
            'designation': ['2'],
            'designationOfficial': ['Zürich HB'],
            'wgs84North': [47.3769],
            'wgs84East': [8.5417],
            'uic_ref': ['8503000'],
            'servicePointBusinessOrganisationAbbreviationEn': ['SBB'],
        })

        osm_a = {
            'node_id': 'osm_a', 'lat': 47.37, 'lon': 8.54,
            'tags': {'name': 'Zürich HB'}, 'local_ref': '1',
        }
        osm_b = {
            'node_id': 'osm_b', 'lat': 47.37, 'lon': 8.54,
            'tags': {'name': 'Zürich HB'}, 'local_ref': '2',
        }

        osm_nodes = {
            (47.37, 8.54): osm_a,  # Note: duplicate coord key — only one stored
            (47.3701, 8.5401): osm_b,
        }
        name_idx = {'Zürich HB': [osm_a, osm_b]}

        ctx = _make_ctx(atlas_df, osm_nodes, {}, name_idx)

        matches = name_match(ctx)

        assert len(matches) == 1
        assert matches[0]['osm_node_id'] == 'osm_b'

    def test_match_record_structure(self, matching_context):
        """Verify name matching returns properly structured records."""
        from matching_process.name_matching import name_match

        matches = name_match(matching_context)

        for match in matches:
            assert 'sloid' in match
            assert 'osm_node_id' in match
            assert 'match_type' in match
            assert match['match_type'] == 'name'


# =============================================================================
# Tests for distance matching helpers
# =============================================================================


class TestBipartiteMatch:
    """Tests for the bipartite_match helper."""

    def test_equal_size_conflict_free(self):
        """N-to-N with no conflicts should produce N pairs."""
        from matching_process.distance_matching import bipartite_match

        atlas = [
            {'wgs84North': 47.0, 'wgs84East': 8.0},
            {'wgs84North': 47.1, 'wgs84East': 8.1},
        ]
        osm = [
            {'lat': 47.0001, 'lon': 8.0001},
            {'lat': 47.1001, 'lon': 8.1001},
        ]

        pairs = bipartite_match(atlas, osm, max_distance=500)

        assert len(pairs) == 2

    def test_unequal_size_returns_empty(self):
        """Different sizes should return empty."""
        from matching_process.distance_matching import bipartite_match

        atlas = [{'wgs84North': 47.0, 'wgs84East': 8.0}]
        osm = [
            {'lat': 47.0001, 'lon': 8.0001},
            {'lat': 47.1, 'lon': 8.1},
        ]

        assert bipartite_match(atlas, osm, max_distance=500) == []

    def test_exceeds_max_distance_returns_empty(self):
        """All pairs beyond max_distance should return empty."""
        from matching_process.distance_matching import bipartite_match

        atlas = [{'wgs84North': 47.0, 'wgs84East': 8.0}]
        osm = [{'lat': 48.0, 'lon': 9.0}]  # ~130 km away

        assert bipartite_match(atlas, osm, max_distance=50) == []

    def test_conflict_returns_empty(self):
        """Conflicting assignments (non-reciprocal) should return empty."""
        from matching_process.distance_matching import bipartite_match

        # Two ATLAS entries both closest to the same OSM node
        atlas = [
            {'wgs84North': 47.0, 'wgs84East': 8.0},
            {'wgs84North': 47.00001, 'wgs84East': 8.00001},
        ]
        # One OSM node very close, one very far
        osm = [
            {'lat': 47.0, 'lon': 8.0},
            {'lat': 50.0, 'lon': 10.0},  # way too far for reciprocal
        ]

        result = bipartite_match(atlas, osm, max_distance=500)
        # Should fail because both ATLAS entries are closest to osm[0]
        # but osm[0] can only match one
        assert result == []


# =============================================================================
# Integration tests
# =============================================================================


class TestMatchingIntegration:
    """Higher-level tests verifying matching components work together."""

    def test_exact_then_name_pipeline(self, matching_context):
        """Running exact_uic then name_match in sequence should work."""
        from matching_process.pipeline import run_pipeline
        from matching_process.exact_matching import exact_uic
        from matching_process.name_matching import name_match

        output = run_pipeline([exact_uic, name_match], matching_context)

        assert isinstance(output.matched, list)
        assert isinstance(output.unmatched_atlas, list)
        assert isinstance(output.unmatched_osm, list)

        # All matched entries should have required fields
        for m in output.matched:
            assert 'sloid' in m
            assert 'osm_node_id' in m
            assert 'match_type' in m

    def test_matched_osm_ids_not_reused(self, matching_context):
        """An OSM node matched by exact should not be re-matched by name."""
        from matching_process.pipeline import run_pipeline
        from matching_process.exact_matching import exact_uic
        from matching_process.name_matching import name_match

        output = run_pipeline([exact_uic, name_match], matching_context)

        osm_ids = [m['osm_node_id'] for m in output.matched if m['osm_node_id']]
        # No duplicate OSM IDs in matches
        assert len(osm_ids) == len(set(osm_ids))

    def test_no_nearby_osm_in_output(self):
        """Pipeline output should flag entries with no nearby OSM node."""
        from matching_process.pipeline import run_pipeline

        # One ATLAS entry in the middle of nowhere
        atlas_df = pd.DataFrame({
            'sloid': ['isolated'],
            'number': ['0000000'],
            'designation': ['1'],
            'designationOfficial': ['Nowhere'],
            'wgs84North': [0.0],
            'wgs84East': [0.0],
            'uic_ref': ['0000000'],
            'servicePointBusinessOrganisationAbbreviationEn': ['TEST'],
        })

        osm_nodes = {
            (47.0, 8.0): {
                'node_id': 'far', 'lat': 47.0, 'lon': 8.0,
                'tags': {}, 'local_ref': None,
            }
        }

        ctx = _make_ctx(atlas_df, osm_nodes, {}, {})

        output = run_pipeline([], ctx)

        assert 'isolated' in output.no_nearby_osm_sloids
