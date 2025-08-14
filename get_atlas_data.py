"""
Simple, clean script to download and process ATLAS and GTFS data.
"""
import requests
import zipfile
import io
import pandas as pd
import os
from collections import defaultdict
from typing import Dict, Set, Tuple, Optional

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
            df = df.dropna(subset=['wgs84North', 'wgs84East'])
            
            # Save processed data
            df.to_csv(output_path, sep=";", index=False)
            
            # Print statistics
            boarding_platforms = df[df['trafficPointElementType'] == 'BOARDING_PLATFORM']
            print(f"ATLAS: BOARDING_PLATFORM rows = {len(boarding_platforms):,}")
            print(f"ATLAS: kept {len(df):,} rows with WGS84 coordinates (uicCountryCode=85)")
            print(f"ATLAS: processed CSV saved to: {output_path}")

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

# Note: baseline GTFS loader removed to keep this module focused on optimized path.

def load_gtfs_data_streaming(gtfs_folder: str, stop_id_filter: Optional[Set[str]] = None):
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
        usecols=['stop_id', 'stop_name'],
        dtype={'stop_id': str, 'stop_name': str}
    )
    swiss_stops = all_stops[all_stops['stop_id'].str.startswith('85')].copy()
    if stop_id_filter is not None:
        swiss_stops = swiss_stops[swiss_stops['stop_id'].isin(stop_id_filter)]
    swiss_stop_ids: Set[str] = set(swiss_stops['stop_id'])
    print(f"GTFS: filtered to {len(swiss_stops):,} Swiss stops (stop_id starts with '85')")

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

# Note: baseline per-stop extraction removed; streaming code builds these directly.

# Note: baseline route directions extractor removed; streaming path computes them.

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
    # direction strings by route
    route_directions = gtfs_data_streaming['route_directions']

    # match GTFS stops to ATLAS sloids
    matches = match_gtfs_to_atlas({'stops': gtfs_data_streaming['stops']}, traffic_points)

    # integrate
    linked_stops = gtfs_data_streaming['stops'].merge(matches, on='stop_id', how='left')
    integrated = linked_stops.merge(route_enriched, on='stop_id', how='inner')
    integrated = integrated.merge(route_directions, on='route_id', how='left')

    cols = ['stop_id', 'sloid', 'route_id', 'route_short_name', 'route_long_name', 'direction_id', 'direction']
    integrated = integrated[cols].sort_values(by='sloid')
    return integrated

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

def download_and_extract_hrdf(hrdf_url):
    """Download and extract HRDF data, returning the actual folder path."""
    print(f"HRDF: downloading from {hrdf_url}…")
    response = requests.get(hrdf_url, stream=True)
    response.raise_for_status()

    print("HRDF: download successful, extracting ZIP file…")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        # Get the list of files to see what folders are created
        all_files = z.namelist()
        print(f"HRDF: ZIP contains {len(all_files)} files")
        
        # Extract everything to data/raw
        z.extractall("data/raw")
        print(f"HRDF: extracted to data/raw")
        
        # Find the HRDF folder by looking for folders that contain HRDF files
        hrdf_folders = []
        for file_path in all_files:
            if '/' in file_path:  # It's in a subfolder
                folder_name = file_path.split('/')[0]
                if folder_name not in hrdf_folders:
                    # Check if this looks like an HRDF folder (contains typical HRDF files)
                    if any(hrdf_file in file_path for hrdf_file in ['GLEISE_LV95', 'FPLAN', 'BAHNHOF']):
                        hrdf_folders.append(folder_name)
        
        if hrdf_folders:
            # Use the first HRDF folder found
            hrdf_folder = os.path.join("data/raw", hrdf_folders[0])
            print(f"HRDF: detected folder {hrdf_folder}")
            return hrdf_folder
        else:
            # Files might be extracted directly to data/raw
            print("HRDF: files extracted directly to data/raw")
            return "data/raw"

def parse_gleise_lv95_for_sloids(hrdf_path, target_sloids, two_pass: bool = True, use_fast_guard: bool = True):
    """Parse GLEISE_LV95 to map sloids to trips.

    two_pass=True does a first pass to collect only (UIC, #ref) pairs for target sloids,
    then a second pass to collect trips for those pairs only. This reduces CPU and memory.

    use_fast_guard=True enables cheap substring guards to skip irrelevant lines before splitting.
    """
    gleise_file_path = os.path.join(hrdf_path, 'GLEISE_LV95')
    
    if not os.path.exists(gleise_file_path):
        print(f"GLEISE_LV95 file not found at: {gleise_file_path}")
        return {}
    
    target_sloids_set: Set[str] = set(target_sloids)
    sloid_to_uic_ref: Dict[str, Tuple[str, str]] = {}
    uic_ref_to_trips: Dict[Tuple[str, str], list] = defaultdict(list)

    print("HRDF: parsing GLEISE_LV95 for sloid→(UIC,#ref) and trips…")

    def _is_potential_assignment(line: str) -> bool:
        if not use_fast_guard:
            return True
        # Fast checks: must start with digits and contain a '#'
        s = line.lstrip()
        return ('#' in s) and (len(s) >= 7 and s[:7].isdigit())

    def _is_potential_sloid(line: str) -> bool:
        if not use_fast_guard:
            return True
        s = line
        return ('ch:1:sloid:' in s) or (' sloid:' in s)

    # Pass 1: collect sloid -> (UIC, #ref)
    lines_processed = 0
    found_sloids = 0
    with open(gleise_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for raw_line in f:
            lines_processed += 1
            if not _is_potential_sloid(raw_line):
                if lines_processed % 1000000 == 0:
                    print(f"  HRDF: processed {lines_processed:,} lines, found {found_sloids} target sloids…")
                continue
            parts = raw_line.strip().split()
            if not parts:
                continue
            if (
                len(parts) >= 5 and
                parts[0].isdigit() and len(parts[0]) == 7 and
                parts[1].startswith('#') and
                parts[2] == 'g' and parts[3] == 'A'
            ):
                uic, ref_no, sloid = parts[0], parts[1], parts[4]
                if sloid in target_sloids_set and sloid not in sloid_to_uic_ref:
                    sloid_to_uic_ref[sloid] = (uic, ref_no)
                    found_sloids += 1
            if lines_processed % 1000000 == 0:
                print(f"  HRDF: processed {lines_processed:,} lines, found {found_sloids} target sloids…")

    if not two_pass:
        # Single-pass fallback: build all trips for all (uic, ref)
        lines_processed = 0
        with open(gleise_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for raw_line in f:
                lines_processed += 1
                if not _is_potential_assignment(raw_line):
                    continue
                parts = raw_line.strip().split()
                if (
                    len(parts) >= 4 and
                    parts[0].isdigit() and len(parts[0]) == 7 and
                    parts[1].isdigit() and len(parts[1]) == 6 and
                    parts[2].isdigit() and len(parts[2]) == 6 and
                    parts[3].startswith('#')
                ):
                    uic, trip_no, op_no, ref_no = parts[0], parts[1], parts[2], parts[3]
                    uic_ref_to_trips[(uic, ref_no)].append((trip_no, op_no))
    else:
        # Two-pass targeted: only collect trips for (uic, ref) pairs we actually need
        needed_by_uic: Dict[str, Set[str]] = defaultdict(set)
        for (uic, ref_no) in set(sloid_to_uic_ref.values()):
            needed_by_uic[uic].add(ref_no)

        lines_processed = 0
        with open(gleise_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for raw_line in f:
                lines_processed += 1
                if not _is_potential_assignment(raw_line):
                    continue
                s = raw_line.lstrip()
                # Quick check: first 7 chars are UIC
                if len(s) < 7 or not s[:7].isdigit():
                    continue
                uic_prefix = s[:7]
                if uic_prefix not in needed_by_uic:
                    continue
                parts = raw_line.strip().split()
                if (
                    len(parts) >= 4 and
                    parts[0] == uic_prefix and
                    parts[1].isdigit() and len(parts[1]) == 6 and
                    parts[2].isdigit() and len(parts[2]) == 6 and
                    parts[3].startswith('#')
                ):
                    uic, trip_no, op_no, ref_no = parts[0], parts[1], parts[2], parts[3]
                    if ref_no in needed_by_uic[uic]:
                        uic_ref_to_trips[(uic, ref_no)].append((trip_no, op_no))

    # Map sloids to trips
    sloid_to_trips: Dict[str, list] = defaultdict(list)
    for sloid, (uic, ref_no) in sloid_to_uic_ref.items():
        trips = uic_ref_to_trips.get((uic, ref_no), [])
        sloid_to_trips[sloid].extend(trips)

    print(f"HRDF: sloids with trips = {len(sloid_to_trips):,}")
    return sloid_to_trips

def extract_fplan_directions_for_trips(hrdf_path, target_trip_keys):
    """Extract direction information from FPLAN for specific trips."""
    fplan_path = os.path.join(hrdf_path, 'FPLAN')
    
    if not os.path.exists(fplan_path):
        print(f"FPLAN file not found at: {fplan_path}")
        return {}
    
    trip_directions = {}
    current_trip_key = None
    current_line = None
    current_stops = []
    
    target_set = set(target_trip_keys)
    lines_processed = 0
    found_trips = 0
    
    print(f"HRDF: parsing FPLAN for {len(target_set):,} target trips…")
    
    with open(fplan_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            lines_processed += 1
            
            if line.startswith('%') or not line.strip():
                continue
                
            # Trip header
            if line.startswith('*Z'):
                # Save previous trip
                if current_trip_key and current_trip_key in target_set and len(current_stops) >= 2:
                    trip_directions[current_trip_key] = {
                        'line': current_line,
                        'first_stop': current_stops[0],
                        'last_stop': current_stops[-1]
                    }
                    found_trips += 1
                
                # Start new trip
                parts = line.split()
                if len(parts) >= 3:
                    current_trip_key = (parts[1], parts[2])
                    current_line = None
                    current_stops = []
            
            # Line information
            elif line.startswith('*L') and current_trip_key and current_trip_key in target_set:
                parts = line.split()
                if len(parts) >= 2:
                    current_line = parts[1]
            
            # Stop records
            elif current_trip_key and current_trip_key in target_set and not line.startswith('*'):
                parts = line.split()
                if len(parts) >= 1 and parts[0].isdigit():
                    current_stops.append(parts[0])
            
            if lines_processed % 5000000 == 0:
                print(f"  HRDF: processed {lines_processed:,} lines, found {found_trips} target trips…")
                
            if found_trips == len(target_set):
                print(f"  HRDF: found all {found_trips} target trips, stopping early")
                break
    
    # Don't forget the last trip
    if current_trip_key and current_trip_key in target_set and len(current_stops) >= 2:
        trip_directions[current_trip_key] = {
            'line': current_line,
            'first_stop': current_stops[0],
            'last_stop': current_stops[-1]
        }
        found_trips += 1
    
    print(f"HRDF: extracted directions for {len(trip_directions):,} trips")
    return trip_directions

def load_station_names_hrdf(hrdf_path):
    """Load station names from BAHNHOF file."""
    bahnhof_path = os.path.join(hrdf_path, 'BAHNHOF')
    
    if not os.path.exists(bahnhof_path):
        print(f"BAHNHOF file not found at: {bahnhof_path}")
        return {}
    
    stations = {}
    
    print("HRDF: loading station names from BAHNHOF…")
    with open(bahnhof_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.strip():
                uic = line[0:7].strip()
                name_part = line[7:].strip()
                if '$<1>' in name_part:
                    name = name_part.split('$<1>')[0].strip()
                else:
                    name = name_part
                stations[uic] = name
    
    return stations

def process_hrdf_direction_data(traffic_points, hrdf_folder):
    """Process HRDF data to extract direction information for ATLAS sloids."""
    print("\n=== HRDF Direction Extraction ===")
    
    all_sloids = set(traffic_points['sloid'].dropna().unique())
    print(f"HRDF: ATLAS sloids to consider = {len(all_sloids):,}")
    
    # Parse GLEISE_LV95 to map sloids to trips
    sloid_to_trips = parse_gleise_lv95_for_sloids(hrdf_folder, all_sloids, two_pass=True, use_fast_guard=True)
    
    if not sloid_to_trips:
        print("No HRDF trips found for any sloids")
        return None
    
    # Collect all unique trip keys
    all_trip_keys = set()
    for trips in sloid_to_trips.values():
        all_trip_keys.update(trips)
    
    print(f"HRDF: total unique trips to analyze = {len(all_trip_keys):,}")
    
    # Extract direction information
    trip_directions = extract_fplan_directions_for_trips(hrdf_folder, all_trip_keys)
    
    # Load station names
    stations = load_station_names_hrdf(hrdf_folder)
    
    # Generate direction strings for each sloid
    hrdf_results = []
    
    for sloid, trips in sloid_to_trips.items():
        unique_directions = set()
        
        for trip_tuple in trips:
            if trip_tuple in trip_directions:
                info = trip_directions[trip_tuple]
                line = info['line'] or ''
                first_stop_uic = info['first_stop']
                last_stop_uic = info['last_stop']
                
                first_stop_name = stations.get(first_stop_uic, f"Unknown({first_stop_uic})")
                last_stop_name = stations.get(last_stop_uic, f"Unknown({last_stop_uic})")

                direction_name_str = f"{first_stop_name} → {last_stop_name}"
                direction_uic_str = f"{first_stop_uic} → {last_stop_uic}"
                unique_directions.add((line, direction_name_str, direction_uic_str))
        
        # Add each unique direction as a separate row
        for line_name, direction_name, direction_uic in unique_directions:
            hrdf_results.append({
                'line_name': line_name,
                'sloid': sloid,
                'direction_name': direction_name,
                'direction_uic': direction_uic
            })
    
    if hrdf_results:
        hrdf_df = pd.DataFrame(hrdf_results)
        hrdf_df = hrdf_df[['line_name', 'sloid', 'direction_name', 'direction_uic']]
        hrdf_df = hrdf_df.sort_values(by=['sloid', 'line_name', 'direction_name'])
        return hrdf_df
    else:
        return None

if __name__ == "__main__":
    # Download and process ATLAS data
    atlas_stops_csv_output_path = "data/raw/stops_ATLAS.csv"
    download_url = "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink"
    get_atlas_stops(atlas_stops_csv_output_path, download_url)
    
    # Load traffic points data
    traffic_points = pd.read_csv(atlas_stops_csv_output_path, sep=';')

    # Process GTFS data
    print("\n=== GTFS Integration (stop_id → sloid) ===")
    gtfs_url = "https://data.opentransportdata.swiss/de/dataset/timetable-2025-gtfs2020/permalink"

    # Check if GTFS results already exist
    gtfs_results_path = "data/processed/atlas_routes_gtfs.csv"
    try:
        gtfs_folder = download_and_extract_gtfs(gtfs_url)
        # Use optimized streaming path by default
        gtfs_stream = load_gtfs_data_streaming(gtfs_folder)
        integrated_data = build_integrated_gtfs_data_streaming(gtfs_stream, traffic_points)

        # Save GTFS results
        result_cols = ['stop_id', 'sloid', 'route_id', 'route_short_name', 'route_long_name', 'direction_id', 'direction']
        final_data = integrated_data[result_cols].sort_values(by='sloid')
        final_data.to_csv(gtfs_results_path, index=False)

        # Print statistics
        total_gtfs_stops = len(integrated_data['stop_id'].unique())
        matched_stops = integrated_data['sloid'].notna().sum()
        unique_sloids_matched = integrated_data['sloid'].dropna().nunique()

        print("\n=== stop_id GTFS → SLOID ATLAS: Summary ===")
        print(f"GTFS integrated stops: {total_gtfs_stops:,}")
        print(f"stop_id→sloid assignments (rows): {matched_stops:,}")
        print(f"unique sloids with routes: {unique_sloids_matched:,}")
        print(f"Saved {len(integrated_data):,} rows to {gtfs_results_path}")
        print("===========================")

    except Exception as e:
        print(f"Error processing GTFS data: {e}")
        print("Continuing with HRDF processing...")

    # Process HRDF data
    print("\n=== HRDF Integration (directions) ===")
    hrdf_url = "https://data.opentransportdata.swiss/dataset/6083374f-6a6a-4d84-a6f7-0816493a0766/resource/95fd7309-cc17-4af7-a2f7-e77f04eb328f/download/oev_sammlung_ch_hrdf_5_40_41_2025_20250711_220742.zip"
    
    # Check if HRDF results already exist
    hrdf_results_path = "data/processed/atlas_routes_hrdf.csv"
    try:
        hrdf_folder = download_and_extract_hrdf(hrdf_url)
        
        if os.path.exists(hrdf_folder):
            # List the contents of the HRDF folder to see what files we have
            hrdf_files = os.listdir(hrdf_folder)
            print(f"HRDF: folder contains {len(hrdf_files)} items")
            
            hrdf_results = process_hrdf_direction_data(traffic_points, hrdf_folder)
            
            if hrdf_results is not None:
                hrdf_results.to_csv(hrdf_results_path, index=False)
                
                print("\n=== HRDF Direction Summary ===")
                print(f"Direction entries: {len(hrdf_results):,}")
                print(f"Unique sloids with directions: {hrdf_results['sloid'].nunique():,}")
                print(f"Saved {len(hrdf_results):,} rows to {hrdf_results_path}")
                print("===========================")
            else:
                print("No HRDF direction data could be processed")
        else:
            print(f"HRDF folder {hrdf_folder} not found")
            
    except Exception as e:
        print(f"Error processing HRDF data: {e}")
    
    print("Done!")

