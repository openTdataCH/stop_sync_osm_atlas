"""
Simple, clean script to download and process ATLAS and GTFS data.
"""
import hashlib
import json
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


def _hash_stop_sequence(stop_keys: list[str]) -> str:
    digest = hashlib.sha1('>'.join(stop_keys).encode('utf-8')).hexdigest()
    return digest[:16]


def _first_non_empty(values) -> str | None:
    for value in values:
        if pd.notna(value):
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


def _parse_uic_from_gtfs_stop_id(stop_id: object) -> str | None:
    if pd.isna(stop_id):
        return None
    prefix = str(stop_id).strip().split(':', 1)[0]
    return prefix if prefix.isdigit() else None


def _atlas_itinerary_sequence_key(stop_id: str, sloid: object, original_stop_id: object) -> str:
    uic_number = _parse_uic_from_gtfs_stop_id(original_stop_id) or _parse_uic_from_gtfs_stop_id(stop_id)
    if uic_number:
        return f'uic:{uic_number}'
    if pd.notna(sloid):
        return str(sloid)
    return f'gtfs:{stop_id}'


def _atlas_itinerary_bucket_key(
    representative_headsign: str | None,
    trip_short_name: str | None,
    fallback_pattern_hash: str,
) -> str:
    bucket_value = _first_non_empty([representative_headsign, trip_short_name])
    if bucket_value is None:
        return fallback_pattern_hash
    return bucket_value


def _merge_atlas_stop_row(existing_row: dict[str, object], new_row: dict[str, object]) -> None:
    for field_name in (
        'stop_id',
        'sloid',
        'mapping_method',
        'stop_name',
        'platform_code',
        'original_stop_id',
        'location_type',
        'parent_station',
        'canonical_stop_key',
        'uic_number',
    ):
        if existing_row.get(field_name) is None and new_row.get(field_name) is not None:
            existing_row[field_name] = new_row[field_name]
    existing_row['sloid_variants'].update(new_row.get('sloid_variants') or set())


def _build_stop_meta_lookup(gtfs_data) -> dict[str, dict[str, object]]:
    if not gtfs_data or not isinstance(gtfs_data, dict) or 'stops' not in gtfs_data:
        return {}
    columns = ['stop_id', 'stop_name', 'platform_code', 'original_stop_id', 'location_type', 'parent_station']
    stop_meta = gtfs_data['stops'][columns].drop_duplicates(subset=['stop_id'])
    return {
        str(row['stop_id']): row
        for row in stop_meta.to_dict(orient='records')
        if pd.notna(row.get('stop_id'))
    }


def _build_match_lookup(integrated_data: pd.DataFrame) -> dict[str, dict[str, object]]:
    if integrated_data is None or integrated_data.empty:
        return {}
    match_rows = integrated_data[['stop_id', 'sloid', 'match_method']].drop_duplicates(subset=['stop_id'])
    return {
        str(row['stop_id']): row
        for row in match_rows.to_dict(orient='records')
        if pd.notna(row.get('stop_id'))
    }


def _build_trip_lookup(gtfs_data) -> dict[str, dict[str, object]]:
    if not gtfs_data or not isinstance(gtfs_data, dict) or 'trips' not in gtfs_data:
        return {}
    trip_columns = ['trip_id', 'route_id', 'direction_id', 'trip_headsign', 'trip_short_name', 'shape_id']
    trips = gtfs_data['trips'][trip_columns].drop_duplicates(subset=['trip_id'])
    return {
        str(row['trip_id']): row
        for row in trips.to_dict(orient='records')
        if pd.notna(row.get('trip_id'))
    }


def _iter_trip_groups_from_staged_stop_times(trip_stop_times_path: str, chunk_size: int = 500000):
    if not trip_stop_times_path or not os.path.exists(trip_stop_times_path):
        return

    carryover = None
    chunks_seen = 0
    for chunk in pd.read_csv(
        trip_stop_times_path,
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
        chunksize=chunk_size,
        low_memory=False,
    ):
        chunks_seen += 1
        if carryover is not None:
            chunk = pd.concat([carryover, chunk], ignore_index=True)
            carryover = None
        if chunk.empty:
            if chunks_seen % 10 == 0:
                print(f"ATLAS itineraries: replayed {chunks_seen} staged stop-time chunks…")
            continue

        last_trip_id = chunk.iloc[-1]['trip_id']
        last_trip_mask = chunk['trip_id'] == last_trip_id
        if last_trip_mask.all():
            carryover = chunk
            if chunks_seen % 10 == 0:
                print(f"ATLAS itineraries: replayed {chunks_seen} staged stop-time chunks…")
            continue

        current_chunk = chunk.loc[~last_trip_mask].copy()
        carryover = chunk.loc[last_trip_mask].copy()

        for trip_id, trip_group in current_chunk.groupby('trip_id', sort=False):
            yield str(trip_id), trip_group.sort_values(by=['stop_sequence', 'stop_id']).reset_index(drop=True)

        if chunks_seen % 10 == 0:
            print(f"ATLAS itineraries: replayed {chunks_seen} staged stop-time chunks…")

    if carryover is not None and not carryover.empty:
        for trip_id, trip_group in carryover.groupby('trip_id', sort=False):
            yield str(trip_id), trip_group.sort_values(by=['stop_sequence', 'stop_id']).reset_index(drop=True)


def _build_atlas_itinerary_frames(
    gtfs_data,
    integrated_data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if integrated_data is None or integrated_data.empty:
        return pd.DataFrame(), pd.DataFrame()

    match_lookup = _build_match_lookup(integrated_data)
    stop_meta_lookup = _build_stop_meta_lookup(gtfs_data)
    trip_lookup = _build_trip_lookup(gtfs_data)

    direction_lookup = {}
    if gtfs_data and isinstance(gtfs_data, dict) and 'route_directions' in gtfs_data:
        direction_lookup = {
            (str(row['route_id']), _safe_direction_id(row.get('direction_id'))): row.get('direction')
            for row in gtfs_data['route_directions'].to_dict(orient='records')
            if pd.notna(row.get('route_id'))
        }

    trip_stop_times_path = None
    if gtfs_data and isinstance(gtfs_data, dict):
        trip_stop_times_path = gtfs_data.get('trip_stop_times_path')

    if not trip_stop_times_path:
        fallback_columns = ['route_id', 'direction_id', 'stop_id', 'sloid', 'match_method']
        if 'direction' in integrated_data.columns:
            fallback_columns.append('direction')
        trip_calls = integrated_data[fallback_columns].copy()
        trip_calls['trip_id'] = (
            trip_calls['route_id'].astype(str)
            + ':'
            + trip_calls['direction_id'].apply(_safe_direction_id).fillna('na')
            + ':synthetic'
        )
        trip_calls['stop_sequence'] = trip_calls.groupby(['route_id', 'direction_id']).cumcount()
        if stop_meta_lookup:
            stop_meta = pd.DataFrame(stop_meta_lookup.values())
            trip_calls = trip_calls.merge(stop_meta, on='stop_id', how='left')
        else:
            for column_name in ['stop_name', 'platform_code', 'original_stop_id', 'location_type', 'parent_station']:
                trip_calls[column_name] = None
        trip_calls['trip_headsign'] = None
        trip_calls['trip_short_name'] = None
        trip_calls['shape_id'] = None
        trip_calls['direction_id'] = trip_calls['direction_id'].apply(_safe_direction_id)
        trip_calls['canonical_stop_key'] = trip_calls['sloid'].where(
            trip_calls['sloid'].notna(),
            'gtfs:' + trip_calls['stop_id'].astype(str),
        )

    itinerary_rows = {}
    itinerary_pattern_rows_by_key: dict[
        tuple[str, str | None, str],
        dict[str, dict[str, object]],
    ] = {}

    if trip_stop_times_path:
        trip_groups = _iter_trip_groups_from_staged_stop_times(trip_stop_times_path)
    else:
        if trip_calls.empty:
            return pd.DataFrame(), pd.DataFrame()
        trip_groups = (
            (str(trip_id), trip_group.sort_values(by=['stop_sequence', 'stop_id']).reset_index(drop=True))
            for trip_id, trip_group in trip_calls.groupby('trip_id', sort=False)
        )

    processed_trip_count = 0
    processed_stop_call_count = 0
    progress_trip_interval = 10000

    for trip_id, ordered_calls in trip_groups:
        processed_trip_count += 1
        trip_meta = trip_lookup.get(trip_id)
        if trip_meta is None and trip_stop_times_path:
            continue

        route_id = str(trip_meta['route_id']) if trip_meta is not None else str(ordered_calls.iloc[0]['route_id'])
        direction_id = _safe_direction_id(trip_meta.get('direction_id') if trip_meta is not None else ordered_calls.iloc[0].get('direction_id'))
        representative_headsign = None
        trip_short_name = None
        shape_id = None
        if trip_meta is not None:
            representative_headsign = _first_non_empty([trip_meta.get('trip_headsign')])
            trip_short_name = _first_non_empty([trip_meta.get('trip_short_name')])
            shape_id = _first_non_empty([trip_meta.get('shape_id')])

        sequence_stop_keys: list[str] = []
        stop_rows_for_itinerary: list[dict[str, object]] = []
        direction_values: list[object] = []
        for stop_row in ordered_calls.itertuples(index=False):
            stop_id = str(stop_row.stop_id)
            match_row = match_lookup.get(stop_id, {})
            stop_meta = stop_meta_lookup.get(stop_id, {})
            sloid = match_row.get('sloid')
            canonical_stop_key = sloid if pd.notna(sloid) else f'gtfs:{stop_id}'
            uic_number = _parse_uic_from_gtfs_stop_id(stop_meta.get('original_stop_id')) or _parse_uic_from_gtfs_stop_id(stop_id)
            sequence_stop_keys.append(_atlas_itinerary_sequence_key(stop_id, sloid, stop_meta.get('original_stop_id')))
            if hasattr(stop_row, 'direction'):
                direction_values.append(stop_row.direction)
            stop_rows_for_itinerary.append({
                'stop_sequence': int(stop_row.stop_sequence),
                'stop_id': stop_id,
                'sloid': sloid,
                'sloid_variants': {str(sloid)} if pd.notna(sloid) else set(),
                'mapping_method': match_row.get('match_method'),
                'stop_name': stop_meta.get('stop_name'),
                'platform_code': stop_meta.get('platform_code'),
                'original_stop_id': stop_meta.get('original_stop_id'),
                'location_type': stop_meta.get('location_type'),
                'parent_station': stop_meta.get('parent_station'),
                'canonical_stop_key': canonical_stop_key,
                'uic_number': uic_number,
            })

        if not stop_rows_for_itinerary:
            continue

        direction_label = (
            direction_lookup.get((route_id, direction_id))
            or _first_non_empty(direction_values)
            or representative_headsign
            or trip_short_name
        )
        fallback_pattern_hash = _hash_stop_sequence(sequence_stop_keys)
        itinerary_bucket_key = _atlas_itinerary_bucket_key(
            representative_headsign,
            trip_short_name,
            fallback_pattern_hash,
        )
        itinerary_key = (route_id, direction_id, itinerary_bucket_key)
        atlas_itinerary_id = f"{route_id}:{direction_id or 'na'}:{itinerary_bucket_key}"

        existing_row = itinerary_rows.get(itinerary_key)
        if existing_row is None:
            itinerary_rows[itinerary_key] = {
                'atlas_itinerary_id': atlas_itinerary_id,
                'atlas_line_id': route_id,
                'direction_id': direction_id,
                'direction_label': direction_label,
                'representative_headsign': representative_headsign,
                'trip_count': 1,
                'shape_id': None,
                'headsign_or_pattern_hash': itinerary_bucket_key,
            }
        else:
            existing_row['trip_count'] += 1
            if existing_row['representative_headsign'] is None and representative_headsign is not None:
                existing_row['representative_headsign'] = representative_headsign
            if existing_row['direction_label'] is None and direction_label is not None:
                existing_row['direction_label'] = direction_label

        pattern_candidates = itinerary_pattern_rows_by_key.setdefault(itinerary_key, {})
        pattern_candidate = pattern_candidates.get(fallback_pattern_hash)
        if pattern_candidate is None:
            pattern_candidates[fallback_pattern_hash] = {
                'trip_count': 1,
                'stop_rows': stop_rows_for_itinerary,
                'uic_sequence': [k.replace('uic:', '') for k in sequence_stop_keys]
            }
            processed_stop_call_count += len(stop_rows_for_itinerary)
        else:
            pattern_candidate['trip_count'] += 1
            for existing_stop_row, stop_row in zip(pattern_candidate['stop_rows'], stop_rows_for_itinerary):
                _merge_atlas_stop_row(existing_stop_row, stop_row)

        if processed_trip_count % progress_trip_interval == 0:
            print(
                "ATLAS itineraries: processed "
                f"{processed_trip_count:,} trips, "
                f"{len(itinerary_rows):,} unique itineraries, "
                f"{processed_stop_call_count:,} emitted stop calls…"
            )

    itineraries_df = pd.DataFrame(itinerary_rows.values())
    if itineraries_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    print(
        "ATLAS itineraries: completed reduction with "
        f"{processed_trip_count:,} trips, "
        f"{len(itinerary_rows):,} unique itineraries, "
        f"{processed_stop_call_count:,} emitted stop calls"
    )

    itinerary_stop_rows: list[dict[str, object]] = []
    for itinerary_key, pattern_candidates in itinerary_pattern_rows_by_key.items():
        atlas_itinerary_id = itinerary_rows[itinerary_key]['atlas_itinerary_id']
        _, selected_pattern = max(
            pattern_candidates.items(),
            key=lambda item: (
                int(item[1]['trip_count']),
                len(item[1]['stop_rows']),
                item[0],
            ),
        )
        itinerary_rows[itinerary_key]['shape_id'] = ">".join(selected_pattern['uic_sequence'])
        stop_rows = selected_pattern['stop_rows']
        for stop_row in stop_rows:
            itinerary_stop_rows.append({
                'atlas_itinerary_id': atlas_itinerary_id,
                'stop_sequence': stop_row['stop_sequence'],
                'stop_id': stop_row['stop_id'],
                'sloid': stop_row['sloid'],
                'sloid_variants': json.dumps(sorted(stop_row['sloid_variants'])) if stop_row['sloid_variants'] else None,
                'mapping_method': stop_row['mapping_method'],
                'stop_name': stop_row['stop_name'],
                'platform_code': stop_row['platform_code'],
                'original_stop_id': stop_row['original_stop_id'],
                'location_type': stop_row['location_type'],
                'parent_station': stop_row['parent_station'],
                'canonical_stop_key': stop_row['canonical_stop_key'],
                'uic_number': stop_row['uic_number'],
            })

    itinerary_stop_calls_df = pd.DataFrame(itinerary_stop_rows)
    itineraries_df = itineraries_df.sort_values(by=['atlas_line_id', 'direction_id', 'atlas_itinerary_id']).reset_index(drop=True)
    itinerary_stop_calls_df = itinerary_stop_calls_df.sort_values(by=['atlas_itinerary_id', 'stop_sequence']).reset_index(drop=True)
    return itineraries_df, itinerary_stop_calls_df


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

    # Extract distinct routes / line families
    routes_df = integrated_data[['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type']].drop_duplicates(subset=['route_id'])
    routes_df['route_id_normalized'] = routes_df['route_id'].apply(lambda x: _normalize_route_id_for_matching(str(x)) if pd.notna(x) else None)

    atlas_line_families_df = routes_df.rename(columns={'route_id': 'atlas_line_id'})[
        ['atlas_line_id', 'agency_id', 'route_id_normalized', 'route_short_name', 'route_long_name', 'route_desc', 'route_type']
    ]
    atlas_line_families_out = os.path.join(out_dir, "atlas_line_families.csv")
    atlas_line_families_df.to_csv(atlas_line_families_out, index=False)
    print(f"ATLAS line families: wrote {len(atlas_line_families_df):,} rows to {atlas_line_families_out}")

    atlas_itineraries_df, atlas_itinerary_stop_calls_df = _build_atlas_itinerary_frames(gtfs_data, integrated_data)
    atlas_itineraries_out = os.path.join(out_dir, "atlas_itineraries.csv")
    atlas_itinerary_stop_calls_out = os.path.join(out_dir, "atlas_itinerary_stop_calls.csv")
    atlas_itineraries_df.to_csv(atlas_itineraries_out, index=False)
    atlas_itinerary_stop_calls_df.to_csv(atlas_itinerary_stop_calls_out, index=False)
    print(f"ATLAS itineraries: wrote {len(atlas_itineraries_df):,} rows to {atlas_itineraries_out}")
    print(f"ATLAS itinerary stop calls: wrote {len(atlas_itinerary_stop_calls_df):,} rows to {atlas_itinerary_stop_calls_out}")


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

