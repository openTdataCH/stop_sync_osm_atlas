# 1: Utility Functions and Data Loading
import pandas as pd
import xml.etree.ElementTree as ET
from collections import defaultdict
from tqdm import tqdm
import logging, json
import numpy as np
from scipy.spatial import KDTree
# Import functions from distance_matching.py
from matching_process.distance_matching import distance_matching, transform_for_distance_matching, haversine_distance
# Import route_matching function
from matching_process.route_matching import route_matching
# Import standardize_operator from org_standaarization.py
from matching_process.org_standaarization import standardize_operator

# Setup logging for detailed match candidate logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def is_osm_station(osm_node):
    """Check if an OSM node is a station based on its tags, excluding aerialway stations."""
    tags = osm_node.get('tags', {})
    # If it's an aerialway station, it should not be filtered out by this function.
    if tags.get('aerialway') == 'station':
        return False
    # Otherwise, check if it's a railway or public_transport station.
    if tags.get('railway') == 'station' or tags.get('public_transport') == 'station':
        return True
    return False


def parse_osm_xml(xml_file):
    """
    Parse the OSM XML file and build a comprehensive data structure that can be used for all matching strategies:
      - all_nodes: Complete representation of all OSM nodes with coordinates and tags
      - uic_ref_dict: { uic_ref : [ {node_id, lat, lon, local_ref, tags}, ... ] }
      - name_index: { name_value : [node_info, ...] } for keys: 'name', 'uic_name', 'gtfs:name'
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()
    all_nodes = {}
    uic_ref_dict = defaultdict(list)
    name_index = defaultdict(list)
    ref_tag_count = 0
    
    for node in root.iter("node"):
        node_id = node.get("id")
        try:
            lat = float(node.get("lat"))
            lon = float(node.get("lon"))
        except (ValueError, TypeError):
            continue
            
        local_ref = None
        tags = {}
        
        for tag in node.findall("tag"):
            k = tag.get("k")
            v = tag.get("v")
            # Standardize operator names
            if k == "operator":
                original_v = v
                v, was_changed = standardize_operator(v)
                if was_changed:
                    tags['original_operator'] = original_v
            tags[k] = v
            if k == "local_ref":
                local_ref = v
            elif k == "ref":
                ref_tag_count += 1
                if not local_ref:
                    local_ref = v
        
        # Create node entry that will be used in all data structures
        node_entry = {
            'node_id': node_id,
            'lat': lat,
            'lon': lon,
            'local_ref': local_ref,
            'tags': tags
        }
        
        # Store in main nodes dictionary by coordinates
        all_nodes[(lat, lon)] = node_entry
        
        # Build UIC reference index
        if "uic_ref" in tags:
            uic_val = tags["uic_ref"]
            uic_ref_dict[uic_val].append(node_entry)
        
        # Build name index
        for key in ['name', 'uic_name', 'gtfs:name']:
            if key in tags:
                name_index[tags[key]].append(node_entry)
    
    logger.info(f"Parsed OSM XML: {len(all_nodes)} nodes, {len(uic_ref_dict)} uic_ref entries; {ref_tag_count} 'ref' tags encountered.")
    return all_nodes, uic_ref_dict, name_index


# 2: Matching Functions & Station-Level Grouping

def exact_matching(atlas_df, uic_ref_dict):
    """
    Exact matching:
      - ATLAS 'number' equals OSM 'uic_ref'
      - When multiple candidates exist, try to match ATLAS 'designation' with OSM 'local_ref' exactly.
      - Only allow many-to-one matching if there's only one OSM node for the UIC reference
      - Only allow one-to-many matching if there's only one ATLAS entry for the UIC reference
    Returns:
      - List of match records (dictionaries)
      - List of unmatched ATLAS rows (as Series)
      - Set of used OSM node IDs.
    """
    matches = []
    unmatched = []
    used_osm_ids = set()
    
    # Group ATLAS entries by UIC reference (number)
    grouped_atlas = atlas_df.groupby(atlas_df['number'].astype(str))
    
    for uic_ref, group in tqdm(grouped_atlas, total=len(grouped_atlas), desc="Exact Matching"):
        atlas_entries = group.to_dict(orient="records")
        osm_candidates = uic_ref_dict.get(str(uic_ref), [])
        
        # Skip if no OSM candidates for this UIC reference
        if not osm_candidates:
            for entry in atlas_entries:
                unmatched.append(entry)
            continue
        
        # Filter out already used OSM nodes and OSM stations
        available_osm = [
            cand for cand in osm_candidates 
            if cand['node_id'] not in used_osm_ids and not is_osm_station(cand)
        ]
        
        # Case 1: No available OSM nodes (all used previously or are stations)
        if not available_osm:
            for entry in atlas_entries:
                unmatched.append(entry)
            continue
        
        # Case 2: Only one OSM node for this UIC - match all ATLAS entries to it
        if len(available_osm) == 1:
            osm_node = available_osm[0]
            for atlas_entry in atlas_entries:
                csv_lat = atlas_entry['wgs84North']
                csv_lon = atlas_entry['wgs84East']
                otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
                designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()
                
                dist = haversine_distance(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                osm_network = osm_node['tags'].get('network', '')
                osm_operator = osm_node['tags'].get('operator', '')
                osm_amenity = osm_node['tags'].get('amenity', '')
                osm_railway = osm_node['tags'].get('railway', '')
                osm_aerialway = osm_node['tags'].get('aerialway', '')
                
                matches.append({
                    'sloid': atlas_entry['sloid'],
                    'number': atlas_entry['number'],
                    'uic_ref': str(uic_ref),
                    'csv_designation': otdp_designation,
                    'csv_designation_official': designation_official,
                    'csv_lat': csv_lat,
                    'csv_lon': csv_lon,
                    'csv_business_org_abbr': business_org_abbr,
                    'osm_node_id': osm_node['node_id'],
                    'osm_lat': osm_node['lat'],
                    'osm_lon': osm_node['lon'],
                    'osm_local_ref': osm_node.get('local_ref'),
                    'osm_network': osm_network,
                    'osm_operator': osm_operator,
                    'osm_original_operator': osm_node['tags'].get('original_operator'),
                    'osm_amenity': osm_amenity,
                    'osm_railway': osm_railway,
                    'osm_aerialway': osm_aerialway,
                    'osm_name': osm_node['tags'].get('name', ''),
                    'osm_uic_name': osm_node['tags'].get('uic_name', ''),
                    'osm_uic_ref': osm_node['tags'].get('uic_ref', ''),
                    'osm_public_transport': osm_node['tags'].get('public_transport', ''),
                    'distance_m': dist,
                    'match_type': 'exact',
                    'candidate_pool_size': len(available_osm),
                    'matching_notes': "Single OSM node for this UIC reference"
                })
            used_osm_ids.add(osm_node['node_id'])
            continue
        
        # Case 3: Only one ATLAS entry - match to all available OSM nodes
        if len(atlas_entries) == 1:
            atlas_entry = atlas_entries[0]
            
            csv_lat = atlas_entry['wgs84North']
            csv_lon = atlas_entry['wgs84East']
            otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
            designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
            business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()
            
            # Match to all available OSM nodes
            for osm_node in available_osm:
                dist = haversine_distance(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                osm_network = osm_node['tags'].get('network', '')
                osm_operator = osm_node['tags'].get('operator', '')
                osm_amenity = osm_node['tags'].get('amenity', '')
                osm_railway = osm_node['tags'].get('railway', '')
                osm_aerialway = osm_node['tags'].get('aerialway', '')
                
                matches.append({
                    'sloid': atlas_entry['sloid'],
                    'number': atlas_entry['number'],
                    'uic_ref': str(uic_ref),
                    'csv_designation': otdp_designation,
                    'csv_designation_official': designation_official,
                    'csv_lat': csv_lat,
                    'csv_lon': csv_lon,
                    'csv_business_org_abbr': business_org_abbr,
                    'osm_node_id': osm_node['node_id'],
                    'osm_lat': osm_node['lat'],
                    'osm_lon': osm_node['lon'],
                    'osm_local_ref': osm_node.get('local_ref'),
                    'osm_network': osm_network,
                    'osm_operator': osm_operator,
                    'osm_original_operator': osm_node['tags'].get('original_operator'),
                    'osm_amenity': osm_amenity,
                    'osm_railway': osm_railway,
                    'osm_aerialway': osm_aerialway,
                    'osm_name': osm_node['tags'].get('name', ''),
                    'osm_uic_name': osm_node['tags'].get('uic_name', ''),
                    'osm_uic_ref': osm_node['tags'].get('uic_ref', ''),
                    'osm_public_transport': osm_node['tags'].get('public_transport', ''),
                    'distance_m': dist,
                    'match_type': 'exact',
                    'candidate_pool_size': len(available_osm),
                    'matching_notes': "Single ATLAS entry matched to multiple OSM nodes with same UIC reference"
                })
                used_osm_ids.add(osm_node['node_id'])
            continue
        
        # Case 4: Multiple ATLAS and multiple OSM nodes - try to match by designation/local_ref
        matched_atlas_ids = set()
        matched_osm_ids = set()
        
        # First pass: Try to match based on exact local_ref/designation match
        for atlas_entry in atlas_entries:
            sloid = atlas_entry['sloid']
            if sloid in matched_atlas_ids:
                continue
                
            otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
            
            for osm_node in available_osm:
                osm_id = osm_node['node_id']
                if osm_id in matched_osm_ids or osm_id in used_osm_ids:
                    continue
                
                # Skip if OSM node is a station (already filtered, but double-check)
                if is_osm_station(osm_node):
                    continue
                    
                osm_local_ref = str(osm_node.get('local_ref') or "").strip()
                
                # Check for exact designation/local_ref match
                if otdp_designation and osm_local_ref and otdp_designation.lower() == osm_local_ref.lower():
                    csv_lat = atlas_entry['wgs84North']
                    csv_lon = atlas_entry['wgs84East']
                    designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                    business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()
                    
                    dist = haversine_distance(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                    osm_network = osm_node['tags'].get('network', '')
                    osm_operator = osm_node['tags'].get('operator', '')
                    osm_amenity = osm_node['tags'].get('amenity', '')
                    osm_railway = osm_node['tags'].get('railway', '')
                    osm_aerialway = osm_node['tags'].get('aerialway', '')
                    
                    matches.append({
                        'sloid': sloid,
                        'number': atlas_entry['number'],
                        'uic_ref': str(uic_ref),
                        'csv_designation': otdp_designation,
                        'csv_designation_official': designation_official,
                        'csv_lat': csv_lat,
                        'csv_lon': csv_lon,
                        'csv_business_org_abbr': business_org_abbr,
                        'osm_node_id': osm_id,
                        'osm_lat': osm_node['lat'],
                        'osm_lon': osm_node['lon'],
                        'osm_local_ref': osm_local_ref,
                        'osm_network': osm_network,
                        'osm_operator': osm_operator,
                        'osm_original_operator': osm_node['tags'].get('original_operator'),
                        'osm_amenity': osm_amenity,
                        'osm_railway': osm_railway,
                        'osm_aerialway': osm_aerialway,
                        'osm_name': osm_node['tags'].get('name', ''),
                        'osm_uic_name': osm_node['tags'].get('uic_name', ''),
                        'osm_uic_ref': osm_node['tags'].get('uic_ref', ''),
                        'osm_public_transport': osm_node['tags'].get('public_transport', ''),
                        'distance_m': dist,
                        'match_type': 'exact',
                        'candidate_pool_size': len(available_osm),
                        'matching_notes': "Exact local_ref/designation match"
                    })
                    
                    matched_atlas_ids.add(sloid)
                    matched_osm_ids.add(osm_id)
                    used_osm_ids.add(osm_id)
                    break
        
        # Add all unmatched atlas entries to the unmatched list
        for atlas_entry in atlas_entries:
            if atlas_entry['sloid'] not in matched_atlas_ids:
                unmatched.append(atlas_entry)
    
    return matches, unmatched, used_osm_ids


def name_based_matching(atlas_df, name_index):
    """
    Name-based matching:
      - Compare ATLAS 'designationOfficial' against OSM 'name', 'uic_name', 'gtfs:name'.
      - Then (if possible) match ATLAS 'designation' with OSM 'local_ref' exactly.
    Returns:
      - List of match records (dictionaries)
      - List of unmatched ATLAS rows (as Series)
      - Set of used OSM node IDs.
    """
    matches = []
    unmatched = []
    used_osm_ids = set()
    for idx, row in tqdm(atlas_df.iterrows(), total=len(atlas_df), desc="Name-Based Matching"):
        sloid = row['sloid']
        otdp_number = str(row['number'])
        designation_official_raw = row.get('designationOfficial', "")
        if pd.isna(designation_official_raw):
            designation_official = ""
        else:
            designation_official = str(designation_official_raw).strip()
        otdp_designation = str(row['designation']).strip() if pd.notna(row['designation']) else ""
        csv_lat = row['wgs84North']
        csv_lon = row['wgs84East']
        # Get business organization abbreviation
        business_org_abbr = str(row.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()
        
        note = ""
        if designation_official == "":
            note = "Missing designationOfficial."
            unmatched.append(row)
            continue
        candidates = name_index.get(designation_official, [])
        candidates = [
            cand for cand in candidates 
            if cand['node_id'] not in used_osm_ids and not is_osm_station(cand)
        ]
        candidate_pool_size = len(candidates)
        candidate = None
        if candidate_pool_size == 1:
            candidate = candidates[0]
            note = "Single candidate via name index."
        elif candidate_pool_size > 1:
            for cand in candidates:
                osm_local_ref = str(cand.get('local_ref') or "").strip()
                if otdp_designation and osm_local_ref.lower() == otdp_designation.lower():
                    candidate = cand
                    note = "Multiple candidates; exact local_ref match in name index."
                    break
        if candidate:
            used_osm_ids.add(candidate['node_id'])
            dist = haversine_distance(csv_lat, csv_lon, candidate['lat'], candidate['lon'])
            # Extract OSM network and operator tags
            osm_network = candidate['tags'].get('network', '')
            osm_operator = candidate['tags'].get('operator', '')
            osm_amenity = candidate['tags'].get('amenity', '')
            osm_railway = candidate['tags'].get('railway', '')
            osm_aerialway = candidate['tags'].get('aerialway', '')
            
            matches.append({
                'sloid': sloid,
                'number': row['number'],  # Added station number
                'uic_ref': otdp_number,
                'csv_designation_official': designation_official,
                'csv_designation': otdp_designation,
                'csv_lat': csv_lat,
                'csv_lon': csv_lon,
                'csv_business_org_abbr': business_org_abbr,  # Added business organization abbreviation
                'osm_node_id': candidate['node_id'],
                'osm_lat': candidate['lat'],
                'osm_lon': candidate['lon'],
                'osm_local_ref': candidate.get('local_ref'),
                'osm_network': osm_network,  # Added network tag
                'osm_operator': osm_operator,  # Added operator tag
                'osm_original_operator': candidate['tags'].get('original_operator'),
                'osm_amenity': osm_amenity,
                'osm_railway': osm_railway,
                'osm_aerialway': osm_aerialway,
                'osm_name': candidate['tags'].get('name', ''),
                'osm_uic_name': candidate['tags'].get('uic_name', ''),
                'osm_uic_ref': candidate['tags'].get('uic_ref', ''),
                'osm_public_transport': candidate['tags'].get('public_transport', ''),
                'distance_m': dist,
                'match_type': 'name',
                'candidate_pool_size': candidate_pool_size,
                'matching_notes': note
            })
        else:
            unmatched.append(row)
    return matches, unmatched, used_osm_ids
# 3: Distance Matching


# 4: Final Pipeline

# ----------------------------
# Logger setup (if not already configured)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
# ----------------------------


def final_pipeline(route_matching_strategy='hrdf'):
    """
    Execute the complete matching pipeline:
    1. Load data from CSV and XML files
    2. Perform exact matching using UIC references
    3. Perform name-based matching for remaining unmatched entries
    4. Perform distance-based matching for any still unmatched entries
    5. Perform route-based matching for remaining unmatched entries based on the chosen strategy.
    """
    # --- Load Data ---
    atlas_csv_file = "data/raw/stops_ATLAS.csv"
    osm_xml_file = "data/raw/osm_data.xml"
    
    logger.info("Loading and parsing data files...")
    atlas_df = pd.read_csv(atlas_csv_file, sep=";")
    all_osm_nodes, uic_ref_dict, name_index = parse_osm_xml(osm_xml_file)

    # --- Identify Duplicate ATLAS entries ---
    # Keep=False marks all occurrences of duplicates as True
    duplicate_atlas_mask = atlas_df.duplicated(subset=['number', 'designation'], keep=False)
    # Add condition to exclude rows where designation is empty or NaN
    non_empty_designation_mask = atlas_df['designation'].notna() & (atlas_df['designation'].astype(str).str.strip() != '')
    duplicate_atlas_mask = duplicate_atlas_mask & non_empty_designation_mask

    # Create a map from a duplicate sloid to another sloid in its duplicate group
    duplicate_sloid_map = {}
    duplicate_rows_df = atlas_df[duplicate_atlas_mask]
    # Group by 'number' and 'designation' to find duplicate sets
    for _, group_df in duplicate_rows_df.groupby(['number', 'designation'], sort=False):
        if len(group_df) > 1:
            sloids_in_group = group_df['sloid'].astype(str).tolist()
            for current_sloid in sloids_in_group:
                # Find the first other sloid in the group to point to
                other_sloid_pointer = next((s_other for s_other in sloids_in_group if s_other != current_sloid), None)
                if other_sloid_pointer:
                    duplicate_sloid_map[current_sloid] = other_sloid_pointer

    num_duplicate_atlas_rows = len(atlas_df[duplicate_atlas_mask]) # Count rows marked as duplicate
    logger.info(f"Identified {num_duplicate_atlas_rows} ATLAS entries (rows) that are part of a duplicate group based on non-empty 'number' and 'designation'.")
    
    # --- Exact Matching ---
    logger.info("Performing exact matching...")
    exact_matches, unmatched_after_exact, used_osm_ids_exact = exact_matching(atlas_df, uic_ref_dict)
    logger.info(f"Exact matching: {len(exact_matches)} matches; {len(unmatched_after_exact)} unmatched.")
    
    # --- Name-Based Matching ---
    logger.info("Performing name-based matching...")
    unmatched_after_exact_df = pd.DataFrame(unmatched_after_exact)
    name_matches, unmatched_after_name, used_osm_ids_name = name_based_matching(unmatched_after_exact_df, name_index)
    unmatched_after_name_df = pd.DataFrame(unmatched_after_name)
    logger.info(f"Name-based matching: {len(name_matches)} matches; {len(unmatched_after_name_df)} unmatched.")
    
    # --- Collect Used OSM IDs ---
    used_osm_ids_total = set()
    for m in exact_matches + name_matches:
        if 'osm_node_id' in m:
            used_osm_ids_total.add(m['osm_node_id'])
    
    # --- Distance Matching ---
    logger.info("Performing distance-based matching...")
    # Filter out already matched nodes for distance matching
    filtered_osm_nodes = transform_for_distance_matching(all_osm_nodes, filtered=True, used_node_ids=used_osm_ids_total)
    
    # Further filter out OSM stations from filtered_osm_nodes before passing to distance_matching
    filtered_osm_nodes_no_stations = {
        coord: node_info for coord, node_info in filtered_osm_nodes.items()
        if not is_osm_station(node_info)
    }

    # Initialize lists for actual matches and those with no nearby OSM
    actual_distance_matches = []
    no_nearby_osm_entries = []
    
    if len(unmatched_after_name_df) > 0:
        # Get all results from distance_matching
        all_distance_results = distance_matching(
            unmatched_after_name_df, 
            filtered_osm_nodes_no_stations, # Use the station-filtered list
            max_distance=50,
            all_xml_nodes_for_stage4=all_osm_nodes # Pass all OSM nodes for Stage 4 check
        )
        # Separate the results
        for match in all_distance_results:
            if match.get('match_type') == 'no_osm_within_50m':
                no_nearby_osm_entries.append(match)
            else:
                actual_distance_matches.append(match)
    else:
        all_distance_results = [] # Keep this for consistency if needed elsewhere, though separation makes it less direct

    logger.info(f"Distance matching: Found {len(actual_distance_matches)} actual matches and {len(no_nearby_osm_entries)} ATLAS entries with no OSM nodes within 50m.")
    
    # Extract SLOIDs for entries with no nearby OSM nodes
    no_nearby_osm_sloids = {m['sloid'] for m in no_nearby_osm_entries if 'sloid' in m}
    
    # Update used OSM IDs only with actual matches
    for m in actual_distance_matches:
        if 'osm_node_id' in m and m['osm_node_id'] != 'NA': # Ensure 'NA' isn't added
            used_osm_ids_total.add(m['osm_node_id'])
    
    # --- Route Matching ---
    logger.info(f"Performing route-based matching with strategy: '{route_matching_strategy}'...")
    # Track matched SLOIDs from previous stages (including actual distance matches)
    matched_sloids = set()
    for m in exact_matches + name_matches + actual_distance_matches: # Use actual_distance_matches
        if 'sloid' in m:
            matched_sloids.add(m['sloid'])
    
    # Filter unmatched entries after *actual* distance matching
    # This df still contains the entries that will be marked as 'no_osm_within_50m'
    unmatched_after_distance_df = unmatched_after_name_df[~unmatched_after_name_df['sloid'].isin(matched_sloids)]

    # Filter out already matched nodes for route matching
    filtered_osm_nodes_for_route = {
        coord: node_info for coord, node_info in all_osm_nodes.items()
        if node_info['node_id'] not in used_osm_ids_total
    }
    
    # Route matching is performed on entries not yet matched by exact, name, or actual distance
    if len(unmatched_after_distance_df) > 0:
        route_matches = route_matching(
            unmatched_after_distance_df, 
            filtered_osm_nodes_for_route, 
            osm_xml_file=osm_xml_file, 
            max_distance=50,
            strategy=route_matching_strategy
        )
    else:
        route_matches = []
    logger.info(f"Route matching: {len(route_matches)} matches.")
    
    # Update used OSM IDs with route matches
    for m in route_matches:
        if 'osm_node_id' in m:
            used_osm_ids_total.add(m['osm_node_id'])

    # Update matched SLOIDs with route matches
    for m in route_matches:
        if 'sloid' in m:
            matched_sloids.add(m['sloid']) # Add route matched sloids

    # --- Find Remaining Unmatched Nodes ---
    unmatched_osm_nodes = [node for node in all_osm_nodes.values() if node['node_id'] not in used_osm_ids_total]
    logger.info(f"Unmatched OSM nodes: {len(unmatched_osm_nodes)}")

    # --- Add check for isolated OSM nodes (no ATLAS stop within 50m) ---
    logger.info("Checking for isolated unmatched OSM nodes...")
    if unmatched_osm_nodes:
        # Create a spatial index for all ATLAS stops for efficient lookup
        atlas_coords = atlas_df[['wgs84North', 'wgs84East']].to_numpy()
        atlas_rad = np.radians(atlas_coords)
        atlas_3d = np.array([
            np.cos(atlas_rad[:, 0]) * np.cos(atlas_rad[:, 1]),
            np.cos(atlas_rad[:, 0]) * np.sin(atlas_rad[:, 1]),
            np.sin(atlas_rad[:, 0])
        ]).T
        atlas_kdtree = KDTree(atlas_3d)
        
        check_radius_m = 50
        check_radius_rad = 2 * np.sin((check_radius_m / 6371000.0) / 2)
        
        isolated_osm_node_ids = set()
        for osm_node in unmatched_osm_nodes:
            osm_lat_rad = np.radians(osm_node['lat'])
            osm_lon_rad = np.radians(osm_node['lon'])
            query_point = [
                np.cos(osm_lat_rad) * np.cos(osm_lon_rad),
                np.cos(osm_lat_rad) * np.sin(osm_lon_rad),
                np.sin(osm_lat_rad)
            ]
            
            # Find indices of ATLAS stops within the radius
            indices = atlas_kdtree.query_ball_point(query_point, check_radius_rad)
            if not indices: # If the list of indices is empty, no stops were found
                isolated_osm_node_ids.add(osm_node['node_id'])
        
        # Add 'is_isolated' flag to each unmatched OSM node
        for osm_node in unmatched_osm_nodes:
            osm_node['is_isolated'] = osm_node['node_id'] in isolated_osm_node_ids

        logger.info(f"Found {len(isolated_osm_node_ids)} isolated unmatched OSM nodes.")

    # --- Check how many unmatched nodes have routes and UIC references ---
    unmatched_nodes_with_uic = [node for node in unmatched_osm_nodes if 'uic_ref' in node['tags']]
    unmatched_nodes_with_uic_count = len(unmatched_nodes_with_uic)
    
    # Check how many unmatched nodes have local_ref
    unmatched_nodes_with_local_ref = [node for node in unmatched_osm_nodes if node.get('local_ref')]
    unmatched_nodes_with_local_ref_count = len(unmatched_nodes_with_local_ref)

    # Read osm_nodes_with_routes.csv to check which nodes have routes
    try:
        nodes_with_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
        # Get unique node IDs from the CSV
        nodes_with_routes = set(nodes_with_routes_df['node_id'].astype(str).unique())
        
        # Count unmatched nodes that are in the routes file
        unmatched_with_routes = [node for node in unmatched_osm_nodes 
                                if str(node['node_id']) in nodes_with_routes]
        unmatched_with_routes_count = len(unmatched_with_routes)
    except Exception as e:
        logger.warning(f"Could not check nodes with routes: {e}")
        unmatched_with_routes_count = 0

    # --- Combine All Matches ---
    # Combine only actual matches
    all_matches = exact_matches + name_matches + actual_distance_matches + route_matches
    all_matches_df = pd.DataFrame(all_matches)
    
    # --- Calculate Final Unmatched ATLAS Entries ---
    # The definition of final_unmatched_atlas naturally includes those identified as 'no_osm_within_50m'
    # because their sloids were not added to matched_sloids from the distance phase.
    final_unmatched_atlas = []
    # We need to start from the original atlas_df to correctly identify all unmatched
    all_atlas_sloids = set(atlas_df['sloid'])
    final_unmatched_sloids = all_atlas_sloids - matched_sloids
    
    # Create the final unmatched dataframe from the original atlas_df
    final_unmatched_atlas_df = atlas_df[atlas_df['sloid'].isin(final_unmatched_sloids)]
    final_unmatched_atlas = final_unmatched_atlas_df.to_dict(orient="records")

    logger.info(f"Final unmatched ATLAS entries: {len(final_unmatched_atlas)}")
    # Count the entries with no nearby OSM nodes (already calculated)
    # no_nearby_osm_entries = [match for match in all_matches if match.get('match_type') == 'no_osm_within_50m'] # This line is removed as it's calculated earlier
    print(f"ATLAS entries with no OSM nodes within 50 meters: {len(no_nearby_osm_entries)}") # Use the count from separation
    
    # --- Prepare Data for Database Import ---
    base_data = {
        "matched": all_matches_df.to_dict(orient="records"),
        "unmatched_atlas": final_unmatched_atlas, # Use the correctly calculated list
        "unmatched_osm": unmatched_osm_nodes
    }
    
    # --- Count Matches by Type for Final Report ---
    # Split Stage 1 distance matches into regular and stop_position types (using actual_distance_matches)
    stage1_distance_matches_regular = len([m for m in actual_distance_matches # Use actual_distance_matches
                                          if m['match_type'].startswith('distance_matching_1_') 
                                          and not m['match_type'].endswith('_stop_position')])
    stage1_distance_matches_stop_position = len([m for m in actual_distance_matches # Use actual_distance_matches
                                               if m['match_type'].startswith('distance_matching_1_') 
                                               and m['match_type'].endswith('_stop_position')])
    stage1_distance_matches_total = stage1_distance_matches_regular + stage1_distance_matches_stop_position

    stage2_distance_matches = len([m for m in actual_distance_matches if m['match_type'] == 'distance_matching_2']) # Use actual_distance_matches
    stage3a_distance_matches = len([m for m in actual_distance_matches if m['match_type'] == 'distance_matching_3a']) # Use actual_distance_matches
    stage3b_distance_matches = len([m for m in actual_distance_matches if m['match_type'] == 'distance_matching_3b']) # Use actual_distance_matches
    
    # Count route matching stages
    route_gtfs_matches = [m for m in route_matches if m['match_type'].startswith('route_gtfs')]
    route_hrdf_matches = [m for m in route_matches if m['match_type'].startswith('route_hrdf')]
    
    # --- Print Final Summary ---
    print("==== FINAL MATCHING SUMMARY ====")
    print(f"Total ATLAS entries (with coordinates): {len(atlas_df)}")
    print(f"Exact matches: {len(exact_matches)}")
    print(f"Name-based matches: {len(name_matches)}")
    print(f"Distance-based matches (actual): {len(actual_distance_matches)}") # Report actual count
    print(f"  ├─ Stage 1 (Group-based proximity): {stage1_distance_matches_total}")
    print(f"  │  ├─ Using all nodes: {stage1_distance_matches_regular}")
    print(f"  │  └─ Using stop_position nodes only: {stage1_distance_matches_stop_position}")
    print(f"  ├─ Stage 2 (Exact local_ref match): {stage2_distance_matches}")
    print(f"  ├─ Stage 3a (Single candidate): {stage3a_distance_matches}")
    print(f"  └─ Stage 3b (Relative distance ratio): {stage3b_distance_matches}")
    # Removed Stage 4 from here as it's reported with unmatched
    print(f"Route-based matches: {len(route_matches)}")
    print(f"  ├─ Using GTFS data: {len(route_gtfs_matches)}")
    print(f"  └─ Using HRDF data: {len(route_hrdf_matches)}")
    if 'hrdf' in route_matching_strategy:
        hrdf_name_matches = sum(1 for m in route_hrdf_matches if 'name' in m['match_type'])
        hrdf_uic_matches = sum(1 for m in route_hrdf_matches if 'uic' in m['match_type'])
        hrdf_both_matches = sum(1 for m in route_hrdf_matches if 'name' in m['match_type'] and 'uic' in m['match_type'])
        print(f"     ├─ By Name Direction: {hrdf_name_matches}")
        print(f"     ├─ By UIC Direction: {hrdf_uic_matches}")
        print(f"     └─ By Both: {hrdf_both_matches}")

    print(f"Total matched (all methods): {len(all_matches_df)}") # all_matches now excludes 'no_osm_within_50m'
    print(f"Unmatched ATLAS entries: {len(final_unmatched_atlas)}")
    # Report 'no_osm_within_50m' as a subset of unmatched
    print(f"  └─ Of which have no OSM nodes within 50m: {len(no_nearby_osm_entries)}")
    print(f"Unmatched OSM nodes: {len(unmatched_osm_nodes)}")
    print(f"  ├─ With at least one route: {unmatched_with_routes_count}")
    print(f"  ├─ With UIC reference: {unmatched_nodes_with_uic_count}")
    print(f"  └─ With local_ref: {unmatched_nodes_with_local_ref_count}")

    # --- Duplicate Summary ---
    # Count how many of the matched/unmatched entries are themselves duplicates
    matched_duplicate_items_count = sum(1 for m in all_matches if 'sloid' in m and str(m['sloid']) in duplicate_sloid_map)
    unmatched_duplicate_items_count = sum(1 for row in final_unmatched_atlas if str(row['sloid']) in duplicate_sloid_map)
    
    # Total unique sloids that are part of a duplicate group and have a mapping
    total_unique_sloids_in_duplication = len(duplicate_sloid_map)

    print(f"Duplicated ATLAS entries (unique sloids involved in a duplication): {total_unique_sloids_in_duplication}")
    print(f"  ├─ Matched items that are duplicates: {matched_duplicate_items_count}")
    print(f"  └─ Unmatched items that are duplicates: {unmatched_duplicate_items_count}")

    print("Base data is ready for database import.")
    
    # Return the map of duplicate sloids
    return base_data, duplicate_sloid_map, no_nearby_osm_sloids

