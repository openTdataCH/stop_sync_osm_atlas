"""
Tests for data integration and processing pipelines.
Verifies the correct flow of data through the various processing stages.
"""
import json
import os
import re
import sys
import pytest
import pandas as pd
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching_and_import_db.downloader.get_atlas_data import (
    ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK,
    _build_atlas_itinerary_frames,
    get_atlas_stops,
    get_current_gtfs_permalink,
    write_atlas_route_csvs,
)

class TestGtfsRoutesIntegration:
    """Tests for the entity-first GTFS route CSV generation."""

    def test_gtfs_precomputed_integration_is_used(self, tmp_path):
        """
        Verify that precomputed integrated GTFS data is correctly used.
        
        This ensures that when the pipeline provides already-processed GTFS data,
        it is successfully written to the output file without being re-processed
        or ignored.
        """
        # 1. Setup Mock Data
        
        # Traffic points (needed by input signature, but not used if integrated keys are present)
        traffic_points = pd.DataFrame({'sloid': []})
        
        # GTFS Stream (can be None or mock, we are testing the precomputed path)
        gtfs_stream = {} 
        
        # Precomputed Integrated GTFS Data
        # Create a DataFrame that mimics build_integrated_gtfs_data_streaming output
        integrated_gtfs_data = pd.DataFrame([
            {
                'sloid': 'ch:1:sloid:1',
                'stop_id': 'stop-1',
                'match_method': 'strict',
                'route_id': 'gtfs-route-1',
                'agency_id': 'agency-1',
                'route_short_name': 'R1',
                'route_long_name': 'Route 1',
                'route_desc': 'Desc 1',
                'route_type': '3',
                'direction_id': 0,
                'direction': 'A -> B'
            },
            {
                'sloid': 'ch:1:sloid:2',
                'stop_id': 'stop-2',
                'match_method': 'coordinate_proximity',
                'route_id': 'gtfs-route-2',
                'agency_id': 'agency-2',
                'route_short_name': 'R2',
                'route_long_name': 'Route 2',
                'route_desc': 'Desc 2',
                'route_type': '3',
                'direction_id': 1,
                'direction': 'B -> A'
            }
        ])
        
        # 2. Execute Function
        write_atlas_route_csvs(
            gtfs_data=gtfs_stream,
            traffic_points=traffic_points,
            integrated_gtfs_data=integrated_gtfs_data,
            out_dir=str(tmp_path)
        )
        
        # 3. Verify Output
        line_families_file = tmp_path / "atlas_line_families.csv"
        itineraries_file = tmp_path / "atlas_itineraries.csv"
        stop_calls_file = tmp_path / "atlas_itinerary_stop_calls.csv"

        assert line_families_file.exists(), "ATLAS line families CSV was not created"
        assert itineraries_file.exists(), "ATLAS itineraries CSV was not created"
        assert stop_calls_file.exists(), "ATLAS itinerary stop calls CSV was not created"

        line_families_df = pd.read_csv(line_families_file)
        itineraries_df = pd.read_csv(itineraries_file)
        stop_calls_df = pd.read_csv(stop_calls_file)

        assert len(line_families_df) == 2, f"Expected 2 line-family rows, got {len(line_families_df)}"
        expected_route_cols = {
            'atlas_line_id',
            'agency_id',
            'route_id_normalized',
            'route_short_name',
            'route_long_name',
            'route_desc',
            'route_type',
        }
        assert expected_route_cols.issubset(set(line_families_df.columns)), "Line-family columns are missing"
        assert 'gtfs-route-1' in line_families_df['atlas_line_id'].values
        assert 'gtfs-route-2' in line_families_df['atlas_line_id'].values

        assert len(itineraries_df) == 2, f"Expected 2 itinerary rows, got {len(itineraries_df)}"
        expected_direction_cols = {
            'atlas_itinerary_id',
            'atlas_line_id',
            'direction_id',
            'representative_headsign',
            'direction_label',
        }
        assert expected_direction_cols.issubset(set(itineraries_df.columns)), "Itinerary columns are missing"
        assert set(itineraries_df['direction_label']) == {'A -> B', 'B -> A'}

        assert len(stop_calls_df) == 2, f"Expected 2 itinerary stop-call rows, got {len(stop_calls_df)}"
        expected_stop_cols = {
            'atlas_itinerary_id',
            'sloid',
            'stop_id',
            'stop_sequence',
            'mapping_method',
        }
        assert expected_stop_cols.issubset(set(stop_calls_df.columns)), "Itinerary stop-call columns are missing"
        assert set(stop_calls_df['sloid']) == {'ch:1:sloid:1', 'ch:1:sloid:2'}
        assert set(stop_calls_df['mapping_method']) == {'strict', 'coordinate_proximity'}

    def test_gtfs_only_integration(self, tmp_path):
        """Test that GTFS routes output writes entity-first GTFS files only."""
        traffic_points = pd.DataFrame({'sloid': []})
        gtfs_stream = {}
        
        # GTFS Input
        integrated_gtfs = pd.DataFrame([{
            'sloid': 'ch:1:sloid:1',
            'stop_id': 'stop-1',
            'match_method': 'unique_number',
            'route_id': 'r1',
            'agency_id': 'agency-1',
            'route_short_name': 'R1',
            'route_long_name': 'Route 1',
            'route_desc': 'Desc 1',
            'route_type': '3',
            'direction_id': 0,
            'direction': 'dir1'
        }])
        
        # Execute
        write_atlas_route_csvs(
            gtfs_data=gtfs_stream,
            traffic_points=traffic_points,
            integrated_gtfs_data=integrated_gtfs,
            out_dir=str(tmp_path)
        )
        
        # Verify
        line_families = pd.read_csv(tmp_path / "atlas_line_families.csv")
        itineraries = pd.read_csv(tmp_path / "atlas_itineraries.csv")
        stop_calls = pd.read_csv(tmp_path / "atlas_itinerary_stop_calls.csv")
        assert len(line_families) == 1
        assert len(itineraries) == 1
        assert len(stop_calls) == 1
        assert stop_calls.iloc[0]['sloid'] == 'ch:1:sloid:1'
        assert stop_calls.iloc[0]['mapping_method'] == 'unique_number'


def test_gtfs_permalink_uses_current_year_and_en_locale():
    current_year = date.today().year
    permalink = get_current_gtfs_permalink()

    assert f"timetable-{current_year}-gtfs2020" in permalink
    assert "/en/dataset/" in permalink


def test_gtfs_permalink_links_do_not_contain_stale_years():
    current_year = str(date.today().year)
    link_pattern = re.compile(r"timetable-(\d{4})-gtfs2020")

    repo_root = Path(__file__).resolve().parents[2]
    checked_files = [
        repo_root / "matching_and_import_db/downloader/get_atlas_data.py",
        repo_root / "documentation/1. Download and process data.md",
    ]

    stale_hits = []
    for file_path in checked_files:
        content = file_path.read_text(encoding='utf-8')
        for match in link_pattern.finditer(content):
            found_year = match.group(1)
            if found_year != current_year:
                stale_hits.append((str(file_path), found_year, match.group(0)))

    assert not stale_hits, f"Found stale GTFS timetable years: {stale_hits}"


def test_atlas_actual_date_permalink_targets_v2_csv_resource():
    assert ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK == (
        "https://data.opentransportdata.swiss/dataset/traffic-point-v2/"
        "resource_permalink/actual-date-world-traffic-point.csv"
    )


def test_get_atlas_stops_accepts_plain_csv_payload_with_bom(tmp_path):
    csv_payload = (
        "\ufeffsloid;uicCountryCode;validTo;trafficPointElementType;wgs84North;wgs84East\n"
        "ch:1:sloid:1;85;9999-12-31;BOARDING_PLATFORM;47.0;8.0\n"
    ).encode("utf-8")
    mocked_response = MagicMock()
    mocked_response.content = csv_payload
    mocked_response.raise_for_status.return_value = None

    output_path = tmp_path / "stops_ATLAS.csv"

    with patch("matching_and_import_db.downloader.get_atlas_data.requests.get", return_value=mocked_response), patch(
        "matching_and_import_db.downloader.get_atlas_data.filter_points_in_switzerland",
        side_effect=lambda df, lat_col, lon_col: df,
    ):
        stats = get_atlas_stops(str(output_path), ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK)

    written = pd.read_csv(output_path, sep=";")

    assert list(written.columns)[0] == "sloid"
    assert written.iloc[0]["sloid"] == "ch:1:sloid:1"
    assert stats["raw_total"] == 1
    assert stats["after_type_filter"] == 1


def test_atlas_itineraries_collapse_same_uic_sequence_and_keep_sloid_variants(tmp_path):
    stop_times_path = tmp_path / "trip_stop_times.csv"
    pd.DataFrame([
        {'trip_id': 'trip-1', 'stop_id': '8501000:0:A', 'stop_sequence': 1},
        {'trip_id': 'trip-1', 'stop_id': '8502000:0:B', 'stop_sequence': 2},
        {'trip_id': 'trip-2', 'stop_id': '8501000:0:C', 'stop_sequence': 1},
        {'trip_id': 'trip-2', 'stop_id': '8502000:0:B', 'stop_sequence': 2},
    ]).to_csv(stop_times_path, index=False)

    gtfs_data = {
        'trip_stop_times_path': str(stop_times_path),
        'trips': pd.DataFrame([
            {'trip_id': 'trip-1', 'route_id': 'R1', 'direction_id': '0', 'trip_headsign': 'End', 'trip_short_name': None, 'shape_id': None},
            {'trip_id': 'trip-2', 'route_id': 'R1', 'direction_id': '0', 'trip_headsign': 'End', 'trip_short_name': None, 'shape_id': None},
        ]),
        'stops': pd.DataFrame([
            {'stop_id': '8501000:0:A', 'stop_name': 'Alpha A', 'platform_code': 'A', 'original_stop_id': '8501000:0:A', 'location_type': None, 'parent_station': None},
            {'stop_id': '8501000:0:C', 'stop_name': 'Alpha C', 'platform_code': 'C', 'original_stop_id': '8501000:0:C', 'location_type': None, 'parent_station': None},
            {'stop_id': '8502000:0:B', 'stop_name': 'Beta B', 'platform_code': 'B', 'original_stop_id': '8502000:0:B', 'location_type': None, 'parent_station': None},
        ]),
    }
    integrated = pd.DataFrame([
        {'stop_id': '8501000:0:A', 'sloid': 'ch:1:sloid:A', 'match_method': 'uic_platform'},
        {'stop_id': '8501000:0:C', 'sloid': 'ch:1:sloid:C', 'match_method': 'uic_platform'},
        {'stop_id': '8502000:0:B', 'sloid': 'ch:1:sloid:B', 'match_method': 'uic_platform'},
    ])

    itineraries_df, stop_calls_df = _build_atlas_itinerary_frames(gtfs_data, integrated)

    assert len(itineraries_df) == 1
    assert int(itineraries_df.iloc[0]['trip_count']) == 2
    assert len(stop_calls_df) == 2

    first_stop = stop_calls_df.sort_values(by='stop_sequence').iloc[0]
    assert json.loads(first_stop['sloid_variants']) == ['ch:1:sloid:A', 'ch:1:sloid:C']


def test_atlas_itineraries_keep_distinct_patterns_when_headsign_missing(tmp_path):
    stop_times_path = tmp_path / "trip_stop_times.csv"
    pd.DataFrame([
        {'trip_id': 'trip-1', 'stop_id': '8501000:0:A', 'stop_sequence': 1},
        {'trip_id': 'trip-1', 'stop_id': '8502000:0:B', 'stop_sequence': 2},
        {'trip_id': 'trip-2', 'stop_id': '8501000:0:A', 'stop_sequence': 1},
        {'trip_id': 'trip-2', 'stop_id': '8503000:0:C', 'stop_sequence': 2},
    ]).to_csv(stop_times_path, index=False)

    gtfs_data = {
        'trip_stop_times_path': str(stop_times_path),
        'trips': pd.DataFrame([
            {'trip_id': 'trip-1', 'route_id': 'R1', 'direction_id': '0', 'trip_headsign': None, 'trip_short_name': None, 'shape_id': None},
            {'trip_id': 'trip-2', 'route_id': 'R1', 'direction_id': '0', 'trip_headsign': None, 'trip_short_name': None, 'shape_id': None},
        ]),
        'stops': pd.DataFrame([
            {'stop_id': '8501000:0:A', 'stop_name': 'Alpha', 'platform_code': 'A', 'original_stop_id': '8501000:0:A', 'location_type': None, 'parent_station': None},
            {'stop_id': '8502000:0:B', 'stop_name': 'Beta', 'platform_code': 'B', 'original_stop_id': '8502000:0:B', 'location_type': None, 'parent_station': None},
            {'stop_id': '8503000:0:C', 'stop_name': 'Gamma', 'platform_code': 'C', 'original_stop_id': '8503000:0:C', 'location_type': None, 'parent_station': None},
        ]),
    }
    integrated = pd.DataFrame([
        {'stop_id': '8501000:0:A', 'sloid': 'ch:1:sloid:A', 'match_method': 'uic_platform'},
        {'stop_id': '8502000:0:B', 'sloid': 'ch:1:sloid:B', 'match_method': 'uic_platform'},
        {'stop_id': '8503000:0:C', 'sloid': 'ch:1:sloid:C', 'match_method': 'uic_platform'},
    ])

    itineraries_df, stop_calls_df = _build_atlas_itinerary_frames(gtfs_data, integrated)

    assert len(itineraries_df) == 2
    assert len(stop_calls_df) == 4

