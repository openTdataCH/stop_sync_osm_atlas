"""
This files creates to csv files, one with all the ATLAS stops and one with route info for each stop.
"""
#import ATLAS data
import requests
import zipfile
import io
import csv
import pandas as pd
import os
import gc  # Add garbage collection
from collections import defaultdict

# === PERFORMANCE CONFIGURATION ===
# Adjust these values based on available memory and processing needs
GTFS_CHUNK_SIZE = 5000000      # Rows per chunk for GTFS processing (5M default)
GTFS_FILE_CHUNK_SIZE = 500000  # Rows per chunk for GTFS file loading (500K default)
ATLAS_CHUNK_SIZE = 400000      # Rows per chunk for ATLAS processing (400K default)
PROGRESS_REPORT_INTERVAL_GLEISE = 1000000   # Report every 1M lines for GLEISE_LV95
PROGRESS_REPORT_INTERVAL_FPLAN = 5000000    # Report every 5M lines for FPLAN
GC_FREQUENCY = 5               # Force garbage collection every N chunks
# ===================================

# Set pandas to use less memory
pd.options.mode.chained_assignment = None  # default='warn'

# Create data directories
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)
os.makedirs("data/debug", exist_ok=True)

def get_atlas_stops(atlas_stops_csv_output_path, download_url):
    """Download and process ATLAS stops data in a memory-efficient way."""
    response = requests.get(download_url)
    if response.status_code == 200:
        print("Download successful, extracting ZIP file...")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # List all files in the ZIP archive
            csv_files = z.namelist()
            print("Files in the ZIP:", csv_files)
            
            if csv_files:
                # Assume the CSV file is the first one in the archive
                csv_filename = csv_files[0]
                print("Extracting:", csv_filename)

                # Extract the CSV file and process it in chunks before saving
                with z.open(csv_filename) as f:
                    # Use chunk processing to reduce memory usage
                    chunk_size = ATLAS_CHUNK_SIZE  # Adjust based on memory constraints
                    chunks = []
                    
                    for chunk in pd.read_csv(f, sep=";", chunksize=chunk_size):
                        # Filter for Switzerland (country code 85)
                        chunk = chunk[chunk['uicCountryCode'] == 85]
                        # Remove rows without coordinates
                        chunk = chunk.dropna(subset=['wgs84North', 'wgs84East'])
                        chunks.append(chunk)
                        
                        # Count boarding platforms for reporting
                        if 'trafficPointElementType' in chunk.columns:
                            boarding_platforms_count = len(chunk[chunk['trafficPointElementType'] == 'BOARDING_PLATFORM'])
                            print(f"Processed chunk with {boarding_platforms_count} BOARDING_PLATFORM entries")
                    
                    # Combine filtered chunks
                    csv_data = pd.concat(chunks, ignore_index=True)
                    # Get statistics for reporting
                    boarding_platforms = csv_data[csv_data['trafficPointElementType'] == 'BOARDING_PLATFORM']
                    print(f"Found {len(boarding_platforms)} BOARDING_PLATFORM entries in ATLAS data.")
                    print(f"ATLAS data processed: {len(csv_data)} rows with coordinates.")
                    
                    # Save the processed data
                    csv_data.to_csv(atlas_stops_csv_output_path, sep=";", index=False)
                    
                    # Force garbage collection
                    del chunks, csv_data
                    gc.collect()
                    
                print(f"Processed CSV file saved as: {atlas_stops_csv_output_path}")
            else:
                print("No CSV file found in the ZIP archive.")
    else:
        print("Failed to download file. Status code:", response.status_code)

def extract_route_direction_per_stop(gtfs_data):
    """Extracts route and direction information for each stop from GTFS data."""
    # Process in smaller chunks to reduce memory usage and improve performance
    chunk_size = GTFS_CHUNK_SIZE  # Reduced from 40M to 5M for better memory management
    
    print(f"Processing stop_times data ({len(gtfs_data['stop_times'])} rows) in chunks of {chunk_size:,}")
    
    # Pre-filter trips data to only needed columns to reduce memory
    trips_filtered = gtfs_data['trips'][['trip_id', 'route_id', 'direction_id']].copy()
    routes_filtered = gtfs_data['routes'][['route_id', 'route_short_name', 'route_long_name']].copy()
    
    if len(gtfs_data['stop_times']) > chunk_size:
        result_chunks = []
        total_chunks = (len(gtfs_data['stop_times']) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(gtfs_data['stop_times']), chunk_size):
            print(f"Processing stop_times chunk {i//chunk_size + 1}/{total_chunks}")
            chunk = gtfs_data['stop_times'].iloc[i:i+chunk_size][['stop_id', 'trip_id']].copy()
            
            # Use inner join to only keep rows that exist in both datasets
            stop_times_with_trip = pd.merge(chunk, trips_filtered, on='trip_id', how='inner')
            
            # Extract unique combinations immediately to reduce memory
            stop_route_direction = stop_times_with_trip[['stop_id', 'route_id', 'direction_id']].drop_duplicates()
            result_chunks.append(stop_route_direction)
            
            # Clean up to free memory
            del chunk, stop_times_with_trip
            
            # Force garbage collection every 5 chunks
            if (i // chunk_size + 1) % GC_FREQUENCY == 0:
                gc.collect()
                
        print("Combining chunk results...")
        stop_route_direction = pd.concat(result_chunks, ignore_index=True).drop_duplicates()
        del result_chunks
        gc.collect()
    else:
        # For smaller datasets, process directly but still filter columns early
        stop_times_filtered = gtfs_data['stop_times'][['stop_id', 'trip_id']].copy()
        stop_times_with_trip = pd.merge(stop_times_filtered, trips_filtered, on='trip_id', how='inner')
        stop_route_direction = stop_times_with_trip[['stop_id', 'route_id', 'direction_id']].drop_duplicates()
        del stop_times_filtered, stop_times_with_trip
        gc.collect()

    print("Adding route information...")
    # Join with routes to get route names - this is now a smaller dataset
    stop_route_direction = pd.merge(
        stop_route_direction, 
        routes_filtered,
        on='route_id', 
        how='left'
    )
    
    print(f"Extracted route information for {len(stop_route_direction)} stop-route combinations")
    return stop_route_direction

def match_gtfs_to_atlas(gtfs_data, traffic_points):
    """
    Match GTFS stops to ATLAS stops based on UIC number and local reference.
    
    Args:
        gtfs_data: Dictionary with GTFS dataframes
        traffic_points: DataFrame with ATLAS stops data
        
    Returns:
        DataFrame with matched stops (stop_id to sloid mapping)
    """
    print("\nMatching GTFS stops to ATLAS stops...")
    
    # 1. Filter for GTFS stops whose stop_id starts with "85"
    gtfs_stops = gtfs_data['stops'][gtfs_data['stops']['stop_id'].str.startswith('85')].copy()
    
    # 2. Parse GTFS stop_ids to extract uic_number and local_ref
    def parse_stop_id(stop_id):
        try:
            parts = stop_id.split(':')
            
            # Always take first part as UIC number
            uic_number = parts[0]
            
            # If there are at least 3 parts, take the third as local_ref
            if len(parts) >= 3:
                local_ref = parts[2]
                return uic_number, local_ref
            # Otherwise just return UIC with no local_ref
            return uic_number, None
        except:
            # Add to review file for manual inspection
            with open("data/debug/review_stop_ids.txt", "a") as f:
                f.write(f"{stop_id}\n")
            return stop_id, None
            
    # Apply parsing function and create normalized local_ref
    temp_data = gtfs_stops['stop_id'].apply(parse_stop_id)
    gtfs_stops['uic_number'] = [x[0] for x in temp_data]
    gtfs_stops['local_ref'] = [x[1] for x in temp_data]
    del temp_data
    gc.collect()
    
    gtfs_stops['uic_number'] = gtfs_stops['uic_number'].astype(str)
    
    # 3. Normalize local_ref (10000->1, 10001->2)
    def normalize_local_ref(ref):
        if not pd.isna(ref):
            if ref == '10000': return '1'
            elif ref == '10001': return '2'
        return ref
        
    gtfs_stops['normalized_local_ref'] = gtfs_stops['local_ref'].apply(normalize_local_ref)
    
    # 4. Prepare ATLAS entries - only keep necessary columns
    traffic_points_copy = traffic_points[['sloid', 'number', 'designation']].copy()
    traffic_points_copy['number'] = traffic_points_copy['number'].astype(str)
    
    # 5. Create indexes for faster lookups
    # Skip creating dictionaries to save memory, use merge instead
    
    # 6. Match GTFS stops to ATLAS stops
    # First do simple matching using merge
    print("Performing simple matches...")
    simple_matches = pd.merge(
        gtfs_stops[['stop_id', 'uic_number', 'normalized_local_ref']],
        traffic_points_copy,
        left_on=['uic_number', 'normalized_local_ref'],
        right_on=['number', 'designation'],
        how='inner'
    )[['stop_id', 'sloid']]
    
    # Clean up to free memory
    del traffic_points_copy, gtfs_stops
    gc.collect()
    
    print(f"Found {len(simple_matches)} simple matches")
    
    return simple_matches

def download_and_extract_gtfs(gtfs_url, extract_to_folder=None):
    """Download and extract GTFS data from URL.
    If ``extract_to_folder`` is *None*, the function discovers the final ZIP
    location from the download stream and derives a sensible folder name
    from that filename inside ``data/raw``. The function returns the path
    of the folder containing the extracted files so that the caller can
    reuse it later on.
    """
    print(f"Attempting to download GTFS data from: {gtfs_url}")
    
    try:
        # Use a single streaming GET request to handle redirects and get final URL
        with requests.get(gtfs_url, stream=True, allow_redirects=True) as response:
            response.raise_for_status()
            
            # Determine the extract_to_folder from the final URL after redirection
            if extract_to_folder is None:
                final_url = response.url
                zip_name = os.path.basename(final_url)
                folder_name, _ = os.path.splitext(zip_name)
                extract_to_folder = os.path.join("data/raw", folder_name)

            # Create directory if it doesn't exist
            if not os.path.exists(extract_to_folder):
                os.makedirs(extract_to_folder)
            
            # Check if GTFS files already exist to avoid re-downloading
            required_files = ['routes.txt', 'trips.txt', 'stop_times.txt', 'stops.txt']
            if all(os.path.exists(os.path.join(extract_to_folder, f)) for f in required_files):
                print(f"GTFS files already exist in {extract_to_folder}, skipping download.")
                return extract_to_folder
            
            print("Download successful, extracting GTFS ZIP file...")
            # Use response.content to get the file bytes and extract
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                z.extractall(extract_to_folder)
                extracted_files = z.namelist()
                print(f"Extracted {len(extracted_files)} files to {extract_to_folder}")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading GTFS data: {e}")
        raise
    except zipfile.BadZipFile as e:
        print(f"Error extracting GTFS ZIP file: {e}")
        raise

    # Return path so caller can use it
    return extract_to_folder

def download_and_extract_hrdf(hrdf_url, extract_folder):
    """Download and extract HRDF data from a ZIP URL if the folder doesn't exist."""
    # Update to extract into data/raw directory instead of project root
    data_raw_path = "data/raw"
    target_path = os.path.join(data_raw_path, os.path.basename(extract_folder))
    
    if os.path.exists(extract_folder):
        print(f"HRDF data folder '{extract_folder}' already exists. Skipping download.")
        return

    print(f"HRDF data folder not found. Downloading from {hrdf_url}...")

    try:
        response = requests.get(hrdf_url, stream=True)
        response.raise_for_status()

        print("Download successful. Extracting ZIP file...")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Extract to data/raw directory
            z.extractall(data_raw_path)
            print(f"Successfully extracted HRDF data to {data_raw_path}.")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading HRDF data: {e}")
        raise
    except zipfile.BadZipFile:
        print("Downloaded file is not a valid ZIP file.")
        raise

def extract_gtfs_directions(gtfs_data):
    """Extracts start and end stops for each route from GTFS data."""
    print("Extracting GTFS directions...")
    
    stop_times = gtfs_data['stop_times']
    stops = gtfs_data['stops']
    trips = gtfs_data['trips']

    # 1. Find the first and last stop for each trip using stop_sequence
    print("Finding first and last stops for each trip...")
    # This can be memory intensive, so we work carefully.
    # Find the index of the min and max stop_sequence for each trip_id.
    first_stop_indices = stop_times.groupby('trip_id')['stop_sequence'].idxmin()
    last_stop_indices = stop_times.groupby('trip_id')['stop_sequence'].idxmax()

    # Select the corresponding rows from stop_times.
    first_stops = stop_times.loc[first_stop_indices][['trip_id', 'stop_id']]
    last_stops = stop_times.loc[last_stop_indices][['trip_id', 'stop_id']]

    first_stops = first_stops.rename(columns={'stop_id': 'first_stop_id'})
    last_stops = last_stops.rename(columns={'stop_id': 'last_stop_id'})
    
    # 2. Merge to get trip start and end points together.
    print("Merging trip termini...")
    trip_termini = pd.merge(first_stops, last_stops, on='trip_id')
    del first_stops, last_stops, first_stop_indices, last_stop_indices
    gc.collect()

    # 3. Get stop names for the start and end stops.
    print("Merging with stop names...")
    stops_subset = stops[['stop_id', 'stop_name']]
    trip_termini = pd.merge(trip_termini, stops_subset, left_on='first_stop_id', right_on='stop_id', how='left')
    trip_termini = trip_termini.rename(columns={'stop_name': 'first_stop_name'}).drop(columns=['stop_id'])

    trip_termini = pd.merge(trip_termini, stops_subset, left_on='last_stop_id', right_on='stop_id', how='left')
    trip_termini = trip_termini.rename(columns={'stop_name': 'last_stop_name'}).drop(columns=['stop_id'])
    del stops_subset
    gc.collect()

    # 4. Create the final direction string.
    print("Creating direction strings...")
    trip_termini['direction'] = trip_termini['first_stop_name'].fillna('Unknown') + ' → ' + trip_termini['last_stop_name'].fillna('Unknown')

    # 5. Link these directions back to their routes.
    print("Linking directions to routes...")
    trip_directions = pd.merge(trips[['trip_id', 'route_id']], trip_termini[['trip_id', 'direction']], on='trip_id', how='left')
    
    # A single route can have multiple direction strings if its trips have different start/end points.
    # We will keep all unique direction strings for each route.
    route_directions = trip_directions[['route_id', 'direction']].drop_duplicates().dropna()

    print(f"Extracted {len(route_directions)} unique route directions.")
    
    return route_directions

def parse_gleise_lv95_for_sloids(hrdf_path, target_sloids):
    """
    Parse GLEISE_LV95 to map sloids to trips with the correct format understanding
    """
    gleise_file_path = os.path.join(hrdf_path, 'GLEISE_LV95')
    
    # Step 1: Map sloids to (UIC, ref_no)
    sloid_to_uic_ref = {}
    
    # Step 2: Map (UIC, ref_no) to trips
    uic_ref_to_trips = defaultdict(list)
    
    print("Parsing GLEISE_LV95 for HRDF direction data...")
    
    # Convert target_sloids to set for faster lookup
    target_sloids_set = set(target_sloids)
    lines_processed = 0
    found_sloids = 0
    
    with open(gleise_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            lines_processed += 1
            parts = line.strip().split()
            if not parts:
                continue
                
            # Check if this is a trip assignment line (beginning of file)
            # Format: UIC trip_no op_no ref_no [bitfield]
            if (len(parts) >= 4 and 
                parts[0].isdigit() and len(parts[0]) == 7 and  # UIC
                parts[1].isdigit() and len(parts[1]) == 6 and  # trip_no  
                parts[2].isdigit() and len(parts[2]) == 6 and  # op_no
                parts[3].startswith('#')):                      # ref_no
                
                uic = parts[0]
                trip_no = parts[1]
                op_no = parts[2]
                ref_no = parts[3]
                
                uic_ref_to_trips[(uic, ref_no)].append((trip_no, op_no))
                
            # Check if this is a sloid definition line (later in file)
            # Format: UIC ref_no g A sloid
            elif (len(parts) >= 5 and 
                  parts[0].isdigit() and len(parts[0]) == 7 and  # UIC
                  parts[1].startswith('#') and                   # ref_no
                  parts[2] == 'g' and parts[3] == 'A'):         # sloid marker
                
                uic = parts[0]
                ref_no = parts[1]
                sloid = parts[4]
                
                if sloid in target_sloids_set:
                    sloid_to_uic_ref[sloid] = (uic, ref_no)
                    found_sloids += 1
            
            # Report progress every 1M lines instead of 2M for better feedback
            if lines_processed % PROGRESS_REPORT_INTERVAL_GLEISE == 0:
                print(f"  ... processed {lines_processed:,} lines, found {found_sloids} target sloids")
                
            # Early termination if we've found all target sloids
            if found_sloids == len(target_sloids_set):
                print(f"  Found all {found_sloids} target sloids, stopping early at line {lines_processed:,}")
                break
    
    # Step 3: Map sloids to trips
    sloid_to_trips = defaultdict(list)
    for sloid, (uic, ref_no) in sloid_to_uic_ref.items():
        trips = uic_ref_to_trips.get((uic, ref_no), [])
        sloid_to_trips[sloid].extend(trips)
    
    print(f"Found {len(sloid_to_trips)} sloids with trips in HRDF data (processed {lines_processed:,} lines)")
    return sloid_to_trips

def extract_fplan_directions_for_trips(hrdf_path, target_trip_keys):
    """
    Extract direction information from FPLAN for specific trips
    """
    fplan_path = os.path.join(hrdf_path, 'FPLAN')
    
    trip_directions = {}
    current_trip_key = None
    current_line = None
    current_stops = []
    
    # Convert target trips to a set for faster lookup
    target_set = set(target_trip_keys)
    lines_processed = 0
    found_trips = 0
    
    print(f"Parsing FPLAN for {len(target_set)} target trips...")
    
    with open(fplan_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            lines_processed += 1
            
            if line.startswith('%') or not line.strip():
                continue
                
            # Trip header
            if line.startswith('*Z'):
                # Save previous trip if it was a target
                if current_trip_key and current_trip_key in target_set and current_stops and len(current_stops) >= 2:
                    trip_directions[current_trip_key] = {
                        'line': current_line,
                        'first_stop': current_stops[0],
                        'last_stop': current_stops[-1]
                    }
                    found_trips += 1
                
                # Start new trip
                parts = line.split()
                if len(parts) >= 3:
                    trip_no = parts[1]
                    op_no = parts[2]
                    current_trip_key = (trip_no, op_no)
                    current_line = None
                    current_stops = []
            
            # Line information
            elif line.startswith('*L') and current_trip_key and current_trip_key in target_set:
                parts = line.split()
                if len(parts) >= 2:
                    line_info = parts[1]
                    # Handle line references vs direct line names
                    if line_info.startswith('#'):
                        current_line = f"REF{line_info}"  # Mark as reference
                    else:
                        current_line = line_info
            
            # Stop records (no * prefix)
            elif current_trip_key and current_trip_key in target_set and not line.startswith('*'):
                parts = line.split()
                if len(parts) >= 1 and parts[0].isdigit():
                    stop_uic = parts[0]
                    current_stops.append(stop_uic)
            
            # Report progress every 5M lines for better feedback
            if lines_processed % PROGRESS_REPORT_INTERVAL_FPLAN == 0:
                print(f"  ... processed {lines_processed:,} lines, found {found_trips} target trips")
                
            # Early termination if we've found all target trips
            if found_trips == len(target_set):
                print(f"  Found all {found_trips} target trips, stopping early at line {lines_processed:,}")
                break
    
    # Don't forget the last trip
    if current_trip_key and current_trip_key in target_set and current_stops and len(current_stops) >= 2:
        trip_directions[current_trip_key] = {
            'line': current_line,
            'first_stop': current_stops[0],
            'last_stop': current_stops[-1]
        }
        found_trips += 1
    
    print(f"Extracted directions for {len(trip_directions)} trips (processed {lines_processed:,} lines)")
    return trip_directions

def load_station_names_hrdf(hrdf_path):
    """Load station names from BAHNHOF file"""
    bahnhof_path = os.path.join(hrdf_path, 'BAHNHOF')
    stations = {}
    
    print("Loading station names from HRDF...")
    with open(bahnhof_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.strip():
                uic = line[0:7].strip()
                # Extract the main name (before any $<1> markers)
                name_part = line[7:].strip()
                if '$<1>' in name_part:
                    name = name_part.split('$<1>')[0].strip()
                else:
                    name = name_part
                stations[uic] = name
    
    return stations

def process_hrdf_direction_data(traffic_points, hrdf_folder):
    """
    Process HRDF data to extract direction information for ATLAS sloids
    """
    print("\n=== Processing HRDF Direction Data ===")
    
    # Get all unique sloids from traffic points
    all_sloids = set(traffic_points['sloid'].dropna().unique())
    print(f"Found {len(all_sloids)} unique sloids in ATLAS data")
    
    # Parse GLEISE_LV95 to map sloids to trips
    sloid_to_trips = parse_gleise_lv95_for_sloids(hrdf_folder, all_sloids)
    
    if not sloid_to_trips:
        print("No HRDF trips found for any sloids")
        return None
    
    # Collect all unique trip keys
    all_trip_keys = set()
    for trips in sloid_to_trips.values():
        all_trip_keys.update(trips)
    
    print(f"Total unique trips to analyze: {len(all_trip_keys)}")
    
    # Extract direction information for these trips
    trip_directions = extract_fplan_directions_for_trips(hrdf_folder, all_trip_keys)
    
    print(f"Found direction info for {len(trip_directions)} trips")
    
    # Load station names
    stations = load_station_names_hrdf(hrdf_folder)
    
    # Generate direction strings for each sloid
    hrdf_results = []
    
    for sloid, trips in sloid_to_trips.items():
        unique_directions = set()
        
        for trip_tuple in trips:
            if trip_tuple in trip_directions:
                info = trip_directions[trip_tuple]
                line = info['line']
                first_stop_uic = info['first_stop']
                last_stop_uic = info['last_stop']
                
                first_stop_name = stations.get(first_stop_uic, f"Unknown({first_stop_uic})")
                last_stop_name = stations.get(last_stop_uic, f"Unknown({last_stop_uic})")
                
                line_name = ''
                if line and not line.startswith('REF'):
                    line_name = line

                direction_name_str = f"{first_stop_name} → {last_stop_name}"
                direction_uic_str = f"{first_stop_uic} → {last_stop_uic}"
                unique_directions.add((line_name, direction_name_str, direction_uic_str))
        
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
        # Reorder columns to user specification
        hrdf_df = hrdf_df[['line_name', 'sloid', 'direction_name', 'direction_uic']]
        hrdf_df = hrdf_df.sort_values(by=['sloid', 'line_name', 'direction_name'])
        return hrdf_df
    else:
        return None

def load_gtfs_file_robust(file_path, cols_to_load, dtypes_to_apply, file_key):
    """
    Robust GTFS file loader with multiple fallback strategies for corrupted CSV files
    """
    print(f"Loading GTFS file: {file_path}")
    
    # Strategy 1: Try with error handling and different engines
    strategies = [
        # Standard approach
        {'engine': 'c', 'on_bad_lines': 'skip', 'quoting': 1},
        # Python engine (slower but more robust)
        {'engine': 'python', 'on_bad_lines': 'skip', 'quoting': 1},
        # More lenient quoting
        {'engine': 'python', 'on_bad_lines': 'skip', 'quoting': 3},
        # Skip initial lines if corruption is at the beginning
        {'engine': 'python', 'on_bad_lines': 'skip', 'quoting': 1, 'skiprows': range(1, 100)},
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            print(f"  Trying strategy {i+1}/{len(strategies)}: {strategy}")
            
            if file_key == 'stop_times':
                # For large files, use smaller chunks for better memory management
                chunk_size = GTFS_FILE_CHUNK_SIZE  # Reduced from 1M to 500K for better memory control
                chunks = []
                
                # Add error handling parameters
                reader_params = {
                    'usecols': cols_to_load,
                    'dtype': dtypes_to_apply,
                    'chunksize': chunk_size,
                    'low_memory': True,
                    **strategy
                }
                
                chunk_count = 0
                for chunk in pd.read_csv(file_path, **reader_params):
                    chunks.append(chunk)
                    chunk_count += 1
                    if chunk_count % 5 == 0:  # Report every 5 chunks instead of 10
                        print(f"    Loaded {chunk_count} chunks ({chunk_count * chunk_size:,} rows)...")
                        
                    # Force garbage collection every 20 chunks to prevent memory buildup
                    if chunk_count % 20 == 0:
                        gc.collect()
                
                print(f"  Combining {chunk_count} chunks...")
                result = pd.concat(chunks, ignore_index=True)
                del chunks
                gc.collect()
                print(f"  ✓ Successfully loaded {len(result)} rows using strategy {i+1}")
                return result
            else:
                # For smaller files, load directly
                reader_params = {
                    'usecols': cols_to_load,
                    'dtype': dtypes_to_apply,
                    'low_memory': True,
                    **strategy
                }
                result = pd.read_csv(file_path, **reader_params)
                print(f"  ✓ Successfully loaded {len(result)} rows using strategy {i+1}")
                return result
                
        except Exception as e:
            print(f"  ✗ Strategy {i+1} failed: {e}")
            continue
    
    # If all strategies fail, try manual line-by-line parsing for stop_times
    if file_key == 'stop_times':
        print("  All pandas strategies failed. Attempting manual parsing...")
        return manual_parse_stop_times(file_path, cols_to_load, dtypes_to_apply)
    
    raise Exception(f"All loading strategies failed for {file_path}")

def manual_parse_stop_times(file_path, cols_to_load, dtypes_to_apply):
    """
    Manual line-by-line parser for corrupted stop_times.txt files
    """
    import csv
    
    print("  Starting manual CSV parsing...")
    
    # Read header first
    with open(file_path, 'r', encoding='utf-8') as f:
        header = f.readline().strip().split(',')
    
    # Find column indices
    col_indices = {}
    for col in cols_to_load:
        if col in header:
            col_indices[col] = header.index(col)
        else:
            raise ValueError(f"Column {col} not found in CSV header")
    
    data = []
    error_count = 0
    line_count = 0
    
    with open(file_path, 'r', encoding='utf-8') as f:
        # Skip header
        next(f)
        
        for line_num, line in enumerate(f, 2):  # Start from line 2 (after header)
            line_count += 1
            
            if line_count % 1000000 == 0:
                print(f"    Processed {line_count:,} lines, {error_count} errors")
            
            try:
                # Simple CSV parsing - split by comma and handle quotes
                fields = []
                current_field = ""
                in_quotes = False
                
                for char in line.strip():
                    if char == '"' and not in_quotes:
                        in_quotes = True
                    elif char == '"' and in_quotes:
                        in_quotes = False
                    elif char == ',' and not in_quotes:
                        fields.append(current_field.strip('"'))
                        current_field = ""
                    else:
                        current_field += char
                
                # Don't forget the last field
                fields.append(current_field.strip('"'))
                
                # Extract required columns
                if len(fields) >= max(col_indices.values()) + 1:
                    row = {}
                    for col, idx in col_indices.items():
                        value = fields[idx] if idx < len(fields) else ""
                        
                        # Apply dtype conversion
                        if col in dtypes_to_apply:
                            if dtypes_to_apply[col] == 'int32' and value:
                                row[col] = int(value)
                            else:
                                row[col] = str(value)
                        else:
                            row[col] = value
                    
                    data.append(row)
                else:
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
                if error_count < 10:  # Only print first few errors
                    print(f"    Error on line {line_num}: {e}")
                continue
    
    print(f"  Manual parsing complete: {len(data)} valid rows, {error_count} errors")
    
    return pd.DataFrame(data)

def load_gtfs_data_robust(gtfs_folder):
    """
    Load GTFS data with robust error handling
    """
    gtfs_files_to_load = {
        'routes': {'cols': ['route_id', 'route_short_name', 'route_long_name'],
                   'dtypes': {'route_id': 'str', 'route_short_name': 'str', 'route_long_name': 'str'}},
        'trips': {'cols': ['trip_id', 'route_id', 'direction_id'],
                  'dtypes': {'trip_id': 'str', 'route_id': 'str', 'direction_id': 'Int8'}},
        'stop_times': {'cols': ['trip_id', 'stop_id', 'stop_sequence'],
                       'dtypes': {'trip_id': 'str', 'stop_id': 'str', 'stop_sequence': 'int32'}},
        'stops': {'cols': ['stop_id', 'stop_name'],
                  'dtypes': {'stop_id': 'str', 'stop_name': 'str'}}
    }
    
    gtfs_data = {}
    
    for file_key, spec in gtfs_files_to_load.items():
        file_path = f"{gtfs_folder}/{file_key}.txt"
        cols_to_load = spec['cols']
        dtypes_to_apply = spec['dtypes']
        
        try:
            gtfs_data[file_key] = load_gtfs_file_robust(file_path, cols_to_load, dtypes_to_apply, file_key)
        except Exception as e:
            print(f"CRITICAL ERROR: Could not load {file_path}: {e}")
            raise
    
    return gtfs_data

if __name__ == "__main__":
    DOWNLOAD_AND_PROCESS_GTFS = True

    atlas_stops_csv_output_path="data/raw/stops_ATLAS.csv"
    # Check info here: https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date
    download_url = "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink"
    get_atlas_stops(atlas_stops_csv_output_path, download_url)
    
    # Load traffic points data - needed for both GTFS and HRDF processing
    try:
        traffic_points = pd.read_csv(atlas_stops_csv_output_path, sep=';', 
                                    usecols=['sloid', 'number', 'designation', 'designationOfficial', 'servicePointBusinessOrganisationAbbreviationEn'])
    except Exception as e:
        # If column selection fails, fall back to loading all columns
        print(f"Error loading with specific columns: {e}")
        traffic_points = pd.read_csv(atlas_stops_csv_output_path, sep=';')

    if DOWNLOAD_AND_PROCESS_GTFS:
        print("\n=== Processing GTFS Data (Optional) ===")
        # Use permalink that always redirects to the latest dataset
        GTFS_PERMALINK = "https://data.opentransportdata.swiss/de/dataset/timetable-2025-gtfs2020/permalink"

        # Download and extract GTFS data – the helper returns the folder path
        gtfs_folder = download_and_extract_gtfs(GTFS_PERMALINK)

        # Load GTFS data with robust error handling
        gtfs_data = load_gtfs_data_robust(gtfs_folder)
        
        # Extract GTFS route directions ('Start -> Finish')
        gtfs_route_directions = extract_gtfs_directions(gtfs_data)

        # Extract route and direction information per stop
        route_direction_info = extract_route_direction_per_stop(gtfs_data)
        
        # Clean up to free memory after extract_route_direction_per_stop
        for key in ['stop_times', 'trips']:
            if key in gtfs_data:
                del gtfs_data[key]
        gc.collect()
        
        # Match GTFS stops to ATLAS stops
        matches = match_gtfs_to_atlas(gtfs_data, traffic_points)
        
        # Merge matches with GTFS stops to get full stop information
        linked_stops = pd.merge(gtfs_data['stops'], matches, on='stop_id', how='left')
        
        # Clean up more memory
        del matches, gtfs_data
        gc.collect()
        
        if linked_stops is not None and route_direction_info is not None:
            try:
                integrated_data = pd.merge(linked_stops, route_direction_info, on='stop_id', how='inner')
                
                # Merge GTFS route directions into the integrated data
                integrated_data = pd.merge(integrated_data, gtfs_route_directions, on='route_id', how='left')

                # Clean up to free memory
                del linked_stops, route_direction_info, gtfs_route_directions
                gc.collect()
                
                # Save GTFS stop-routes mapping
                selected_cols = integrated_data[['stop_id', 'sloid', 'route_id', 'route_short_name', 
                                               'route_long_name', 'direction_id', 'direction']]
                selected_cols = selected_cols.sort_values(by='sloid')
                selected_cols.to_csv("data/processed/atlas_routes_gtfs.csv", index=False)
                
                # Generate matching statistics
                total_gtfs_stops = len(integrated_data['stop_id'].unique())
                matched_stops = integrated_data['sloid'].notna().sum()
                unique_sloids_matched = integrated_data['sloid'].dropna().nunique()
                
                print("\n=== GTFS Matching Statistics ===")
                print(f"Total GTFS stops in integrated data: {total_gtfs_stops}")
                print(f"GTFS stops matched to ATLAS sloids: {matched_stops}")
                print(f"Unique ATLAS sloids matched to routes: {unique_sloids_matched}")
                print(f"Saved {len(integrated_data)} rows to data/processed/atlas_routes_gtfs.csv")
                print("===========================")
                
                # Skip unmatched entries analysis to save memory
                print("\nSkipping detailed unmatched entries analysis to conserve memory")
                
                # After the matching statistics, summarize duplicates without detailed listing
                if 'sloid' in integrated_data.columns:
                    duplicates_count = integrated_data[integrated_data.duplicated(subset=['sloid'], keep=False)]['sloid'].nunique()
                    print(f"\nFound {duplicates_count} ATLAS sloids matched to multiple GTFS stops")
                
            except Exception as e:
                print(f"Error processing GTFS data: {e}")
                import traceback
                traceback.print_exc()

    # Download and extract HRDF data
    hrdf_url = "https://data.opentransportdata.swiss/dataset/6083374f-6a6a-4d84-a6f7-0816493a0766/resource/95fd7309-cc17-4af7-a2f7-e77f04eb328f/download/oev_sammlung_ch_hrdf_5_40_41_2025_20250711_220742.zip"
    hrdf_folder_name = "oev_sammlung_ch_hrdf_5_40_41_2025_20250711_220742"
    hrdf_folder = os.path.join("data/raw", hrdf_folder_name)
    download_and_extract_hrdf(hrdf_url, hrdf_folder)
    
    # Process HRDF direction data
    if os.path.exists(hrdf_folder):
        hrdf_results = process_hrdf_direction_data(traffic_points, hrdf_folder)
        
        if hrdf_results is not None:
            # Save HRDF direction data
            hrdf_results.to_csv("data/processed/atlas_routes_hrdf.csv", index=False)
            
            print("\n=== HRDF Direction Statistics ===")
            print(f"Total HRDF direction entries: {len(hrdf_results)}")
            print(f"Unique sloids with HRDF directions: {hrdf_results['sloid'].nunique()}")
            print(f"Saved {len(hrdf_results)} rows to data/processed/atlas_routes_hrdf.csv")
            print("===========================")
        else:
            print("No HRDF direction data could be processed")
    else:
        print(f"HRDF folder {hrdf_folder} not found, skipping HRDF processing")
    
    print("Done!")

