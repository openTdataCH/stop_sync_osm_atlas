"""
Tests for data integration and processing pipelines.
Verifies the correct flow of data through the various processing stages.
"""
import os
import sys
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching_and_import_db.downloader.get_atlas_data import write_unified_routes_csv_direct

class TestUnifiedRoutesIntegration:
    """Tests for the Unified Routes CSV generation."""

    def test_gtfs_precomputed_integration_is_used(self, tmp_path):
        """
        Verify that precomputed integrated GTFS data is correctly used.
        
        This ensures that when the pipeline provides already-processed GTFS data,
        it is successfully written to the output file without being re-processed
        or ignored.
        """
        # 1. Setup Mock Data
        
        # Output file path
        output_file = tmp_path / "unified_routes_test.csv"
        
        # Traffic points (needed by input signature, but not used if integrated keys are present)
        traffic_points = pd.DataFrame({'sloid': []})
        
        # GTFS Stream (can be None or mock, we are testing the precomputed path)
        gtfs_stream = {} 
        
        # Precomputed Integrated GTFS Data
        # Create a DataFrame that mimics build_integrated_gtfs_data_streaming output
        integrated_gtfs_data = pd.DataFrame([
            {
                'sloid': 'ch:1:sloid:1',
                'route_id': 'gtfs-route-1',
                'route_short_name': 'R1',
                'route_long_name': 'Route 1',
                'direction_id': 0,
                'direction': 'A -> B'
            },
            {
                'sloid': 'ch:1:sloid:2',
                'route_id': 'gtfs-route-2',
                'route_short_name': 'R2',
                'route_long_name': 'Route 2',
                'direction_id': 1,
                'direction': 'B -> A'
            }
        ])
        
        # 2. Execute Function
        write_unified_routes_csv_direct(
            gtfs_data=gtfs_stream,
            traffic_points=traffic_points,
            integrated_gtfs_data=integrated_gtfs_data,
            unified_out_path=str(output_file)
        )
        
        # 3. Verify Output
        
        assert output_file.exists(), "Output CSV was not created"
        
        # Read result
        result_df = pd.read_csv(output_file)
        
        # Check assertions
        assert len(result_df) == 2, f"Expected 2 rows, got {len(result_df)}"
        expected_cols = {
            'sloid',
            'route_id',
            'route_id_normalized',
            'route_name_short',
            'route_name_long',
            'direction_id',
            'direction_name',
        }
        assert expected_cols.issubset(set(result_df.columns)), "GTFS-only columns are missing"
        assert 'source' not in result_df.columns, "Legacy source column should not be written"
        assert 'gtfs-route-1' in result_df['route_id'].values
        assert 'gtfs-route-2' in result_df['route_id'].values
        
        print(f"\n✅ Regression test passed: {len(result_df)} GTFS rows successfully written from precomputed data.")

    def test_gtfs_only_integration(self, tmp_path):
        """Test that unified routes output contains GTFS entries only."""
        output_file = tmp_path / "unified_gtfs_only.csv"
        traffic_points = pd.DataFrame({'sloid': []})
        gtfs_stream = {}
        
        # GTFS Input
        integrated_gtfs = pd.DataFrame([{
            'sloid': 'ch:1:sloid:1',
            'route_id': 'r1',
            'direction_id': 0,
            'direction': 'dir1'
        }])
        
        # Execute
        write_unified_routes_csv_direct(
            gtfs_data=gtfs_stream,
            traffic_points=traffic_points,
            integrated_gtfs_data=integrated_gtfs,
            unified_out_path=str(output_file)
        )
        
        # Verify
        result = pd.read_csv(output_file)
        assert len(result) == 1
        assert result.iloc[0]['sloid'] == 'ch:1:sloid:1'
        assert 'source' not in result.columns

