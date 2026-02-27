"""
Simple, clean script to download and process ATLAS and GTFS data.
"""
import requests
import zipfile
import io
import pandas as pd
import os
import datetime
from typing import Optional


from .geo_utils import filter_points_in_switzerland
from .get_atlas_gtfs import (
    download_and_extract_gtfs,
    load_gtfs_data_streaming,
    build_integrated_gtfs_data_streaming,
)
from matching_and_import_db.utils.route_id import normalize_route_id as _normalize_route_id_for_matching
from .get_atlas_hrdf import (
    download_and_extract_hrdf,
    process_hrdf_direction_data,
)

# Create data directories
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)


def get_atlas_stops(output_path, download_url):
    """Download and process ATLAS stops data."""
    response = requests.get(download_url)
    response.raise_for_status()
    
    print("ATLAS: download successful, extracting ZIP file…")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        csv_files = z.namelist()
        print("ATLAS: files in ZIP:", csv_files)
        
        if not csv_files:
            raise Exception("No CSV file found in the ZIP archive.")
        
        csv_filename = csv_files[0]
        print("ATLAS: extracting:", csv_filename)

        with z.open(csv_filename) as f:
            # Load and filter for Switzerland (country code 85) with coordinates
            df = pd.read_csv(f, sep=";")
            df = df[df['uicCountryCode'] == 85]
            df = filter_points_in_switzerland(df, lat_col='wgs84North', lon_col='wgs84East')
            
            # Filter for future validTo dates
            # Note: pandas datetime64[ns] cannot represent years > 2262, turning '9999-12-31' into NaT.
            # To avoid dropping such "infinite" dates, compare ISO date strings directly.
            today_iso = datetime.date.today().isoformat()
            valid_to_iso = df['validTo'].astype(str).str.slice(0, 10)
            before_date_filter = len(df)
            df = df[valid_to_iso >= today_iso].copy()
            print(f"ATLAS: filtered {before_date_filter - len(df):,} rows with past validTo dates, kept {len(df):,} rows")
            
            # Filter for BOARDING_PLATFORM entries, which are the focus of matching
            before_platform_filter = len(df)
            if 'trafficPointElementType' in df.columns:
                df = df[df['trafficPointElementType'] == 'BOARDING_PLATFORM'].copy()
                print(f"ATLAS: filtered to BOARDING_PLATFORM, kept {len(df):,} (from {before_platform_filter:,})")
            else:
                print("ATLAS: 'trafficPointElementType' column not found, cannot filter for BOARDING_PLATFORM.")
            
            # Save processed data (Swiss BOARDING_PLATFORM rows with coordinates and future validTo)
            df.to_csv(output_path, sep=";", index=False)
            
            # Print statistics
            print(f"ATLAS: total BOARDING_PLATFORM rows kept = {len(df):,}")
            print(f"ATLAS: processed CSV saved to: {output_path}")


def write_unified_routes_csv_direct(
    gtfs_data,
    hrdf_data: Optional[pd.DataFrame],
    traffic_points: pd.DataFrame,
    integrated_gtfs_data: Optional[pd.DataFrame] = None,
    unified_out_path: str = "data/processed/atlas_routes_unified.csv"
):
    """Create unified routes CSV directly from source data without intermediate files."""
    today = datetime.date.today().isoformat()
    unified_rows = []

    # Process GTFS data - determine which integrated data to use
    integrated_data = None
    
    if integrated_gtfs_data is not None:
        print("Processing GTFS data for unified routes (reusing precomputed integration)...")
        integrated_data = integrated_gtfs_data
    elif gtfs_data and 'stop_route_unique' in gtfs_data and 'routes' in gtfs_data and 'route_directions' in gtfs_data:
        print("Processing GTFS data for unified routes...")
        # Build integrated GTFS data (per-stop, per-route with a representative direction)
        integrated_data = build_integrated_gtfs_data_streaming(gtfs_data, traffic_points)
    
    # Process integrated GTFS data (common path for both branches above)
    if integrated_data is not None and not integrated_data.empty:
        for r in integrated_data.itertuples(index=False):
            sloid = getattr(r, 'sloid', None)
            route_id = getattr(r, 'route_id', None)
            direction = getattr(r, 'direction', None)
            direction_id = getattr(r, 'direction_id', None)
            route_short = getattr(r, 'route_short_name', None)
            route_long = getattr(r, 'route_long_name', None)
            
            if pd.notna(sloid):  # Only include rows with valid sloid mapping
                unified_rows.append({
                    'sloid': str(sloid),
                    'source': 'gtfs',
                    'evidence': 'gtfs_first_last',
                    'as_of': today,
                    'route_id': None if pd.isna(route_id) else str(route_id),
                    'route_id_normalized': _normalize_route_id_for_matching(None if pd.isna(route_id) else str(route_id)),
                    'route_name_short': None if pd.isna(route_short) else str(route_short),
                    'route_name_long': None if pd.isna(route_long) else str(route_long),
                    'line_name': None,
                    'direction_id': None if pd.isna(direction_id) else str(int(float(direction_id))),
                    'direction_name': None if pd.isna(direction) else str(direction),
                    'direction_uic': None,
                })

    # Process HRDF data
    if hrdf_data is not None and not hrdf_data.empty:
        print("Processing HRDF data for unified routes...")
        for r in hrdf_data.itertuples(index=False):
            sloid = getattr(r, 'sloid', None)
            line_name = getattr(r, 'line_name', None)
            direction_name = getattr(r, 'direction_name', None)
            direction_uic = getattr(r, 'direction_uic', None)
            
            if pd.notna(sloid):  # Only include rows with valid sloid
                unified_rows.append({
                    'sloid': str(sloid),
                    'source': 'hrdf',
                    'evidence': 'hrdf_fplan',
                    'as_of': today,
                    'route_id': None,
                    'route_id_normalized': None,
                    'route_name_short': None,
                    'route_name_long': None,
                    'line_name': None if pd.isna(line_name) else str(line_name),
                    'direction_id': None,
                    'direction_name': None if pd.isna(direction_name) else str(direction_name),
                    'direction_uic': None if pd.isna(direction_uic) else str(direction_uic),
                })

    if unified_rows:
        unified_df = pd.DataFrame(unified_rows, columns=[
            'sloid','source','evidence','as_of','route_id','route_id_normalized','route_name_short','route_name_long','line_name','direction_id','direction_name','direction_uic'
        ])
        unified_df.to_csv(unified_out_path, index=False)
        print(f"Unified routes: wrote {len(unified_df):,} rows to {unified_out_path}")
    else:
        print("No route data to write to unified file")


if __name__ == "__main__":
    # Download and process ATLAS data
    atlas_stops_csv_output_path = "data/raw/stops_ATLAS.csv"
    download_url = "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink"

    get_atlas_stops(atlas_stops_csv_output_path, download_url)
    
    # Load traffic points data
    stops_data = pd.read_csv(atlas_stops_csv_output_path, sep=';')

    # Process GTFS data
    print("\n=== GTFS Integration (stop_id → sloid) ===")
    gtfs_url = "https://data.opentransportdata.swiss/de/dataset/timetable-2025-gtfs2020/permalink"

    gtfs_stream = None
    integrated_data = None
    try:
        gtfs_folder = download_and_extract_gtfs(gtfs_url)

        gtfs_stream = load_gtfs_data_streaming(gtfs_folder)
        integrated_data = build_integrated_gtfs_data_streaming(gtfs_stream, stops_data)

        # Print statistics
        total_gtfs_stops = len(integrated_data['stop_id'].unique())
        matched_stops = integrated_data['sloid'].notna().sum()
        unique_sloids_matched = integrated_data['sloid'].dropna().nunique()

        print("\n=== stop_id GTFS → SLOID ATLAS: Summary ===")
        print(f"GTFS integrated stops: {total_gtfs_stops:,}")
        print(f"stop_id→sloid assignments (rows): {matched_stops:,}")
        print(f"unique sloids with routes: {unique_sloids_matched:,}")

        print("===========================")

    except Exception as e:
        print(f"Error processing GTFS data: {e}")
        gtfs_stream = None

    # Process HRDF data
    print("\n=== HRDF Integration (directions) ===")
    hrdf_url = "https://data.opentransportdata.swiss/dataset/6083374f-6a6a-4d84-a6f7-0816493a0766/resource/95fd7309-cc17-4af7-a2f7-e77f04eb328f/download/oev_sammlung_ch_hrdf_5_40_41_2025_20250711_220742.zip"
    
    hrdf_results = None
    try:
        hrdf_folder = download_and_extract_hrdf(hrdf_url)
        
        if os.path.exists(hrdf_folder):
            # List the contents of the HRDF folder to see what files we have
            hrdf_files = os.listdir(hrdf_folder)
            print(f"HRDF: folder contains {len(hrdf_files)} items")
            
            hrdf_results = process_hrdf_direction_data(stops_data, hrdf_folder)
            
            if hrdf_results is not None:
                print("\n=== HRDF Direction Summary ===")
                print(f"Direction entries: {len(hrdf_results):,}")
                print(f"Unique sloids with directions: {hrdf_results['sloid'].nunique():,}")
                print("===========================")
            else:
                print("No HRDF direction data could be processed")
        else:
            print(f"HRDF folder {hrdf_folder} not found")
            
    except Exception as e:
        print(f"Error processing HRDF data: {e}")
        hrdf_results = None
    
    # Build unified routes file directly from source data
    try:
        write_unified_routes_csv_direct(
            gtfs_data=gtfs_stream,
            hrdf_data=hrdf_results,
            traffic_points=stops_data,
            integrated_gtfs_data=integrated_data,
            unified_out_path="data/processed/atlas_routes_unified.csv"
        )
    except Exception as e:
        print(f"Error writing unified routes CSV: {e}")

    print("Done!")

