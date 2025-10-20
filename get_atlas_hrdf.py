"""HRDF data download and processing module."""
import os
import io
import zipfile
import requests
import pandas as pd
from typing import Dict, Set, Tuple, List
from collections import defaultdict


def download_and_extract_hrdf(hrdf_url):
    """Download and extract HRDF data, keeping only the files we need."""
    print(f"HRDF: downloading from {hrdf_url}…")
    response = requests.get(hrdf_url, stream=True)
    response.raise_for_status()

    # Files we actually need for processing
    needed_files = {'GLEISE_LV95', 'FPLAN', 'BAHNHOF'}

    print("HRDF: download successful, extracting ZIP file…")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        # Get the list of files to see what folders are created
        all_files = z.namelist()
        print(f"HRDF: ZIP contains {len(all_files)} files")
        
        # Extract everything to a dedicated HRDF folder to avoid deleting non-HRDF assets
        hrdf_root = os.path.join("data", "raw", "hrdf")
        os.makedirs(hrdf_root, exist_ok=True)
        # Clear previous extracted content to avoid mixing versions
        try:
            for existing_name in os.listdir(hrdf_root):
                existing_path = os.path.join(hrdf_root, existing_name)
                if os.path.isfile(existing_path):
                    os.remove(existing_path)
                else:
                    import shutil
                    shutil.rmtree(existing_path, ignore_errors=True)
        except Exception:
            pass

        z.extractall(hrdf_root)
        print(f"HRDF: extracted to {hrdf_root}")
        
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
            hrdf_folder = os.path.join(hrdf_root, hrdf_folders[0])
            print(f"HRDF: detected folder {hrdf_folder}")
        else:
            # Files might be extracted directly to hrdf_root
            print(f"HRDF: files extracted directly to {hrdf_root}")
            hrdf_folder = hrdf_root

        # Clean up: keep only the files we need (inside the dedicated HRDF folder)
        files_deleted = 0
        if os.path.exists(hrdf_folder):
            files_in_folder = os.listdir(hrdf_folder)
            for file_name in files_in_folder:
                file_path = os.path.join(hrdf_folder, file_name)
                if os.path.isfile(file_path) and file_name not in needed_files:
                    try:
                        os.remove(file_path)
                        files_deleted += 1
                    except OSError:
                        pass  # Ignore deletion errors
            
            print(f"HRDF: cleaned up {files_deleted} unnecessary files, kept {len(needed_files)} needed files")
            
            # Verify we have the files we need
            missing_files = []
            for needed_file in needed_files:
                if not os.path.exists(os.path.join(hrdf_folder, needed_file)):
                    missing_files.append(needed_file)
            
            if missing_files:
                print(f"HRDF: Warning - missing required files: {missing_files}")
            else:
                print(f"HRDF: All required files present: {list(needed_files)}")
        
        return hrdf_folder


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
    uic_ref_to_trips: Dict[Tuple[str, str], List] = defaultdict(list)

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
