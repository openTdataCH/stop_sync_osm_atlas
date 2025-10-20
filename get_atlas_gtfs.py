"""GTFS data download and processing module."""
import os
import io
import zipfile
import requests
import pandas as pd
from typing import Dict, Set, Tuple, Optional

from geo_utils import filter_points_in_switzerland


def download_and_extract_gtfs(gtfs_url):
    """Download and extract GTFS data to a clean folder."""
    gtfs_folder = "data/raw/gtfs"
    
    print(f"GTFS: downloading from {gtfs_url}")
    response = requests.get(gtfs_url, allow_redirects=True)
    response.raise_for_status()
    
    # Create clean directory
    os.makedirs(gtfs_folder, exist_ok=True)
    
    print("GTFS: download successful, extracting ZIP file…")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall(gtfs_folder)
        extracted_files = z.namelist()
        print(f"GTFS: extracted {len(extracted_files)} files to {gtfs_folder}")
    
    return gtfs_folder


def load_gtfs_data_streaming(gtfs_folder: str):
    """Load GTFS data in a memory-lean streaming fashion.

    This avoids materializing a giant stop_times DataFrame by:
      - First pass: gathering relevant_trip_ids and (first,last) Swiss stop_ids per trip
      - Loading trips filtered to relevant_trip_ids
      - Second pass: deduplicating (stop_id, route_id, direction_id) on the fly

    Returns:
      dict with keys:
        - stops: Swiss stops DataFrame
        - trips: filtered trips DataFrame
        - routes: filtered routes DataFrame
        - stop_route_unique: DataFrame[stop_id, route_id, direction_id]
        - route_directions: DataFrame[route_id, direction]
    """
    print("GTFS: loading data (optimized streaming, two-pass over stop_times)…")

    # Load Swiss stops
    all_stops = pd.read_csv(
        f"{gtfs_folder}/stops.txt",
        usecols=['stop_id', 'stop_name', 'stop_lat', 'stop_lon'],
        dtype={'stop_id': str, 'stop_name': str, 'stop_lat': float, 'stop_lon': float}
    )
    swiss_stops = all_stops[all_stops['stop_id'].str.startswith('85')].copy()
    # Filter by precise Swiss border (polygon)
    swiss_stops = filter_points_in_switzerland(swiss_stops, lat_col='stop_lat', lon_col='stop_lon')
    swiss_stop_ids: Set[str] = set(swiss_stops['stop_id'])
    print(f"GTFS: filtered to {len(swiss_stops):,} Swiss stops inside CH border (from {len(all_stops[all_stops['stop_id'].str.startswith('85')]):,} prefixed '85')")

    # First pass over stop_times: gather relevant trips and per-trip termini among Swiss stops
    relevant_trip_ids: Set[str] = set()
    trip_first: Dict[str, Tuple[int, str]] = {}
    trip_last: Dict[str, Tuple[int, str]] = {}

    chunk_size = 500000
    chunks_seen = 0
    for chunk in pd.read_csv(
        f"{gtfs_folder}/stop_times.txt",
        usecols=['trip_id', 'stop_id', 'stop_sequence'],
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
        chunksize=chunk_size
    ):
        if not swiss_stop_ids:
            continue
        mask = chunk['stop_id'].isin(swiss_stop_ids)
        if not mask.any():
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: stream pass 1 processed {chunks_seen} chunks…")
            continue

        swiss_chunk = chunk[mask]
        if swiss_chunk.empty:
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: stream pass 1 processed {chunks_seen} chunks…")
            continue

        # Update relevant trip ids
        relevant_trip_ids.update(swiss_chunk['trip_id'].astype(str).unique().tolist())

        # Vectorized first/last per chunk
        grp = swiss_chunk.groupby('trip_id', sort=False)
        idx_first = grp['stop_sequence'].idxmin()
        idx_last = grp['stop_sequence'].idxmax()
        first_df = swiss_chunk.loc[idx_first, ['trip_id', 'stop_id', 'stop_sequence']]
        last_df = swiss_chunk.loc[idx_last, ['trip_id', 'stop_id', 'stop_sequence']]

        for r in first_df.itertuples(index=False):
            trip = str(r.trip_id)
            seq_min = int(r.stop_sequence)
            stop_min = str(r.stop_id)
            prev = trip_first.get(trip)
            if prev is None or seq_min < prev[0]:
                trip_first[trip] = (seq_min, stop_min)

        for r in last_df.itertuples(index=False):
            trip = str(r.trip_id)
            seq_max = int(r.stop_sequence)
            stop_max = str(r.stop_id)
            prev = trip_last.get(trip)
            if prev is None or seq_max > prev[0]:
                trip_last[trip] = (seq_max, stop_max)

        chunks_seen += 1
        if chunks_seen % 20 == 0:
            print(f"  GTFS: stream pass 1 processed {chunks_seen} chunks…")

    # Load trips filtered to relevant_trip_ids
    if relevant_trip_ids:
        trips_df = pd.read_csv(
            f"{gtfs_folder}/trips.txt",
            usecols=['trip_id', 'route_id', 'direction_id'],
            dtype={'trip_id': str, 'route_id': str, 'direction_id': 'Int8'}
        )
        trips_df = trips_df[trips_df['trip_id'].isin(relevant_trip_ids)].copy()
    else:
        trips_df = pd.DataFrame(columns=['trip_id', 'route_id', 'direction_id'])
    print(f"GTFS: loaded {len(trips_df):,} trips (filtered to relevant trips)")

    # Build trip_id -> (route_id, direction_id)
    trip_id_to_info: Dict[str, Tuple[str, Optional[int]]] = {
        str(r.trip_id): (str(r.route_id), None if pd.isna(r.direction_id) else int(r.direction_id))
        for r in trips_df.itertuples(index=False)
    }

    # Derive route_directions from per-trip Swiss termini
    if trip_first and trip_last:
        # Build stop_id -> stop_name for Swiss stops we loaded
        stop_id_to_name = dict(zip(swiss_stops['stop_id'].astype(str), swiss_stops['stop_name'].astype(str)))
        route_directions_rows = []
        for trip_id, (seq_min, stop_min) in trip_first.items():
            last_info = trip_last.get(trip_id)
            if trip_id not in trip_id_to_info or last_info is None:
                continue
            route_id, _ = trip_id_to_info[trip_id]
            first_name = stop_id_to_name.get(stop_min, 'Unknown')
            last_name = stop_id_to_name.get(last_info[1], 'Unknown')
            direction_str = f"{first_name} → {last_name}"
            route_directions_rows.append((route_id, direction_str))
        route_directions = (
            pd.DataFrame(route_directions_rows, columns=['route_id', 'direction'])
            .dropna()
            .drop_duplicates()
        )
    else:
        route_directions = pd.DataFrame(columns=['route_id', 'direction'])
    print(f"GTFS: extracted {len(route_directions):,} unique route direction strings (first→last)")

    # Second pass over stop_times: deduplicate (stop_id, route_id, direction_id)
    stop_route_unique_set: Set[Tuple[str, str, Optional[int]]] = set()
    chunks_seen = 0
    for chunk in pd.read_csv(
        f"{gtfs_folder}/stop_times.txt",
        usecols=['trip_id', 'stop_id', 'stop_sequence'],
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
        chunksize=chunk_size
    ):
        if not swiss_stop_ids:
            continue
        mask = chunk['stop_id'].isin(swiss_stop_ids)
        if not mask.any():
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: stream pass 2 processed {chunks_seen} chunks…")
            continue
        swiss_chunk = chunk[mask][['trip_id', 'stop_id']].copy()
        if swiss_chunk.empty:
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: stream pass 2 processed {chunks_seen} chunks…")
            continue
        # Vectorized join of trip -> route,dir
        trips_small = pd.DataFrame(
            [(k, v[0], v[1]) for k, v in trip_id_to_info.items()],
            columns=['trip_id', 'route_id', 'direction_id']
        )
        joined = swiss_chunk.merge(trips_small, on='trip_id', how='inner')[['stop_id', 'route_id', 'direction_id']]
        if not joined.empty:
            for t in joined.drop_duplicates().itertuples(index=False):
                stop_route_unique_set.add((str(t.stop_id), str(t.route_id), None if pd.isna(t.direction_id) else int(t.direction_id)))
        chunks_seen += 1
        if chunks_seen % 20 == 0:
            print(f"  GTFS: stream pass 2 processed {chunks_seen} chunks…")

    if stop_route_unique_set:
        stop_route_unique = pd.DataFrame(
            list(stop_route_unique_set),
            columns=['stop_id', 'route_id', 'direction_id']
        )
    else:
        stop_route_unique = pd.DataFrame(columns=['stop_id', 'route_id', 'direction_id'])
    print(f"GTFS: built {len(stop_route_unique):,} unique (stop_id, route_id, direction_id) triples")

    # Load routes filtered to those we actually reference
    relevant_route_ids: Set[str] = set(trips_df['route_id'].unique())
    if relevant_route_ids:
        all_routes = pd.read_csv(
            f"{gtfs_folder}/routes.txt",
            usecols=['route_id', 'route_short_name', 'route_long_name'],
            dtype={'route_id': str, 'route_short_name': str, 'route_long_name': str}
        )
        swiss_routes = all_routes[all_routes['route_id'].isin(relevant_route_ids)].copy()
    else:
        swiss_routes = pd.DataFrame(columns=['route_id', 'route_short_name', 'route_long_name'])
    print(f"GTFS: loaded {len(swiss_routes):,} routes (filtered to referenced routes)")

    return {
        'stops': swiss_stops,
        'trips': trips_df,
        'routes': swiss_routes,
        'stop_route_unique': stop_route_unique,
        'route_directions': route_directions,
    }


def build_integrated_gtfs_data_streaming(gtfs_data_streaming: Dict[str, pd.DataFrame], traffic_points: pd.DataFrame) -> pd.DataFrame:
    """Build the final integrated GTFS DataFrame using streaming outputs.

    Returns DataFrame with columns:
      ['stop_id', 'sloid', 'route_id', 'route_short_name', 'route_long_name', 'direction_id', 'direction']
    """
    # stop_id, route_id, direction_id
    stop_route_unique = gtfs_data_streaming['stop_route_unique']
    # add route names
    route_enriched = stop_route_unique.merge(
        gtfs_data_streaming['routes'][['route_id', 'route_short_name', 'route_long_name']],
        on='route_id', how='left'
    )
    # direction strings by route (reduce to a single representative direction per route)
    route_directions = gtfs_data_streaming['route_directions']
    if not route_directions.empty:
        route_directions_unique = (
            route_directions
            .dropna(subset=['route_id'])
            .groupby('route_id', as_index=False)['direction']
            .first()
        )
    else:
        route_directions_unique = route_directions

    # match GTFS stops to ATLAS sloids
    matches = match_gtfs_to_atlas({'stops': gtfs_data_streaming['stops']}, traffic_points)

    # integrate
    linked_stops = gtfs_data_streaming['stops'].merge(matches, on='stop_id', how='left')
    integrated = linked_stops.merge(route_enriched, on='stop_id', how='inner')
    integrated = integrated.merge(route_directions_unique, on='route_id', how='left')

    # Remove any multiplicative duplicates that could have slipped through
    integrated = integrated.drop_duplicates(subset=['stop_id', 'sloid', 'route_id', 'direction_id'])

    cols = ['stop_id', 'sloid', 'route_id', 'route_short_name', 'route_long_name', 'direction_id', 'direction']
    integrated = integrated[cols].sort_values(by='sloid')
    return integrated


def _normalize_route_id_for_matching(route_id: Optional[str]) -> Optional[str]:
    """Normalize GTFS route_id by removing year codes like -j24, -j25, etc."""
    if route_id is None or (isinstance(route_id, float) and pd.isna(route_id)):
        return None
    import re
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def match_gtfs_to_atlas(gtfs_data, traffic_points):
    """Map stop_id GTFS → sloid ATLAS using a strict rule with fallbacks.

    Strict: (uic_number, normalized_local_ref) == (number, designation)
    Fallbacks, applied only for stops not matched strictly:
      1) If an ATLAS \"number\" has exactly one row, use that sloid
      2) Else, if any candidate sloid (same number) has its last token equal to
         normalized_local_ref, use that sloid
    """
    print("Mapping stop_id GTFS → sloid ATLAS…")
    
    # GTFS stops are already filtered for Switzerland during loading
    gtfs_stops = gtfs_data['stops'].copy()
    
    # Parse stop_ids to extract UIC and local reference
    def parse_stop_id(stop_id):
        parts = stop_id.split(':')
        uic_number = parts[0]
        local_ref = parts[2] if len(parts) >= 3 else None
        return uic_number, local_ref
    
    temp_data = gtfs_stops['stop_id'].apply(parse_stop_id)
    gtfs_stops['uic_number'] = [x[0] for x in temp_data]
    gtfs_stops['local_ref'] = [x[1] for x in temp_data]
    
    # Normalize local_ref (10000->1, 10001->2)
    def normalize_local_ref(ref):
        if pd.isna(ref):
            return ref
        if ref == '10000':
            return '1'
        elif ref == '10001':
            return '2'
        return ref
        
    gtfs_stops['normalized_local_ref'] = gtfs_stops['local_ref'].apply(normalize_local_ref)
    gtfs_stops['uic_number'] = gtfs_stops['uic_number'].astype(str)
    
    # Prepare ATLAS data
    atlas_data = traffic_points[['sloid', 'number', 'designation']].copy()
    atlas_data['number'] = atlas_data['number'].astype(str)
    
    # Strict: match on UIC number and designation
    strict_matches = pd.merge(
        gtfs_stops[['stop_id', 'uic_number', 'normalized_local_ref']],
        atlas_data,
        left_on=['uic_number', 'normalized_local_ref'],
        right_on=['number', 'designation'],
        how='inner'
    )[['stop_id', 'sloid']]

    # Fallbacks for remaining stops
    matched_stop_ids = set(strict_matches['stop_id'])
    remaining = gtfs_stops[~gtfs_stops['stop_id'].isin(matched_stop_ids)].copy()
    if remaining.empty:
        print(f"stop_id→sloid: strict assignments = {len(strict_matches):,}")
        return strict_matches

    # Group ATLAS by number for quick candidate access
    atlas_by_number = {num: sub[['sloid', 'designation']].copy() for num, sub in atlas_data.groupby('number', sort=False)}

    def last_token_of_sloid(s: str) -> str:
        return s.split(':')[-1]

    fallback_rows = []  # (stop_id, sloid)
    for r in remaining.itertuples(index=False):
        uic = r.uic_number
        nref = r.normalized_local_ref
        stop_id = r.stop_id
        candidates = atlas_by_number.get(uic)
        if candidates is None or candidates.empty:
            continue
        # Fallback 1: unique entry by number
        if len(candidates) == 1:
            fallback_rows.append((stop_id, candidates.iloc[0]['sloid']))
            continue
        # Fallback 2: compare last sloid token with normalized_local_ref
        if pd.notna(nref):
            token_matches = candidates[candidates['sloid'].apply(last_token_of_sloid) == nref]
            if not token_matches.empty:
                fallback_rows.append((stop_id, token_matches.iloc[0]['sloid']))

    if fallback_rows:
        fb_df = pd.DataFrame(fallback_rows, columns=['stop_id', 'sloid']).drop_duplicates()
        combined = pd.concat([strict_matches, fb_df], ignore_index=True).drop_duplicates()
    else:
        combined = strict_matches

    print(f"stop_id→sloid: strict = {len(strict_matches):,}, fallback = {len(combined) - len(strict_matches):,}, total = {len(combined):,}")
    return combined
