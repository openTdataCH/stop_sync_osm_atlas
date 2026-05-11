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
    build_gtfs_atlas_payload,
    download_and_extract_gtfs,
    load_gtfs_data_streaming,
    build_integrated_gtfs_data_streaming,
    write_gtfs_db_payload_cache,
)
from matching_and_import_db.utils.route_id import normalize_route_id as _normalize_route_id_for_matching
from backend.services.stats_export import load_stats_from_file, save_stats_to_file


ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK = (
    "https://data.opentransportdata.swiss/dataset/traffic-point-v2/"
    "resource_permalink/actual-date-world-traffic-point.csv"
)


def _ensure_parent_dir(path: str) -> None:
    """Create the output parent directory if needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_atlas_dataframe(response: requests.Response) -> pd.DataFrame:
    payload = io.BytesIO(response.content)
    if zipfile.is_zipfile(payload):
        payload.seek(0)
        print("ATLAS: download successful, extracting ZIP file...")
        with zipfile.ZipFile(payload) as z:
            csv_files = z.namelist()
            print("ATLAS: files in ZIP:", csv_files)

            if not csv_files:
                raise Exception("No CSV file found in the ZIP archive.")

            csv_filename = csv_files[0]
            print("ATLAS: extracting:", csv_filename)

            with z.open(csv_filename) as extracted_file:
                return pd.read_csv(extracted_file, sep=";")

    payload.seek(0)
    print("ATLAS: download successful, reading CSV file...")
    return pd.read_csv(payload, sep=";", encoding="utf-8-sig")


def _safe_direction_id(val):
    try:
        if pd.isna(val):
            return None
        return str(int(float(val)))
    except (TypeError, ValueError):
        return None


def _resolve_integrated_gtfs_data(
    gtfs_data,
    traffic_points: pd.DataFrame,
    integrated_gtfs_data: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    if integrated_gtfs_data is not None:
        return integrated_gtfs_data
    if gtfs_data and 'stop_route_unique' in gtfs_data and 'routes' in gtfs_data and 'route_directions' in gtfs_data:
        return build_integrated_gtfs_data_streaming(gtfs_data, traffic_points)
    return None


def get_current_gtfs_permalink(year: Optional[int] = None, locale: str = "en") -> str:
    """Return the OpenTransportData GTFS permalink for the active timetable year."""
    target_year = int(year) if year is not None else datetime.date.today().year
    return f"https://data.opentransportdata.swiss/{locale}/dataset/timetable-{target_year}-gtfs2020/permalink"


def get_atlas_stops(output_path, download_url):
    """Download and process ATLAS stops data.

    Returns:
        dict: Filter statistics collected during processing, suitable for
              merging into stats.json under the ``atlas_filtering`` key.
    """
    response = requests.get(download_url)
    response.raise_for_status()

    df = _load_atlas_dataframe(response)

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
    _ensure_parent_dir(output_path)
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
        "after_uic_number_filter": after_country,
        "after_geo_filter": after_geo,
        "after_validity_filter": after_validity,
        "after_type_filter": after_type,
        "eliminated_by_uic_number": raw_total - after_country,
        "eliminated_by_geo": after_country - after_geo,
        "eliminated_by_validity": after_geo - after_validity,
        "eliminated_by_type": after_validity - after_type,
        "type_counts": type_counts,
        "boarding_platform_pct": _pct(boarding_platform_count, raw_total),
        "boarding_area_pct": _pct(boarding_area_count, raw_total),
    }


def write_atlas_route_csvs(
    gtfs_data,
    traffic_points: pd.DataFrame,
    integrated_gtfs_data: Optional[pd.DataFrame] = None,
    out_dir: str = "data/processed/"
):
    """Create entity-first GTFS route mappings without intermediate files."""
    _ensure_parent_dir(os.path.join(out_dir, "dummy"))
    integrated_data = _resolve_integrated_gtfs_data(gtfs_data, traffic_points, integrated_gtfs_data)
    if integrated_gtfs_data is not None:
        print("Processing GTFS data for GTFS routes (reusing precomputed integration)...")
    elif integrated_data is not None:
        print("Processing GTFS data for GTFS routes...")
    
    if integrated_data is None or integrated_data.empty:
        print("No route data to write to GTFS files")
        return

    # Extract distinct routes
    routes_df = integrated_data[['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type']].drop_duplicates(subset=['route_id'])
    routes_df['route_id_normalized'] = routes_df['route_id'].apply(lambda x: _normalize_route_id_for_matching(str(x)) if pd.notna(x) else None)
    # Record the pipeline run date on each emitted route row.
    routes_df['run_id'] = datetime.date.today().isoformat()
    routes_out = os.path.join(out_dir, "atlas_routes.csv")
    routes_df.to_csv(routes_out, index=False)
    print(f"GTFS routes: wrote {len(routes_df):,} rows to {routes_out}")

    # Extract distinct route directions
    directions_df = integrated_data[['route_id', 'direction_id', 'direction']].drop_duplicates(subset=['route_id', 'direction_id'])
    directions_df['direction_id'] = directions_df['direction_id'].apply(_safe_direction_id)
    directions_df['representative_headsign'] = None
    directions_df['direction_label'] = directions_df['direction']
    directions_out = os.path.join(out_dir, "atlas_route_directions.csv")
    directions_df[['route_id', 'direction_id', 'representative_headsign', 'direction_label']].to_csv(directions_out, index=False)
    print(f"GTFS directions: wrote {len(directions_df):,} rows to {directions_out}")

    # Extract ordered stops per route-direction using the integrated row order.
    stops_df = integrated_data[['route_id', 'direction_id', 'sloid', 'stop_id']].copy()
    stops_df['direction_id'] = stops_df['direction_id'].apply(_safe_direction_id)
    stops_df['stop_sequence'] = stops_df.groupby(['route_id', 'direction_id']).cumcount()
    if 'match_method' in integrated_data.columns:
        stops_df['mapping_method'] = integrated_data['match_method']
    elif 'mapping_method' in integrated_data.columns:
        stops_df['mapping_method'] = integrated_data['mapping_method']
    else:
        stops_df['mapping_method'] = None
    stops_out = os.path.join(out_dir, "atlas_route_stops.csv")
    stops_df.to_csv(stops_out, index=False)
    print(f"GTFS route stops: wrote {len(stops_df):,} rows to {stops_out}")


if __name__ == "__main__":
    # Download and process ATLAS data
    atlas_stops_csv_output_path = "data/raw/stops_ATLAS.csv"
    download_url = ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK

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
    gtfs_url = get_current_gtfs_permalink()

    gtfs_stream = None
    integrated_data = None
    try:
        gtfs_folder = download_and_extract_gtfs(gtfs_url)

        gtfs_stream = load_gtfs_data_streaming(gtfs_folder)
        gtfs_payload = build_gtfs_atlas_payload(gtfs_stream, stops_data)
        integrated_data = build_integrated_gtfs_data_streaming(gtfs_stream, stops_data, gtfs_payload=gtfs_payload)
        gtfs_stop_rows, gtfs_state_rows = write_gtfs_db_payload_cache(gtfs_payload, stops_data)
        print(
            f"GTFS DB cache: wrote {len(gtfs_stop_rows):,} GTFS stops and "
            f"{len(gtfs_state_rows):,} GTFS↔ATLAS state rows"
        )

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

    # Build GTFS routes file directly from source data
    try:
        write_atlas_route_csvs(
            gtfs_data=gtfs_stream,
            traffic_points=stops_data,
            integrated_gtfs_data=integrated_data,
            out_dir="data/processed/"
        )
    except Exception as e:
        print(f"Error writing GTFS routes CSV: {e}")

    print("Done!")

