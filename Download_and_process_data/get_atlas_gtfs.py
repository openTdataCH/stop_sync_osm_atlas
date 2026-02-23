"""GTFS data download and processing module."""
import os
import zipfile
import requests
import pandas as pd
import shutil
from typing import Dict, Set, Tuple, Optional

from .geo_utils import filter_points_in_switzerland


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
      - route_directions: DataFrame[route_id, direction]
    """
    print("GTFS: loading data (optimized streaming, single pass over stop_times)…")

    stops_path = os.path.join(gtfs_folder, "stops.txt")
    stop_times_path = os.path.join(gtfs_folder, "stop_times.txt")
    trips_path = os.path.join(gtfs_folder, "trips.txt")
    routes_path = os.path.join(gtfs_folder, "routes.txt")

    # Load Swiss stops (prefix + Swiss polygon)
    all_stops = pd.read_csv(
        stops_path,
        usecols=['stop_id', 'stop_name', 'stop_lat', 'stop_lon'],
        dtype={'stop_id': str, 'stop_name': str, 'stop_lat': float, 'stop_lon': float},
        low_memory=False,
    )
    prefixed = all_stops[all_stops['stop_id'].str.startswith('85')].copy()
    swiss_stops = filter_points_in_switzerland(prefixed, lat_col='stop_lat', lon_col='stop_lon')
    swiss_stop_ids: Set[str] = set(swiss_stops['stop_id'].astype(str))
    print(f"GTFS: filtered to {len(swiss_stops):,} Swiss stops inside CH border (from {len(prefixed):,} prefixed '85')")

    # Load trips once; filter later to relevant_trip_ids found via stop_times streaming
    trips_all = pd.read_csv(
        trips_path,
        usecols=['trip_id', 'route_id', 'direction_id'],
        dtype={'trip_id': str, 'route_id': str, 'direction_id': 'Int8'},
        low_memory=False,
    )
    # Pandas Series maps are faster than rebuilding a join table per chunk
    # Note: indexing by trip_id strings preserves exact join semantics while avoiding per-chunk merges.
    route_by_trip = pd.Series(trips_all['route_id'].values, index=trips_all['trip_id'].astype(str))
    dir_by_trip = pd.Series(trips_all['direction_id'].values, index=trips_all['trip_id'].astype(str))

    # Streaming over stop_times: collect
    #  - relevant_trip_ids (trips touching Swiss stops)
    #  - trip_first/trip_last among Swiss stops (stop_sequence min/max)
    #  - unique (stop_id, route_id, direction_id) combinations
    relevant_trip_ids: Set[str] = set()
    trip_first: Dict[str, Tuple[int, str]] = {}
    trip_last: Dict[str, Tuple[int, str]] = {}
    stop_route_unique_set: Set[Tuple[str, str, Optional[int]]] = set()

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

        mask = chunk['stop_id'].isin(swiss_stop_ids)
        if not mask.any():
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: streamed {chunks_seen} chunks…")
            continue

        swiss_chunk = chunk.loc[mask, ['trip_id', 'stop_id', 'stop_sequence']].copy()
        if swiss_chunk.empty:
            chunks_seen += 1
            if chunks_seen % 20 == 0:
                print(f"  GTFS: streamed {chunks_seen} chunks…")
            continue

        # trips touching Swiss stops
        relevant_trip_ids.update(swiss_chunk['trip_id'].unique().tolist())

        # Per-trip Swiss termini (min/max stop_sequence among Swiss stops)
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

        # Build unique (stop_id, route_id, direction_id)
        swiss_chunk['route_id'] = swiss_chunk['trip_id'].map(route_by_trip)
        swiss_chunk['direction_id'] = swiss_chunk['trip_id'].map(dir_by_trip)
        joined = swiss_chunk[['stop_id', 'route_id', 'direction_id']].dropna(subset=['route_id'])
        if not joined.empty:
            for t in joined.drop_duplicates().itertuples(index=False):
                stop_route_unique_set.add(
                    (str(t.stop_id), str(t.route_id), None if pd.isna(t.direction_id) else int(t.direction_id))
                )

        chunks_seen += 1
        if chunks_seen % 20 == 0:
            print(f"  GTFS: streamed {chunks_seen} chunks…")

    # Filter trips to those we actually saw in stop_times among Swiss stops
    if relevant_trip_ids:
        trips_df = trips_all[trips_all['trip_id'].astype(str).isin(relevant_trip_ids)].copy()
    else:
        trips_df = pd.DataFrame(columns=['trip_id', 'route_id', 'direction_id'])
    print(f"GTFS: loaded {len(trips_df):,} trips (filtered to relevant trips)")

    # Derive route_directions from per-trip Swiss termini (same semantics as before)
    if trip_first and trip_last:
        stop_id_to_name = dict(zip(swiss_stops['stop_id'].astype(str), swiss_stops['stop_name'].astype(str)))
        route_directions_rows = []
        for trip_id, (seq_min, stop_min) in trip_first.items():
            last_info = trip_last.get(trip_id)
            if last_info is None:
                continue
            route_id = route_by_trip.get(str(trip_id))
            if route_id is None or (isinstance(route_id, float) and pd.isna(route_id)):
                continue
            first_name = stop_id_to_name.get(stop_min, 'Unknown')
            last_name = stop_id_to_name.get(last_info[1], 'Unknown')
            route_directions_rows.append((str(route_id), f"{first_name} → {last_name}"))
        route_directions = (
            pd.DataFrame(route_directions_rows, columns=['route_id', 'direction'])
            .dropna()
            .drop_duplicates()
        )
    else:
        route_directions = pd.DataFrame(columns=['route_id', 'direction'])
    print(f"GTFS: extracted {len(route_directions):,} unique route direction strings (first→last)")

    # Materialize stop_route_unique table
    if stop_route_unique_set:
        stop_route_unique = pd.DataFrame(
            list(stop_route_unique_set),
            columns=['stop_id', 'route_id', 'direction_id']
        )
    else:
        stop_route_unique = pd.DataFrame(columns=['stop_id', 'route_id', 'direction_id'])
    print(f"GTFS: built {len(stop_route_unique):,} unique (stop_id, route_id, direction_id) triples")

    # Load routes filtered to those we actually reference
    relevant_route_ids: Set[str] = set(trips_df['route_id'].dropna().astype(str).unique())
    if relevant_route_ids:
        all_routes = pd.read_csv(
            routes_path,
            usecols=['route_id', 'route_short_name', 'route_long_name'],
            dtype={'route_id': str, 'route_short_name': str, 'route_long_name': str},
            low_memory=False,
        )
        swiss_routes = all_routes[all_routes['route_id'].astype(str).isin(relevant_route_ids)].copy()
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


# The normalize_route_id function is imported at module level when needed


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
    
    # Parse stop_id to extract UIC and local reference (vectorized; same semantics as the prior apply())
    parts = gtfs_stops['stop_id'].astype(str).str.split(':', n=2, expand=True)
    gtfs_stops['uic_number'] = parts[0]
    if parts.shape[1] >= 3:
        gtfs_stops['local_ref'] = parts[2]
    else:
        gtfs_stops['local_ref'] = None
    
    # Normalize local_ref (10000->1, 10001->2)
    gtfs_stops['normalized_local_ref'] = gtfs_stops['local_ref'].replace({'10000': '1', '10001': '2'})
    gtfs_stops['uic_number'] = gtfs_stops['uic_number'].astype(str)
    
    # Prepare ATLAS data
    atlas_data = traffic_points[['sloid', 'number', 'designation']].copy()
    atlas_data['number'] = atlas_data['number'].astype(str)
    atlas_data['sloid_last_token'] = atlas_data['sloid'].astype(str).str.split(':').str[-1]
    
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
    atlas_by_number = {
        num: sub[['sloid', 'designation', 'sloid_last_token']].copy()
        for num, sub in atlas_data.groupby('number', sort=False)
    }

    fallback_rows = []  # (stop_id, sloid)
    for r in remaining.itertuples(index=False):
        uic = r.uic_number
        nref = r.normalized_local_ref
        stop_id = r.stop_id
        candidates = atlas_by_number.get(uic)
        if candidates is None or candidates.empty:
            continue
        
        # Handling Parent Stations (nref is None)
        # If we have a generic "Parent" GTFS ID (no platform), map it to ALL ATLAS platforms at that station.
        # This checks if nref is None or empty.
        if pd.isna(nref) or not nref:
            # Broadcast to ALL candidates (1-to-many)
            for sloid_cand in candidates['sloid']:
                fallback_rows.append((stop_id, sloid_cand))
            continue

        # Fallback 1: unique entry by number
        if len(candidates) == 1:
            fallback_rows.append((stop_id, candidates.iloc[0]['sloid']))
            continue
        # Fallback 2: compare last sloid token with normalized_local_ref
        token_matches = candidates[candidates['sloid_last_token'] == nref]
        if not token_matches.empty:
            fallback_rows.append((stop_id, token_matches.iloc[0]['sloid']))

    if fallback_rows:
        fb_df = pd.DataFrame(fallback_rows, columns=['stop_id', 'sloid']).drop_duplicates()
        combined = pd.concat([strict_matches, fb_df], ignore_index=True).drop_duplicates()
    else:
        combined = strict_matches

    print(f"stop_id→sloid: strict = {len(strict_matches):,}, fallback = {len(combined) - len(strict_matches):,}, total = {len(combined):,}")
    return combined
