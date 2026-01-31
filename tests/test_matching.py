"""
Unit tests for the matching pipeline.

Tests cover:
- Utility functions (haversine_distance, is_osm_station)
- Route matching helpers (_normalize_route_id_for_matching, _normalize_direction_id)
- Exact matching logic
- Name matching logic
- Distance matching logic (where feasible without spatial index complexity)
"""

import pytest
import pandas as pd
from collections import defaultdict


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
        """Node with railway=station should be identified as station."""
        from matching_process.utils import is_osm_station
        
        node = {'tags': {'railway': 'station'}}
        assert is_osm_station(node) is True

    def test_public_transport_station_is_station(self):
        """Node with public_transport=station should be identified as station."""
        from matching_process.utils import is_osm_station
        
        node = {'tags': {'public_transport': 'station'}}
        assert is_osm_station(node) is True

    def test_aerialway_station_is_not_station(self):
        """Node with aerialway=station should NOT be identified as station."""
        from matching_process.utils import is_osm_station
        
        node = {'tags': {'aerialway': 'station'}}
        assert is_osm_station(node) is False

    def test_stop_position_is_not_station(self):
        """Node with public_transport=stop_position is not a station."""
        from matching_process.utils import is_osm_station
        
        node = {'tags': {'public_transport': 'stop_position'}}
        assert is_osm_station(node) is False

    def test_empty_tags_is_not_station(self):
        """Node with empty tags should not be a station."""
        from matching_process.utils import is_osm_station
        
        assert is_osm_station({'tags': {}}) is False
        assert is_osm_station({}) is False

    def test_combined_tags_railway_and_aerialway(self):
        """When both railway=station and aerialway=station present, aerialway takes precedence."""
        from matching_process.utils import is_osm_station
        
        # aerialway=station should exclude it even if railway=station
        node = {'tags': {'railway': 'station', 'aerialway': 'station'}}
        assert is_osm_station(node) is False


# =============================================================================
# Tests for matching_process/route_matching_unified.py helpers
# =============================================================================


class TestNormalizeRouteId:
    """Tests for route ID normalization."""

    def test_normalize_journey_numbers(self):
        """Journey numbers like -j123 should be normalized to -jXX."""
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        
        assert _normalize_route_id_for_matching('route-j25') == 'route-jXX'
        assert _normalize_route_id_for_matching('route-j123') == 'route-jXX'
        assert _normalize_route_id_for_matching('IC-j1') == 'IC-jXX'

    def test_no_journey_number_unchanged(self):
        """Route IDs without journey numbers should remain unchanged."""
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        
        assert _normalize_route_id_for_matching('route123') == 'route123'
        assert _normalize_route_id_for_matching('IC') == 'IC'

    def test_none_input(self):
        """None input should return None."""
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        
        assert _normalize_route_id_for_matching(None) is None
        assert _normalize_route_id_for_matching('') is None

    def test_multiple_journey_patterns(self):
        """Multiple journey patterns in one string."""
        from matching_process.route_matching_unified import _normalize_route_id_for_matching
        
        assert _normalize_route_id_for_matching('route-j1-j2') == 'route-jXX-jXX'


class TestNormalizeDirectionId:
    """Tests for direction ID normalization."""

    def test_integer_string(self):
        """Integer string should be normalized to string."""
        from matching_process.route_matching_unified import _normalize_direction_id
        
        assert _normalize_direction_id('123') == '123'
        assert _normalize_direction_id('1') == '1'

    def test_float_to_int_string(self):
        """Float should be converted to integer string."""
        from matching_process.route_matching_unified import _normalize_direction_id
        
        assert _normalize_direction_id(123.0) == '123'
        assert _normalize_direction_id('123.0') == '123'

    def test_nan_returns_none(self):
        """NaN/None values should return None."""
        from matching_process.route_matching_unified import _normalize_direction_id
        import pandas as pd
        
        assert _normalize_direction_id(pd.NA) is None
        assert _normalize_direction_id(float('nan')) is None

    def test_invalid_value_returns_none(self):
        """Invalid values should return None, not raise exceptions."""
        from matching_process.route_matching_unified import _normalize_direction_id
        
        assert _normalize_direction_id('invalid') is None


# =============================================================================
# Tests for exact matching
# =============================================================================


class TestExactMatching:
    """Tests for exact UIC-based matching."""

    def test_no_matching_uic(self, sample_atlas_dataframe):
        """ATLAS entries with no matching UIC should be unmatched."""
        from matching_process.exact_matching import exact_matching
        
        # Empty UIC index - nothing matches
        empty_index = {}
        
        matches, unmatched, used_osm_ids = exact_matching(sample_atlas_dataframe, empty_index)
        
        assert len(unmatched) == len(sample_atlas_dataframe)
        assert len(matches) == 0

    def test_match_record_structure(self, sample_atlas_dataframe, uic_index):
        """Verify exact matching returns properly structured match records."""
        from matching_process.exact_matching import exact_matching
        
        atlas_df = sample_atlas_dataframe[sample_atlas_dataframe['number'] == '8503000'].copy()
        matches, unmatched, used_osm_ids = exact_matching(atlas_df, uic_index)
        
        if matches:
            match = matches[0]
            # Check required fields exist
            assert 'sloid' in match
            assert 'osm_node_id' in match
            assert 'match_type' in match
            assert match['match_type'] == 'exact'


class TestNameMatching:
    """Tests for name-based matching."""

    def test_no_name_match(self, sample_atlas_dataframe):
        """No matching names should result in unmatched entries."""
        from matching_process.name_matching import name_based_matching
        
        empty_index = {}
        
        matches, unmatched, used_osm_ids = name_based_matching(sample_atlas_dataframe, empty_index)
        
        assert len(unmatched) == len(sample_atlas_dataframe)

    def test_match_record_structure(self, sample_atlas_dataframe, name_index):
        """Verify name matching returns properly structured match records."""
        from matching_process.name_matching import name_based_matching
        
        atlas_df = sample_atlas_dataframe[
            sample_atlas_dataframe['designationOfficial'] == 'Zürich HB'
        ].copy()
        matches, unmatched, used_osm_ids = name_based_matching(atlas_df, name_index)
        
        if matches:
            match = matches[0]
            assert 'sloid' in match
            assert 'osm_node_id' in match
            assert 'match_type' in match
            assert match['match_type'] == 'name'


# =============================================================================
# Integration-style tests (still using synthetic data)
# =============================================================================


class TestMatchingIntegration:
    """Higher-level tests that verify matching components work together."""

    def test_exact_match_produces_valid_structure(self, sample_atlas_dataframe, uic_index):
        """Verify exact matching returns properly structured results."""
        from matching_process.exact_matching import exact_matching
        
        matches, unmatched, used_osm_ids = exact_matching(sample_atlas_dataframe, uic_index)
        
        # Check result types
        assert isinstance(matches, list)
        assert isinstance(unmatched, list)
        assert isinstance(used_osm_ids, set)

    def test_used_osm_ids_populated(self, sample_atlas_dataframe, uic_index):
        """Verify that matched OSM IDs are tracked."""
        from matching_process.exact_matching import exact_matching
        
        matches, unmatched, used_osm_ids = exact_matching(sample_atlas_dataframe, uic_index)
        
        # Each match should have its OSM ID in used_osm_ids
        for match in matches:
            assert match['osm_node_id'] in used_osm_ids

    def test_unmatched_atlas_preserved(self, sample_atlas_dataframe, uic_index):
        """Verify that unmatched ATLAS entries are preserved correctly."""
        from matching_process.exact_matching import exact_matching
        
        # Add an entry with no matching UIC
        atlas_df = sample_atlas_dataframe.copy()
        new_row = pd.DataFrame([{
            'sloid': 'ch:1:sloid:999',
            'number': '9999999',  # No matching OSM node
            'designation': 'X',
            'designationOfficial': 'NonExistent Station',
            'wgs84North': 47.0,
            'wgs84East': 8.0,
            'uic_ref': '9999999',
            'servicePointBusinessOrganisationAbbreviationEn': 'TEST',
        }])
        atlas_df = pd.concat([atlas_df, new_row], ignore_index=True)
        
        matches, unmatched, used_osm_ids = exact_matching(atlas_df, uic_index)
        
        # The non-existent station should be in unmatched
        assert len(unmatched) > 0
        # Verify the non-matching entry is not in matches
        matched_sloids = [m['sloid'] for m in matches]
        assert 'ch:1:sloid:999' not in matched_sloids
