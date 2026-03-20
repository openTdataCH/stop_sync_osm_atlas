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
from backend.services.stats_export import load_stats_from_file, save_stats_to_file

# Create data directories
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)


def get_atlas_stops(output_path, download_url):
    """Download and process ATLAS stops data.

    Returns:
        dict: Filter statistics collected during processing, suitable for
              merging into stats.json under the ``atlas_filtering`` key.
    """
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
            df = pd.read_csv(f, sep=";")

            # ── Step 1: Country filter (uicCountryCode == 85) ──────────────
            raw_total = len(df)
            df = df[df['uicCountryCode'] == 85]
            after_country = len(df)

            # ── Step 2: Geography filter (inside Swiss border polygon) ──────
            df = filter_points_in_switzerland(df, lat_col='wgs84North', lon_col='wgs84East')
            after_geo = len(df)

            # ── Step 3: Validity filter (validTo >= today) ──────────────────
            # Note: pandas datetime64[ns] cannot represent years > 2262,
            # turning '9999-12-31' into NaT.  Compare ISO strings directly.
            today_iso = datetime.date.today().isoformat()
            valid_to_iso = df['validTo'].astype(str).str.slice(0, 10)
            df = df[valid_to_iso >= today_iso].copy()
            after_validity = len(df)
            print(
                f"ATLAS: filtered {after_geo - after_validity:,} rows with past "
                f"validTo dates, kept {after_validity:,} rows"
            )

            # ── Step 4: Type filter (BOARDING_PLATFORM) ─────────────────────
            # Collect type counts from the full (pre-type-filter) dataset so we
            # can report every type present in the raw Swiss data.
            type_counts: dict = {}
            if 'trafficPointElementType' in df.columns:
                type_counts = df['trafficPointElementType'].value_counts(dropna=False).to_dict()
                # Convert numpy int64 keys/values to plain Python types
                type_counts = {str(k): int(v) for k, v in type_counts.items()}

                df = df[df['trafficPointElementType'] == 'BOARDING_PLATFORM'].copy()
                print(
                    f"ATLAS: filtered to BOARDING_PLATFORM, kept {len(df):,} "
                    f"(from {after_validity:,})"
                )
            else:
                print("ATLAS: 'trafficPointElementType' column not found, cannot filter for BOARDING_PLATFORM.")

            after_type = len(df)

            # ── Save processed data ─────────────────────────────────────────
            df.to_csv(output_path, sep=";", index=False)
            print(f"ATLAS: total BOARDING_PLATFORM rows kept = {after_type:,}")
            print(f"ATLAS: processed CSV saved to: {output_path}")

            # ── Build and return filter statistics ──────────────────────────
            def _pct(part: int, total: int) -> float:
                return round(part / total * 100, 1) if total else 0.0

            boarding_platform_count = type_counts.get('BOARDING_PLATFORM', 0)
            boarding_area_count = type_counts.get('BOARDING_AREA', 0)

            return {
                "downloaded_at": today_iso,
                "raw_total": raw_total,
                "after_country_filter": after_country,
                "after_geo_filter": after_geo,
                "after_validity_filter": after_validity,
                "after_type_filter": after_type,
                "eliminated_by_country": raw_total - after_country,
                "eliminated_by_geo": after_country - after_geo,
                "eliminated_by_validity": after_geo - after_validity,
                "eliminated_by_type": after_validity - after_type,
                "type_counts": type_counts,
                "boarding_platform_pct": _pct(boarding_platform_count, raw_total),
                "boarding_area_pct": _pct(boarding_area_count, raw_total),
            }


def write_unified_routes_csv_direct(
    gtfs_data,
    traffic_points: pd.DataFrame,
    integrated_gtfs_data: Optional[pd.DataFrame] = None,
    unified_out_path: str = "data/processed/atlas_routes_unified.csv"
):
    """Create unified routes CSV from GTFS source data without intermediate files."""
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
                    'route_id': None if pd.isna(route_id) else str(route_id),
                    'route_id_normalized': _normalize_route_id_for_matching(None if pd.isna(route_id) else str(route_id)),
                    'route_name_short': None if pd.isna(route_short) else str(route_short),
                    'route_name_long': None if pd.isna(route_long) else str(route_long),
                    'line_name': None,
                    'direction_id': None if pd.isna(direction_id) else str(int(float(direction_id))),
                    'direction_name': None if pd.isna(direction) else str(direction),
                    'direction_uic': None,
                })

    if unified_rows:
        unified_df = pd.DataFrame(unified_rows, columns=[
            'sloid','source','evidence','route_id','route_id_normalized','route_name_short','route_name_long','line_name','direction_id','direction_name','direction_uic'
        ])
        unified_df.to_csv(unified_out_path, index=False)
        print(f"Unified routes: wrote {len(unified_df):,} rows to {unified_out_path}")
    else:
        print("No route data to write to unified file")


if __name__ == "__main__":
    # Download and process ATLAS data
    atlas_stops_csv_output_path = "data/raw/stops_ATLAS.csv"
    download_url = "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink"

    atlas_filter_stats = get_atlas_stops(atlas_stops_csv_output_path, download_url)

    # Persist filter stats into stats.json under the 'atlas_filtering' key,
    # merging with any existing content (e.g. pipeline matching stats).
    existing_stats = load_stats_from_file() or {}
    existing_stats["atlas_filtering"] = atlas_filter_stats
    saved_path = save_stats_to_file(existing_stats)
    print(f"ATLAS: filter stats saved to {saved_path}")

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

    # Build unified routes file directly from source data
    try:
        write_unified_routes_csv_direct(
            gtfs_data=gtfs_stream,
            traffic_points=stops_data,
            integrated_gtfs_data=integrated_data,
            unified_out_path="data/processed/atlas_routes_unified.csv"
        )
    except Exception as e:
        print(f"Error writing unified routes CSV: {e}")

    print("Done!")

