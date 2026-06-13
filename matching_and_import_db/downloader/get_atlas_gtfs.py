"""GTFS data download and processing module."""
import hashlib
import math
import os
import zipfile
import requests
import numpy as np
import pandas as pd
import shutil
from typing import Dict, Set

from .geo_utils import filter_points_in_switzerland


COORD_PROXIMITY_MAX_DISTANCE_M = 0.5
_COORD_BUCKET_METERS_PER_DEG_LAT = 111_320.0
_COORD_BUCKET_METERS_PER_DEG_LON = _COORD_BUCKET_METERS_PER_DEG_LAT * math.cos(math.radians(46.8))
GTFS_DB_STOPS_CACHE_PATH = os.path.join('data', 'processed', 'gtfs_stops_raw.csv')
GTFS_DB_STATE_CACHE_PATH = os.path.join('data', 'processed', 'gtfs_stop_identity_resolution.csv')
GTFS_TRIP_STOP_TIMES_STAGE_FILENAME = 'swiss_trip_stop_times.csv'
SWISS_UIC_PREFIX = '85'


def _normalize_optional_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_platform_code(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    alias_map = {
        '10000': '1',
        '10001': '2',
    }
    if normalized in alias_map:
        return alias_map[normalized]
    stripped = normalized.lstrip('0')
    return stripped or normalized


def _derive_identity_level(stop_row: dict[str, object]) -> str:
    location_type = _normalize_optional_text(stop_row.get('location_type'))
    if location_type == '1':
        return 'station'
    if _normalize_platform_code(stop_row.get('platform_code')) or _normalize_optional_text(stop_row.get('normalized_local_ref')):
        return 'platform'
    if _normalize_optional_text(stop_row.get('parent_station')):
        return 'child_stop'
    return 'stop'


def _confidence_for_resolution_method(method: str | None) -> float:
    if method == 'original_stop_id':
        return 1.0
    if method == 'uic_platform':
        return 0.95
    if method == 'coordinate_proximity':
        return 0.85
    if method == 'unique_number':
        return 0.6
    return 0.0


def _hash_trip_pattern(stop_ids: list[str]) -> str:
    digest = hashlib.sha1('>'.join(stop_ids).encode('utf-8')).hexdigest()
    return digest[:16]


def _build_gtfs_atlas_stats(mapping_stats: Dict[str, object]) -> Dict[str, object]:
    atlas_total = int(mapping_stats.get('total_atlas_sloids') or 0)
    atlas_touched = int(mapping_stats.get('touched_atlas_sloids') or 0)
    gtfs_total = int(mapping_stats.get('total_gtfs_stop_ids') or 0)
    gtfs_matched = int(mapping_stats.get('matched_gtfs_stop_ids') or 0)
    gtfs_unmatched = int(mapping_stats.get('unmatched_gtfs_stop_ids') or 0)

    return {
        'algorithm_version': mapping_stats.get('algorithm_version'),
        'atlas': {
            'total': atlas_total,
            'touched_by_gtfs_routes': atlas_touched,
            'coverage_percent': round((atlas_touched / atlas_total) * 100, 1) if atlas_total > 0 else 0.0,
        },
        'gtfs_stop_ids': {
            'total': gtfs_total,
            'matched_to_atlas': gtfs_matched,
            'unmatched': gtfs_unmatched,
            'coverage_percent': round((gtfs_matched / gtfs_total) * 100, 2) if gtfs_total > 0 else 0.0,
        },
        'assignments': {
            'original_stop_id': int(mapping_stats.get('original_stop_id_assignments') or 0),
            'strict': int(mapping_stats.get('strict_assignments') or 0),
            'coordinate_proximity': int(mapping_stats.get('coordinate_proximity_assignments') or 0),
            'unique_number_fallback': int(mapping_stats.get('unique_number_fallback_assignments') or 0),
            'total': int(mapping_stats.get('total_assignments') or 0),
        },
        'cardinality': {
            'stop_to_sloid': mapping_stats.get('stop_to_sloid') or {},
            'sloid_to_stop': mapping_stats.get('sloid_to_stop') or {},
        },
        'coordinate_proximity': {
            'distance_threshold_m': float(mapping_stats.get('coordinate_proximity_distance_threshold_m') or 0.0),
            'candidate_pairs': int(mapping_stats.get('coordinate_proximity_candidate_pairs') or 0),
            'candidate_gtfs_stop_ids': int(mapping_stats.get('coordinate_proximity_candidate_gtfs_stop_ids') or 0),
            'candidate_atlas_sloids': int(mapping_stats.get('coordinate_proximity_candidate_atlas_sloids') or 0),
            'assignments': int(mapping_stats.get('coordinate_proximity_assignments') or 0),
            'conflicting_gtfs_stop_ids': int(mapping_stats.get('coordinate_proximity_conflicting_gtfs_stop_ids') or 0),
            'conflicting_atlas_sloids': int(mapping_stats.get('coordinate_proximity_conflicting_atlas_sloids') or 0),
        },
        'unmatched_reasons': mapping_stats.get('unmatched_reasons') or {},
    }


def _build_coordinate_proximity_matches(
    gtfs_remaining: pd.DataFrame,
    atlas_data: pd.DataFrame,
    max_distance_m: float = COORD_PROXIMITY_MAX_DISTANCE_M,
) -> tuple[pd.DataFrame, Dict[str, int | float]]:
    empty_matches = pd.DataFrame({
        'stop_id': pd.Series(dtype='object'),
        'sloid': pd.Series(dtype='object'),
        'match_method': pd.Series(dtype='object'),
        'distance_m': pd.Series(dtype='float64'),
    })
    empty_stats: Dict[str, int | float] = {
        'coordinate_proximity_distance_threshold_m': float(max_distance_m),
        'coordinate_proximity_candidate_pairs': 0,
        'coordinate_proximity_candidate_gtfs_stop_ids': 0,
        'coordinate_proximity_candidate_atlas_sloids': 0,
        'coordinate_proximity_assignments': 0,
        'coordinate_proximity_conflicting_gtfs_stop_ids': 0,
        'coordinate_proximity_conflicting_atlas_sloids': 0,
    }

    if gtfs_remaining.empty or atlas_data.empty:
        return empty_matches, empty_stats

    gtfs_coords = gtfs_remaining[['stop_id', 'uic_number', 'stop_lat', 'stop_lon']].copy()
    gtfs_coords['stop_lat'] = pd.to_numeric(gtfs_coords['stop_lat'], errors='coerce')
    gtfs_coords['stop_lon'] = pd.to_numeric(gtfs_coords['stop_lon'], errors='coerce')
    gtfs_coords = gtfs_coords.dropna(subset=['stop_id', 'uic_number', 'stop_lat', 'stop_lon'])

    atlas_coords = atlas_data[['sloid', 'number', 'lat', 'lon']].copy()
    atlas_coords['lat'] = pd.to_numeric(atlas_coords['lat'], errors='coerce')
    atlas_coords['lon'] = pd.to_numeric(atlas_coords['lon'], errors='coerce')
    atlas_coords = atlas_coords.dropna(subset=['sloid', 'number', 'lat', 'lon'])

    if gtfs_coords.empty or atlas_coords.empty:
        return empty_matches, empty_stats

    relevant_numbers = set(gtfs_coords['uic_number'].astype(str).unique())
    atlas_coords = atlas_coords[atlas_coords['number'].astype(str).isin(relevant_numbers)].copy()
    if atlas_coords.empty:
        return empty_matches, empty_stats

    gtfs_coords['bucket_x'] = (gtfs_coords['stop_lon'].astype(float) * _COORD_BUCKET_METERS_PER_DEG_LON / max_distance_m).round().astype('int64')
    gtfs_coords['bucket_y'] = (gtfs_coords['stop_lat'].astype(float) * _COORD_BUCKET_METERS_PER_DEG_LAT / max_distance_m).round().astype('int64')
    atlas_coords['bucket_x'] = (atlas_coords['lon'].astype(float) * _COORD_BUCKET_METERS_PER_DEG_LON / max_distance_m).round().astype('int64')
    atlas_coords['bucket_y'] = (atlas_coords['lat'].astype(float) * _COORD_BUCKET_METERS_PER_DEG_LAT / max_distance_m).round().astype('int64')

    offsets = pd.DataFrame(
        [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)],
        columns=['bucket_dx', 'bucket_dy'],
    )
    gtfs_expanded = (
        gtfs_coords.assign(_merge_key=1)
        .merge(offsets.assign(_merge_key=1), on='_merge_key', how='left')
        .drop(columns=['_merge_key'])
    )
    gtfs_expanded['bucket_x'] = gtfs_expanded['bucket_x'] + gtfs_expanded['bucket_dx']
    gtfs_expanded['bucket_y'] = gtfs_expanded['bucket_y'] + gtfs_expanded['bucket_dy']

    candidates = gtfs_expanded.merge(
        atlas_coords,
        left_on=['uic_number', 'bucket_x', 'bucket_y'],
        right_on=['number', 'bucket_x', 'bucket_y'],
        how='inner',
        suffixes=('_gtfs', '_atlas'),
    )
    if candidates.empty:
        return empty_matches, empty_stats

    lat1 = np.radians(candidates['stop_lat'].astype(float))
    lon1 = np.radians(candidates['stop_lon'].astype(float))
    lat2 = np.radians(candidates['lat'].astype(float))
    lon2 = np.radians(candidates['lon'].astype(float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    candidates['distance_m'] = 6_371_000.0 * c

    valid_pairs = candidates.loc[candidates['distance_m'] <= max_distance_m, ['stop_id', 'sloid', 'distance_m']].drop_duplicates(subset=['stop_id', 'sloid'])
    if valid_pairs.empty:
        return empty_matches, empty_stats

    stop_candidate_counts = valid_pairs.groupby('stop_id', sort=False)['sloid'].nunique()
    sloid_candidate_counts = valid_pairs.groupby('sloid', sort=False)['stop_id'].nunique()

    conflict_free = valid_pairs[
        valid_pairs['stop_id'].map(stop_candidate_counts).eq(1)
        & valid_pairs['sloid'].map(sloid_candidate_counts).eq(1)
    ][['stop_id', 'sloid', 'distance_m']].drop_duplicates()
    conflict_free['match_method'] = 'coordinate_proximity'

    stats: Dict[str, int | float] = {
        'coordinate_proximity_distance_threshold_m': float(max_distance_m),
        'coordinate_proximity_candidate_pairs': int(len(valid_pairs)),
        'coordinate_proximity_candidate_gtfs_stop_ids': int(valid_pairs['stop_id'].nunique()),
        'coordinate_proximity_candidate_atlas_sloids': int(valid_pairs['sloid'].nunique()),
        'coordinate_proximity_assignments': int(len(conflict_free)),
        'coordinate_proximity_conflicting_gtfs_stop_ids': int((stop_candidate_counts > 1).sum()),
        'coordinate_proximity_conflicting_atlas_sloids': int((sloid_candidate_counts > 1).sum()),
    }
    return conflict_free, stats


def parse_gtfs_stop_ids(gtfs_stops: pd.DataFrame) -> pd.DataFrame:
    """Parse GTFS stop identifiers into reusable UIC/local-ref fields."""
    parsed = gtfs_stops.copy()
    stop_parts = parsed['stop_id'].fillna('').astype(str).str.split(':', n=2, expand=True)
    original_parts = parsed.get('original_stop_id', pd.Series(index=parsed.index, dtype='object')).fillna('').astype(str).str.split(':', n=2, expand=True)

    if stop_parts.shape[1] >= 1:
        stop_uic = stop_parts[0].where(stop_parts[0].str.fullmatch(r'\d+'), pd.NA)
    else:
        stop_uic = pd.Series(pd.NA, index=parsed.index, dtype='object')
    parsed['uic_number'] = stop_uic
    if stop_parts.shape[1] >= 3:
        parsed['local_ref'] = stop_parts[2].where(stop_uic.notna(), pd.NA)
    else:
        parsed['local_ref'] = None

    if original_parts.shape[1] >= 1:
        original_uic = original_parts[0].where(original_parts[0].str.fullmatch(r'\d+'), pd.NA)
        parsed['uic_number'] = original_uic.where(original_uic.notna(), parsed['uic_number'])
    if original_parts.shape[1] >= 3:
        original_local_ref = original_parts[2].replace('', pd.NA)
        # Only use original_local_ref if the original string was actually a UIC-based ID
        original_local_ref = original_local_ref.where(original_uic.notna(), pd.NA)
        parsed['local_ref'] = original_local_ref.where(original_local_ref.notna(), parsed['local_ref'])

    didok_uic = parsed.get('didok', pd.Series(index=parsed.index, dtype='object')).fillna('').astype(str)
    didok_uic = didok_uic.where(didok_uic.str.fullmatch(r'\d+'), pd.NA)
    parsed['uic_number'] = didok_uic.where(didok_uic.notna(), parsed['uic_number'])

    parsed['platform_code'] = parsed.get('platform_code')
    parsed['stop_code'] = parsed.get('stop_code')
    parsed['normalized_local_ref'] = parsed['local_ref'].map(_normalize_platform_code)
    parsed['normalized_local_ref'] = parsed['normalized_local_ref'].where(
        parsed['normalized_local_ref'].notna(),
        parsed['platform_code'].map(_normalize_platform_code),
    )
    parsed['uic_number'] = parsed['uic_number'].fillna(parsed.get('stop_code')).astype(str)
    parsed['uic_number'] = parsed['uic_number'].replace({'None': pd.NA, 'nan': pd.NA})
    return parsed


def _select_swiss_gtfs_stops(all_stops: pd.DataFrame) -> pd.DataFrame:
    """Return Swiss GTFS stops using all known UIC/DIDOK identifier columns."""
    required_columns = {'stop_id', 'original_stop_id', 'didok', 'stop_lat', 'stop_lon'}
    missing_columns = sorted(required_columns - set(all_stops.columns))
    if missing_columns:
        raise RuntimeError(f"GTFS stops.txt missing required columns for Swiss stop filtering: {missing_columns}")

    swiss_uic_mask = (
        all_stops['didok'].fillna('').astype(str).str.startswith(SWISS_UIC_PREFIX)
        | all_stops['original_stop_id'].fillna('').astype(str).str.startswith(SWISS_UIC_PREFIX)
        | all_stops['stop_id'].fillna('').astype(str).str.startswith(SWISS_UIC_PREFIX)
    )
    prefixed = all_stops[swiss_uic_mask].copy()
    swiss_stops = filter_points_in_switzerland(prefixed, lat_col='stop_lat', lon_col='stop_lon')
    if swiss_stops.empty:
        raise RuntimeError(
            "GTFS Swiss stop filter produced 0 stops. Expected Swiss UIC/DIDOK values "
            "starting with '85' in one of didok, original_stop_id, or stop_id."
        )
    print(
        f"GTFS: filtered to {len(swiss_stops):,} Swiss stops inside CH border "
        f"(from {len(prefixed):,} Swiss UIC/DIDOK rows)"
    )
    return swiss_stops


def download_and_extract_gtfs(gtfs_url):
    """Download and extract GTFS data to a clean folder.

    Performance note:
      - GTFS ZIPs are large; extracting everything is slow and wastes disk.
      - We only extract the files required by this project:
          stops.txt, stop_times.txt, trips.txt, routes.txt
    """
    gtfs_folder = os.path.join("data", "raw", "gtfs")
    os.makedirs(gtfs_folder, exist_ok=True)

    required_files = {"stops.txt", "stop_times.txt", "trips.txt", "routes.txt"}

    # Download ZIP to disk (streamed) to avoid holding multi-GB content in RAM
    zip_path = os.path.join(gtfs_folder, "gtfs.zip")
    zip_tmp_path = zip_path + ".part"
    print(f"GTFS: downloading from {gtfs_url}")
    with requests.get(gtfs_url, allow_redirects=True, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(zip_tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(zip_tmp_path, zip_path)

    print("GTFS: download successful, extracting required files…")
    extracted = 0
    with zipfile.ZipFile(zip_path) as z:
        # Build a mapping basename -> member path (GTFS may contain a folder prefix)
        basename_to_member: Dict[str, str] = {}
        for member in z.namelist():
            base = os.path.basename(member)
            if base in required_files and base not in basename_to_member:
                basename_to_member[base] = member

        missing = sorted(required_files - set(basename_to_member.keys()))
        if missing:
            raise RuntimeError(f"GTFS ZIP missing required files: {missing}")

        # Clear any previous versions of the required files
        for base in required_files:
            out_path = os.path.join(gtfs_folder, base)
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except OSError:
                pass

        # Extract only what we need
        for base, member in basename_to_member.items():
            out_path = os.path.join(gtfs_folder, base)
            with z.open(member) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            extracted += 1

    # Optionally remove the downloaded ZIP to save disk space
    try:
        os.remove(zip_path)
    except OSError:
        pass

    print(f"GTFS: extracted {extracted} required files to {gtfs_folder}")
    return gtfs_folder


def load_gtfs_data_streaming(gtfs_folder: str):
    """Load GTFS data in a memory-lean streaming fashion (optimized).

    Key optimizations vs the previous implementation:
      - Extract-only download step (handled in download_and_extract_gtfs)
      - Single pass over stop_times.txt (instead of two full passes)
      - No per-chunk reconstruction of trip join tables

        Returns a dict with keys:
            - stops: Swiss stops DataFrame
            - trips: filtered trips DataFrame (only trips that touch Swiss stops)
            - routes: filtered routes DataFrame (only routes referenced by filtered trips)
            - stop_route_unique: DataFrame[stop_id, route_id, direction_id]
            - route_directions: DataFrame[route_id, direction] (first stop → last stop, all stops including cross-border)
            - trip_stop_times_path: CSV path with filtered Swiss trip stop-times
            - trip_stop_times_row_count: number of staged Swiss trip stop-time rows
    """
    print("GTFS: loading data (optimized streaming, single pass over stop_times)…")

    stops_path = os.path.join(gtfs_folder, "stops.txt")
    stop_times_path = os.path.join(gtfs_folder, "stop_times.txt")
    trips_path = os.path.join(gtfs_folder, "trips.txt")
    routes_path = os.path.join(gtfs_folder, "routes.txt")

    # Load Swiss stops (prefix + Swiss polygon)
    stop_columns = {
        'stop_id',
        'stop_name',
        'stop_lat',
        'stop_lon',
        'stop_code',
        'platform_code',
        'original_stop_id',
        'location_type',
        'parent_station',
        'didok',
    }
    all_stops = pd.read_csv(
        stops_path,
        usecols=lambda column_name: column_name in stop_columns,
        dtype={
            'stop_id': str,
            'stop_name': str,
            'stop_code': str,
            'platform_code': str,
            'original_stop_id': str,
            'parent_station': str,
        },
        low_memory=False,
    )
    for optional_column in ('stop_code', 'platform_code', 'original_stop_id', 'location_type', 'parent_station', 'didok'):
        if optional_column not in all_stops.columns:
            all_stops[optional_column] = pd.NA
    all_stops['stop_lat'] = pd.to_numeric(all_stops['stop_lat'], errors='coerce')
    all_stops['stop_lon'] = pd.to_numeric(all_stops['stop_lon'], errors='coerce')
    all_stops['location_type'] = pd.to_numeric(all_stops['location_type'], errors='coerce').astype('Int64')
    swiss_stops = _select_swiss_gtfs_stops(all_stops)
    swiss_stop_ids: Set[str] = set(swiss_stops['stop_id'].astype(str))

    # Load trips once; filter later to relevant_trip_ids found via stop_times streaming
    trip_columns = {
        'trip_id',
        'route_id',
        'direction_id',
        'trip_headsign',
        'trip_short_name',
        'shape_id',
    }
    trips_all = pd.read_csv(
        trips_path,
        usecols=lambda column_name: column_name in trip_columns,
        dtype={
            'trip_id': str,
            'route_id': str,
            'trip_headsign': str,
            'trip_short_name': str,
            'shape_id': str,
        },
        low_memory=False,
    )
    for optional_column in ('direction_id', 'trip_headsign', 'trip_short_name', 'shape_id'):
        if optional_column not in trips_all.columns:
            trips_all[optional_column] = pd.NA
    trips_all['direction_id'] = pd.to_numeric(trips_all['direction_id'], errors='coerce').astype('Int64')
    # Pandas Series maps are faster than rebuilding a join table per chunk
    # Note: indexing by trip_id strings preserves exact join semantics while avoiding per-chunk merges.
    route_by_trip = pd.Series(trips_all['route_id'].values, index=trips_all['trip_id'].astype(str))
    dir_by_trip = pd.Series(trips_all['direction_id'].values, index=trips_all['trip_id'].astype(str))

    # Streaming over stop_times: collect
    #  - relevant_trip_ids (trips touching Swiss stops)
    #  - trip termini among all stops (stop_sequence min/max per trip, for direction labels)
    #  - unique (stop_id, route_id, direction_id) combinations
    #
    # Optimization: no per-row Python loops inside the hot path.
    # We accumulate small DataFrames per chunk and do a single final reduce.
    relevant_trip_ids: Set[str] = set()
    global_terminus_first_parts: list = []  # (trip_id, stop_id, stop_sequence) — first stop per trip per chunk (all stops, not Swiss-only)
    global_terminus_last_parts: list = []   # same for last
    stop_route_parts: list = []       # unique (stop_id, route_id, direction_id) slices
    trip_stop_times_path = os.path.join(gtfs_folder, GTFS_TRIP_STOP_TIMES_STAGE_FILENAME)
    try:
        os.remove(trip_stop_times_path)
    except FileNotFoundError:
        pass
    trip_stop_times_header_written = False
    trip_stop_times_row_count = 0

    chunk_size = 500000
    chunks_seen = 0
    for chunk in pd.read_csv(
        stop_times_path,
        usecols=['trip_id', 'stop_id', 'stop_sequence'],
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
        chunksize=chunk_size,
        low_memory=False,
    ):
        if not swiss_stop_ids:
            continue

        # Track global termini from ALL stops for direction labels (not Swiss-only)
        grp_all = chunk.groupby('trip_id', sort=False)['stop_sequence']
        global_terminus_first_parts.append(chunk.loc[grp_all.idxmin(), ['trip_id', 'stop_id', 'stop_sequence']])
        global_terminus_last_parts.append(chunk.loc[grp_all.idxmax(), ['trip_id', 'stop_id', 'stop_sequence']])

        mask = chunk['stop_id'].isin(swiss_stop_ids)
        if not mask.any():
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: streamed {chunks_seen} chunks…")
            continue

        swiss_chunk = chunk.loc[mask, ['trip_id', 'stop_id', 'stop_sequence']]
        if swiss_chunk.empty:
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: streamed {chunks_seen} chunks…")
            continue

        # trips touching Swiss stops — use fast numpy unique array directly
        relevant_trip_ids.update(swiss_chunk['trip_id'].unique())
        swiss_chunk.to_csv(
            trip_stop_times_path,
            mode='a',
            index=False,
            header=not trip_stop_times_header_written,
        )
        trip_stop_times_header_written = True
        trip_stop_times_row_count += len(swiss_chunk)


        # Build unique (stop_id, route_id, direction_id) — vectorized map + drop_duplicates
        route_ids = swiss_chunk['trip_id'].map(route_by_trip)
        dir_ids = swiss_chunk['trip_id'].map(dir_by_trip)
        candidate = pd.DataFrame({
            'stop_id': swiss_chunk['stop_id'].values,
            'route_id': route_ids.values,
            'direction_id': dir_ids.values,
        }).dropna(subset=['route_id']).drop_duplicates()
        if not candidate.empty:
            stop_route_parts.append(candidate)

        chunks_seen += 1
        if chunks_seen % 20 == 0:
            print(f"  GTFS: streamed {chunks_seen} chunks…")

    # Filter trips to those we actually saw in stop_times among Swiss stops
    if relevant_trip_ids:
        trips_df = trips_all[trips_all['trip_id'].astype(str).isin(relevant_trip_ids)].copy()
    else:
        trips_df = pd.DataFrame(columns=['trip_id', 'route_id', 'direction_id', 'trip_headsign', 'trip_short_name', 'shape_id'])
    print(f"GTFS: loaded {len(trips_df):,} trips (filtered to relevant trips)")

    # Derive route_directions from per-trip global termini (first stop → last stop)
    # Final reduce: find the true global first/last stop per trip across all chunks,
    # then filter to only trips that touch Swiss stops (relevant_trip_ids).
    if global_terminus_first_parts and global_terminus_last_parts:
        stop_id_to_name = all_stops.set_index('stop_id')['stop_name'].to_dict()

        all_first = pd.concat(global_terminus_first_parts, ignore_index=True)
        all_last = pd.concat(global_terminus_last_parts, ignore_index=True)

        # Filter to relevant trips (those touching Swiss stops)
        all_first = all_first[all_first['trip_id'].isin(relevant_trip_ids)]
        all_last = all_last[all_last['trip_id'].isin(relevant_trip_ids)]

        # Keep the row with the globally minimum/maximum stop_sequence per trip
        global_first = all_first.loc[all_first.groupby('trip_id')['stop_sequence'].idxmin(), ['trip_id', 'stop_id']]
        global_last = all_last.loc[all_last.groupby('trip_id')['stop_sequence'].idxmax(), ['trip_id', 'stop_id']]

        merged = global_first.merge(global_last, on='trip_id', suffixes=('_first', '_last'))
        merged['route_id'] = merged['trip_id'].map(route_by_trip)
        merged['direction_id'] = merged['trip_id'].map(dir_by_trip)
        merged = merged.dropna(subset=['route_id'])
        merged['direction'] = (
            merged['stop_id_first'].map(stop_id_to_name).fillna('Unknown')
            + ' → '
            + merged['stop_id_last'].map(stop_id_to_name).fillna('Unknown')
        )
        route_directions = merged[['route_id', 'direction_id', 'direction']].drop_duplicates()
    else:
        route_directions = pd.DataFrame(columns=['route_id', 'direction_id', 'direction'])
    print(f"GTFS: extracted {len(route_directions):,} unique route direction strings (first→last)")

    # Final reduce: materialize the unique (stop_id, route_id, direction_id) table
    if stop_route_parts:
        stop_route_unique = pd.concat(stop_route_parts, ignore_index=True).drop_duplicates()
    else:
        stop_route_unique = pd.DataFrame(columns=['stop_id', 'route_id', 'direction_id'])
    print(f"GTFS: built {len(stop_route_unique):,} unique (stop_id, route_id, direction_id) triples")

    print(f"GTFS: staged {trip_stop_times_row_count:,} Swiss trip stop-time rows to {trip_stop_times_path}")

    # Load routes filtered to those we actually reference
    relevant_route_ids: Set[str] = set(trips_df['route_id'].dropna().astype(str).unique())
    if relevant_route_ids:
        all_routes = pd.read_csv(
            routes_path,
            usecols=['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type'],
            dtype={'route_id': str, 'agency_id': str, 'route_short_name': str, 'route_long_name': str, 'route_desc': str, 'route_type': str},
            low_memory=False,
        )
        swiss_routes = all_routes[all_routes['route_id'].astype(str).isin(relevant_route_ids)].copy()
    else:
        swiss_routes = pd.DataFrame(columns=['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type'])
    print(f"GTFS: loaded {len(swiss_routes):,} routes (filtered to referenced routes)")

    return {
        'stops': swiss_stops,
        'trips': trips_df,
        'routes': swiss_routes,
        'stop_route_unique': stop_route_unique,
        'route_directions': route_directions,
        'trip_stop_times_path': trip_stop_times_path if trip_stop_times_header_written else None,
        'trip_stop_times_row_count': trip_stop_times_row_count,
    }


def build_integrated_gtfs_data_streaming(
    gtfs_data_streaming: Dict[str, pd.DataFrame],
    traffic_points: pd.DataFrame,
    gtfs_payload: Dict[str, object] | None = None,
) -> pd.DataFrame:
    """Build the final integrated GTFS DataFrame using streaming outputs.

        Returns DataFrame with columns:
            ['stop_id', 'sloid', 'match_method', 'route_id', 'route_short_name', 'route_long_name', 'direction_id', 'direction']
    """
    gtfs_payload = gtfs_payload or build_gtfs_atlas_payload(gtfs_data_streaming, traffic_points)

    # stop_id, route_id, direction_id
    stop_route_unique = gtfs_data_streaming['stop_route_unique']
    # add route metadata
    route_enriched = stop_route_unique.merge(
        gtfs_data_streaming['routes'][['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type']],
        on='route_id', how='left'
    )
    # direction strings by route/direction_id
    route_directions = gtfs_data_streaming['route_directions']
    if not route_directions.empty:
        route_directions_unique = (
            route_directions
            .dropna(subset=['route_id'])
            .groupby(['route_id', 'direction_id'], as_index=False)['direction']
            .first()
        )
    else:
        route_directions_unique = route_directions

    import json
    stats_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'data', 'gtfs_atlas_stats.json'
    )
    os.makedirs(os.path.dirname(stats_path), exist_ok=True)
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(gtfs_payload['mapping_stats_export'], f, indent=2)

    # integrate
    linked_stops = gtfs_payload['gtfs_stops'].merge(gtfs_payload['matches'], on='stop_id', how='left')
    integrated = linked_stops.merge(route_enriched, on='stop_id', how='inner')
    integrated = integrated.merge(route_directions_unique, on=['route_id', 'direction_id'], how='left')

    # Remove any multiplicative duplicates that could have slipped through
    integrated = integrated.drop_duplicates(subset=['stop_id', 'sloid', 'route_id', 'direction_id'])

    cols = ['stop_id', 'sloid', 'match_method', 'route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type', 'direction_id', 'direction']
    integrated = integrated[cols].sort_values(by='sloid')
    return integrated


def build_gtfs_atlas_payload(gtfs_data_streaming: Dict[str, pd.DataFrame], traffic_points: pd.DataFrame) -> Dict[str, object]:
    """Return canonical GTFS stops, GTFS→ATLAS matches, and exported stats.

    The database importer and the route CSV/integration writers should consume
    this helper instead of rebuilding GTFS matching state separately.
    """
    gtfs_stops = parse_gtfs_stop_ids(gtfs_data_streaming['stops'])
    matches, mapping_stats = match_gtfs_to_atlas({'stops': gtfs_stops}, traffic_points, return_stats=True)
    return {
        'gtfs_stops': gtfs_stops,
        'matches': matches.copy(),
        'mapping_stats': mapping_stats,
        'mapping_stats_export': _build_gtfs_atlas_stats(mapping_stats),
    }


def build_gtfs_db_payload_rows(
    gtfs_payload: Dict[str, object],
    traffic_points: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    gtfs_stop_rows = []
    for stop in gtfs_payload['gtfs_stops'].to_dict(orient='records'):
        stop_id = _normalize_optional_text(stop.get('stop_id'))
        if not stop_id:
            continue

        stop_lat = _normalize_optional_float(stop.get('stop_lat'))
        stop_lon = _normalize_optional_float(stop.get('stop_lon'))
        if stop_lat is None or stop_lon is None:
            continue

        gtfs_stop_rows.append({
            'stop_id': stop_id,
            'stop_code': _normalize_optional_text(stop.get('stop_code')),
            'stop_name': _normalize_optional_text(stop.get('stop_name')),
            'platform_code': _normalize_optional_text(stop.get('platform_code')),
            'original_stop_id': _normalize_optional_text(stop.get('original_stop_id')),
            'location_type': _normalize_optional_text(stop.get('location_type')),
            'parent_station': _normalize_optional_text(stop.get('parent_station')),
            'uic_number': _normalize_optional_text(stop.get('uic_number')),
            'local_ref': _normalize_optional_text(stop.get('local_ref')),
            'normalized_local_ref': _normalize_optional_text(stop.get('normalized_local_ref')),
            'stop_lat': stop_lat,
            'stop_lon': stop_lon,
        })

    gtfs_stop_lookup = {row['stop_id']: row for row in gtfs_stop_rows}
    gtfs_uic_numbers = {
        row['uic_number']
        for row in gtfs_stop_rows
        if row.get('uic_number')
    }

    atlas_coords = traffic_points[['sloid', 'number']].copy()
    atlas_coords['atlas_lat'] = pd.to_numeric(traffic_points.get('wgs84North'), errors='coerce')
    atlas_coords['atlas_lon'] = pd.to_numeric(traffic_points.get('wgs84East'), errors='coerce')
    atlas_coords = atlas_coords.dropna(subset=['sloid', 'atlas_lat', 'atlas_lon'])
    atlas_coords['number'] = atlas_coords['number'].astype(str)
    if gtfs_uic_numbers:
        atlas_coords = atlas_coords[atlas_coords['number'].isin(gtfs_uic_numbers)].copy()

    atlas_stop_lookup = {}
    for atlas_row in atlas_coords.to_dict(orient='records'):
        sloid = _normalize_optional_text(atlas_row.get('sloid'))
        if not sloid or sloid in atlas_stop_lookup:
            continue
        atlas_stop_lookup[sloid] = {
            'atlas_lat': float(atlas_row['atlas_lat']),
            'atlas_lon': float(atlas_row['atlas_lon']),
        }

    gtfs_state_rows = []
    match_lookup = {}
    for match in gtfs_payload['matches'].to_dict(orient='records'):
        stop_id = _normalize_optional_text(match.get('stop_id'))
        sloid = _normalize_optional_text(match.get('sloid'))
        resolution_method = _normalize_optional_text(match.get('match_method'))
        if not stop_id or not resolution_method:
            continue
        match_lookup[stop_id] = {
            'resolved_sloid': sloid,
            'resolution_method': resolution_method,
            'distance_m': _normalize_optional_float(match.get('distance_m')),
        }

    for gtfs_stop in gtfs_stop_rows:
        stop_id = gtfs_stop['stop_id']
        match = match_lookup.get(stop_id, {})
        resolved_sloid = match.get('resolved_sloid')
        atlas_stop = atlas_stop_lookup.get(resolved_sloid) if resolved_sloid else None
        gtfs_state_rows.append({
            'stop_id': stop_id,
            'source_location_type': gtfs_stop.get('location_type'),
            'identity_level': _derive_identity_level(gtfs_stop),
            'resolved_sloid': resolved_sloid,
            'resolution_method': match.get('resolution_method') or 'unmatched',
            'confidence': _confidence_for_resolution_method(match.get('resolution_method')),
            'distance_m': match.get('distance_m'),
            'gtfs_stop_lat': gtfs_stop['stop_lat'],
            'gtfs_stop_lon': gtfs_stop['stop_lon'],
            'atlas_lat': atlas_stop['atlas_lat'] if atlas_stop else None,
            'atlas_lon': atlas_stop['atlas_lon'] if atlas_stop else None,
            'details_json': {
                'original_stop_id': gtfs_stop.get('original_stop_id'),
                'platform_code': gtfs_stop.get('platform_code'),
                'parent_station': gtfs_stop.get('parent_station'),
            },
        })

    return gtfs_stop_rows, gtfs_state_rows


def write_gtfs_db_payload_cache(
    gtfs_payload: Dict[str, object],
    traffic_points: pd.DataFrame,
    stops_cache_path: str = GTFS_DB_STOPS_CACHE_PATH,
    state_cache_path: str = GTFS_DB_STATE_CACHE_PATH,
) -> tuple[list[dict], list[dict]]:
    gtfs_stop_rows, gtfs_state_rows = build_gtfs_db_payload_rows(gtfs_payload, traffic_points)

    os.makedirs(os.path.dirname(stops_cache_path), exist_ok=True)
    pd.DataFrame(gtfs_stop_rows).to_csv(stops_cache_path, index=False)
    pd.DataFrame(gtfs_state_rows).to_csv(state_cache_path, index=False)
    return gtfs_stop_rows, gtfs_state_rows


# The normalize_route_id function is imported at module level when needed


def match_gtfs_to_atlas(gtfs_data, traffic_points, return_stats: bool = False):
    """Map GTFS stops to ATLAS SLOIDs using original_stop_id-first identity resolution.

    Resolution order:
        1) direct original_stop_id == sloid
        2) strict (uic_number, normalized_local_ref/platform_code) == (number, designation)
        3) same-UIC coordinate proximity within 0.5m
        4) unique-number fallback
    """
    print("Mapping stop_id GTFS → sloid ATLAS…")
    
    # GTFS stops are already filtered for Switzerland during loading
    gtfs_stops = parse_gtfs_stop_ids(gtfs_data['stops'])
    
    # Prepare ATLAS data
    atlas_columns = ['sloid', 'number', 'designation']
    if 'wgs84North' in traffic_points.columns:
        atlas_columns.append('wgs84North')
    if 'wgs84East' in traffic_points.columns:
        atlas_columns.append('wgs84East')
    atlas_data = traffic_points[atlas_columns].copy()
    atlas_data['number'] = atlas_data['number'].astype(str)
    atlas_data = atlas_data.dropna(subset=['sloid', 'number'])
    atlas_data['lat'] = pd.to_numeric(atlas_data.get('wgs84North'), errors='coerce')
    atlas_data['lon'] = pd.to_numeric(atlas_data.get('wgs84East'), errors='coerce')
    atlas_data['normalized_designation'] = atlas_data['designation'].map(_normalize_platform_code)

    direct_original_matches = pd.DataFrame(columns=['stop_id', 'sloid', 'match_method', 'distance_m'])
    original_stop_candidates = gtfs_stops[['stop_id', 'original_stop_id']].dropna(subset=['original_stop_id'])
    if not original_stop_candidates.empty:
        direct_original_matches = (
            original_stop_candidates
            .merge(atlas_data[['sloid']], left_on='original_stop_id', right_on='sloid', how='inner')
            [['stop_id', 'sloid']]
            .drop_duplicates()
        )
        if not direct_original_matches.empty:
            direct_original_matches['match_method'] = 'original_stop_id'
            direct_original_matches['distance_m'] = np.nan
    
    matched_stop_ids = set(direct_original_matches['stop_id'])
    remaining = gtfs_stops[~gtfs_stops['stop_id'].isin(matched_stop_ids)].copy()

    strict_matches = pd.DataFrame(columns=['stop_id', 'sloid', 'match_method', 'distance_m'])
    if not remaining.empty:
        strict_matches = pd.merge(
            remaining[['stop_id', 'uic_number', 'normalized_local_ref']].dropna(subset=['uic_number', 'normalized_local_ref']),
            atlas_data[['sloid', 'number', 'normalized_designation']],
            left_on=['uic_number', 'normalized_local_ref'],
            right_on=['number', 'normalized_designation'],
            how='inner'
        )[['stop_id', 'sloid']].drop_duplicates()
        if not strict_matches.empty:
            strict_matches['match_method'] = 'uic_platform'
            strict_matches['distance_m'] = np.nan

    matched_stop_ids |= set(strict_matches['stop_id'])
    remaining = gtfs_stops[~gtfs_stops['stop_id'].isin(matched_stop_ids)].copy()

    coordinate_matches, coordinate_stats = _build_coordinate_proximity_matches(remaining, atlas_data)

    matched_stop_ids |= set(coordinate_matches['stop_id'])
    remaining = gtfs_stops[~gtfs_stops['stop_id'].isin(matched_stop_ids)].copy()

    # Final fallback for remaining stops: unique ATLAS number only.
    atlas_counts = atlas_data.groupby('number', sort=False)['sloid'].nunique()
    unique_numbers = set(atlas_counts[atlas_counts == 1].index.astype(str))

    atlas_unique_lookup = (
        atlas_data[atlas_data['number'].astype(str).isin(unique_numbers)][['number', 'sloid']]
        .drop_duplicates(subset=['number'])
    )

    unique_fallback_matches = pd.DataFrame({
        'stop_id': pd.Series(dtype='object'),
        'sloid': pd.Series(dtype='object'),
        'match_method': pd.Series(dtype='object'),
        'distance_m': pd.Series(dtype='float64'),
    })
    if not remaining.empty and not atlas_unique_lookup.empty:
        unique_fallback_matches = (
            remaining[['stop_id', 'uic_number']]
            .merge(atlas_unique_lookup, left_on='uic_number', right_on='number', how='inner')
            [['stop_id', 'sloid']]
            .drop_duplicates()
        )
        unique_fallback_matches['match_method'] = 'unique_number'
        unique_fallback_matches['distance_m'] = np.nan

    match_frames = [
        frame
        for frame in (direct_original_matches, strict_matches, coordinate_matches, unique_fallback_matches)
        if not frame.empty
    ]
    if match_frames:
        combined = (
            pd.concat(match_frames, ignore_index=True)
            .drop_duplicates(subset=['stop_id', 'sloid'])
            .sort_values(by=['stop_id', 'sloid'])
        )
    else:
        combined = pd.DataFrame(columns=['stop_id', 'sloid', 'match_method', 'distance_m'])

    # Derive mapping quality stats for docs/UI.
    total_gtfs_stops = int(gtfs_stops['stop_id'].nunique())
    total_atlas_sloids = int(traffic_points['sloid'].dropna().nunique()) if 'sloid' in traffic_points.columns else 0
    matched_stop_ids_count = int(combined['stop_id'].nunique()) if not combined.empty else 0
    unmatched_total = max(total_gtfs_stops - matched_stop_ids_count, 0)
    touched_sloids = int(combined['sloid'].nunique()) if not combined.empty else 0

    if not combined.empty:
        stop_to_sloid = combined.groupby('stop_id', sort=False)['sloid'].nunique()
        sloid_to_stop = combined.groupby('sloid', sort=False)['stop_id'].nunique()
        stop_1_to_1 = int((stop_to_sloid == 1).sum())
        stop_1_to_many = int((stop_to_sloid > 1).sum())
        sloid_1_to_1 = int((sloid_to_stop == 1).sum())
        sloid_many_to_1 = int((sloid_to_stop > 1).sum())
    else:
        stop_1_to_1 = 0
        stop_1_to_many = 0
        sloid_1_to_1 = 0
        sloid_many_to_1 = 0

    atlas_numbers = set(atlas_data['number'].astype(str).unique())
    unmatched_candidates = gtfs_stops[~gtfs_stops['stop_id'].isin(set(combined['stop_id']))].copy()
    if unmatched_candidates.empty:
        unmatched_no_atlas_number = 0
        unmatched_non_unique_after_strict = 0
    else:
        unmatched_no_atlas_number = int((~unmatched_candidates['uic_number'].isin(atlas_numbers)).sum())
        unmatched_non_unique_after_strict = int(unmatched_total - unmatched_no_atlas_number)

    mapping_stats = {
        'algorithm_version': 'original_stop_id_plus_uic_platform_plus_coordinate_proximity_plus_unique_number',
        'total_gtfs_stop_ids': total_gtfs_stops,
        'matched_gtfs_stop_ids': matched_stop_ids_count,
        'unmatched_gtfs_stop_ids': unmatched_total,
        'total_atlas_sloids': total_atlas_sloids,
        'touched_atlas_sloids': touched_sloids,
        'gtfs_coverage_percent': round((matched_stop_ids_count / total_gtfs_stops * 100), 2) if total_gtfs_stops else 0.0,
        'atlas_coverage_percent': round((touched_sloids / total_atlas_sloids * 100), 2) if total_atlas_sloids else 0.0,
        'original_stop_id_assignments': int(len(direct_original_matches)),
        'strict_assignments': int(len(strict_matches)),
        'coordinate_proximity_assignments': int(len(coordinate_matches)),
        'unique_number_fallback_assignments': int(len(unique_fallback_matches)),
        'total_assignments': int(len(combined)),
        'coordinate_proximity_distance_threshold_m': float(coordinate_stats.get('coordinate_proximity_distance_threshold_m') or 0.0),
        'coordinate_proximity_candidate_pairs': int(coordinate_stats.get('coordinate_proximity_candidate_pairs') or 0),
        'coordinate_proximity_candidate_gtfs_stop_ids': int(coordinate_stats.get('coordinate_proximity_candidate_gtfs_stop_ids') or 0),
        'coordinate_proximity_candidate_atlas_sloids': int(coordinate_stats.get('coordinate_proximity_candidate_atlas_sloids') or 0),
        'coordinate_proximity_conflicting_gtfs_stop_ids': int(coordinate_stats.get('coordinate_proximity_conflicting_gtfs_stop_ids') or 0),
        'coordinate_proximity_conflicting_atlas_sloids': int(coordinate_stats.get('coordinate_proximity_conflicting_atlas_sloids') or 0),
        'stop_to_sloid': {
            'one_to_one': stop_1_to_1,
            'one_to_many': stop_1_to_many,
        },
        'sloid_to_stop': {
            'one_to_one': sloid_1_to_1,
            'many_to_one': sloid_many_to_1,
        },
        'unmatched_reasons': {
            'no_atlas_candidate_for_uic_number': unmatched_no_atlas_number,
            'non_unique_atlas_number_after_strict_miss': unmatched_non_unique_after_strict,
            'coordinate_proximity_conflicting_gtfs_stop_ids': int(coordinate_stats.get('coordinate_proximity_conflicting_gtfs_stop_ids') or 0),
            'coordinate_proximity_conflicting_atlas_sloids': int(coordinate_stats.get('coordinate_proximity_conflicting_atlas_sloids') or 0),
        },
    }

    if combined.empty:
        print("stop_id→sloid: no matches found")
        return (combined, mapping_stats) if return_stats else combined

    print(
        f"stop_id→sloid: original_stop_id = {len(direct_original_matches):,}, "
        f"uic_platform = {len(strict_matches):,}, "
        f"coordinate_proximity = {len(coordinate_matches):,}, "
        f"unique_fallback = {len(unique_fallback_matches):,}, total = {len(combined):,}"
    )
    return (combined, mapping_stats) if return_stats else combined
