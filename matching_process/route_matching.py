import pandas as pd
import logging
from collections import defaultdict
from tqdm import tqdm
import sys
from math import radians, sin, cos, sqrt, atan2
import xml.etree.ElementTree as ET
import os
# Setup logging
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def _get_osm_directions_from_xml(xml_file):
    """
    Parses the raw OSM XML to create a map of OSM node IDs to their route direction strings.
    Returns two maps: one for name-based directions and one for UIC-based directions.
    """
    logger.info("Parsing OSM XML for route direction strings (name and UIC)...")
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except (ET.ParseError, FileNotFoundError) as e:
        logger.error(f"Failed to parse {xml_file}: {e}")
        return defaultdict(set), defaultdict(set)

    node_id_to_name = {}
    node_id_to_uic = {}
    for node in root.findall(".//node"):
        node_id = node.get('id')
        for tag in node.findall("./tag"):
            if tag.get('k') == 'name':
                node_id_to_name[node_id] = tag.get('v')
            elif tag.get('k') == 'uic_ref':
                node_id_to_uic[node_id] = tag.get('v')

    osm_name_directions_map = defaultdict(set)
    osm_uic_directions_map = defaultdict(set)
    for relation in root.findall(".//relation"):
        if any(tag.get('k') == 'type' and tag.get('v') == 'route' for tag in relation.findall("./tag")):
            member_nodes = [member.get('ref') for member in relation.findall("./member[@type='node']")]
            if len(member_nodes) >= 2:
                first_node_id, last_node_id = member_nodes[0], member_nodes[-1]
                
                first_name, last_name = node_id_to_name.get(first_node_id), node_id_to_name.get(last_node_id)
                if first_name and last_name:
                    direction_string = f"{first_name} → {last_name}"
                    for node_id in member_nodes:
                        osm_name_directions_map[node_id].add(direction_string)

                first_uic, last_uic = node_id_to_uic.get(first_node_id), node_id_to_uic.get(last_node_id)
                if first_uic and last_uic:
                    direction_string = f"{first_uic} → {last_uic}"
                    for node_id in member_nodes:
                        osm_uic_directions_map[node_id].add(direction_string)
    
    logger.info(f"Derived name directions for {len(osm_name_directions_map)} and UIC directions for {len(osm_uic_directions_map)} OSM nodes.")
    return osm_name_directions_map, osm_uic_directions_map

def _create_match_dict(csv_row, osm_node, distance, match_type, notes, **kwargs):
    """Helper to create a standardized match dictionary."""
    match = {
        'sloid': csv_row['sloid'],
        'number': csv_row.get('number'),
        'csv_lat': csv_row['wgs84North'],
        'csv_lon': csv_row['wgs84East'],
        'csv_business_org_abbr': csv_row.get('servicePointBusinessOrganisationAbbreviationEn', ''),
        'osm_node_id': osm_node['node_id'],
        'osm_lat': osm_node['lat'],
        'osm_lon': osm_node['lon'],
        'distance_m': distance,
        'osm_uic_ref': osm_node['tags'].get('uic_ref', ''),
        'match_type': match_type,
        'matching_notes': notes,
    }
    match.update(kwargs)
    return match

def _perform_hrdf_matching(unmatched_df, xml_nodes, osm_xml_file, used_osm_nodes):
    """Performs route matching using HRDF direction strings and UIC references."""
    logger.info("Performing HRDF-based route matching...")

    try:
        hrdf_routes = pd.read_csv("data/processed/atlas_routes_hrdf.csv")
        atlas_name_directions = defaultdict(set)
        atlas_uic_directions = defaultdict(set)
        for _, row in hrdf_routes.iterrows():
            sloid_str = str(row['sloid'])
            if pd.notna(row.get('direction_name')):
                atlas_name_directions[sloid_str].add(row['direction_name'])
            if pd.notna(row.get('direction_uic')):
                atlas_uic_directions[sloid_str].add(row['direction_uic'])
    except FileNotFoundError:
        logger.error("HRDF routes file not found. Skipping HRDF matching.")
        return [], set()

    osm_name_directions, osm_uic_directions = _get_osm_directions_from_xml(osm_xml_file)
    
    osm_by_uic = defaultdict(list)
    for node in xml_nodes.values():
        if node['node_id'] not in used_osm_nodes:
            uic_ref = node.get('tags', {}).get('uic_ref')
            if uic_ref:
                osm_by_uic[uic_ref.strip()].append(node)

    matches = []
    used_osm_ids_hrdf = set()

    for _, atlas_row in tqdm(unmatched_df.iterrows(), total=len(unmatched_df), desc="HRDF Route Matching"):
        sloid = str(atlas_row['sloid'])
        atlas_uic_raw = atlas_row.get('number')
        
        if pd.isna(atlas_uic_raw): continue
        try:
            atlas_uic = str(int(float(atlas_uic_raw)))
        except (ValueError, TypeError):
            continue
            
        atlas_name_dirs = atlas_name_directions.get(sloid, set())
        atlas_uic_dirs = atlas_uic_directions.get(sloid, set())
        if not atlas_name_dirs and not atlas_uic_dirs:
            continue

        candidate_nodes = osm_by_uic.get(atlas_uic, [])
        for osm_node in candidate_nodes:
            osm_id = osm_node['node_id']
            if osm_id in used_osm_ids_hrdf: continue
            
            osm_name_dirs = osm_name_directions.get(osm_id, set())
            osm_uic_dirs = osm_uic_directions.get(osm_id, set())
            
            name_match = atlas_name_dirs.intersection(osm_name_dirs)
            uic_match = atlas_uic_dirs.intersection(osm_uic_dirs)
            
            if name_match or uic_match:
                match_subtype_parts = []
                if name_match: match_subtype_parts.append("name")
                if uic_match: match_subtype_parts.append("uic")
                
                # Combine main type and subtype into a single string
                match_type_str = f"route_hrdf_{'+'.join(match_subtype_parts)}"

                match = _create_match_dict(
                    atlas_row, osm_node,
                    haversine_distance(atlas_row['wgs84North'], atlas_row['wgs84East'], osm_node['lat'], osm_node['lon']),
                    match_type_str,
                    f"Shared UIC ({atlas_uic}) and direction string."
                )
                matches.append(match)
                used_osm_ids_hrdf.add(osm_id)
                break # Match found for this sloid, move to the next
    
    logger.info(f"HRDF matching found {len(matches)} new matches.")
    return matches, used_osm_ids_hrdf

def _perform_gtfs_matching(unmatched_df, xml_nodes, max_distance, used_osm_nodes):
    """Performs route matching using GTFS route/direction IDs."""
    logger.info("Performing GTFS-based route matching...")
    # This function would contain the entirety of the previous `route_matching` logic,
    # refactored to work on the provided `unmatched_df` and respect `used_osm_nodes`.
    # For brevity, we'll assume the original logic is now inside this function.
    # We will mock a simplified version of its output for now.
    
    # The full, original logic from `route_matching.py` would be here, but adapted.
    # This includes _load_and_prepare_route_data, _build_osm_indexes, etc.
    # To avoid repeating >800 lines, this is a placeholder for that logic.
    
    # --- Start of placeholder logic ---
    atlas_route_map, osm_route_map = _load_and_prepare_route_data()
    
    # Filter xml_nodes to exclude already used ones
    available_xml_nodes = {k: v for k, v in xml_nodes.items() if v['node_id'] not in used_osm_nodes}
    
    # Build indexes on available nodes
    osm_by_uic_route_dir, osm_by_route_dir, osm_by_uic_route_dir_normalized, osm_by_route_dir_normalized = _build_osm_indexes(available_xml_nodes, osm_route_map)
    atlas_by_uic_route_dir, atlas_stop_route_combinations, atlas_by_route_dir = _build_atlas_indexes(unmatched_df, atlas_route_map)
    
    unique_uic_route_dir_keys, _ = _identify_stage1_candidates(atlas_by_uic_route_dir, osm_by_uic_route_dir, atlas_stop_route_combinations)
    stage2_allowed_keys, stage2_normalized_allowed_keys = _identify_stage2_allowed_keys(atlas_by_route_dir, osm_by_route_dir, osm_by_route_dir_normalized)
    all_stage2_allowed_keys = stage2_allowed_keys | stage2_normalized_allowed_keys

    matches = []
    used_osm_ids_gtfs = set()
    
    def create_gtfs_match_dict_fn(csv_row, osm_lat, osm_lon, osm_node, distance, match_type, 
                              matching_notes, candidate_pool_size, route, direction, business_org_abbr):
        # A simplified version of the inner helper from the original function
        return _create_match_dict(csv_row, osm_node, distance, match_type, matching_notes,
                                  csv_route=route, csv_direction=direction, candidate_pool_size=candidate_pool_size)

    for _, csv_row in tqdm(unmatched_df.iterrows(), total=len(unmatched_df), desc="GTFS Route Matching"):
        sloid = str(csv_row['sloid'])
        uic_ref = str(csv_row.get('number', '')).strip() if pd.notna(csv_row.get('number')) else ""
        business_org_abbr = str(csv_row.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip()
        
        route_directions = atlas_route_map.get(sloid, [])
        if not route_directions: continue
        
        row_matched = False
        for rd in route_directions:
            if row_matched: break
            route, direction = rd['route'], rd['direction']
            
            # Stage 1
            match, matched = _perform_stage1_matching(
                csv_row, uic_ref, business_org_abbr, route, direction,
                unique_uic_route_dir_keys, osm_by_uic_route_dir, osm_by_uic_route_dir_normalized, create_gtfs_match_dict_fn,
                used_osm_ids_gtfs
            )
            if matched:
                matches.append(match)
                used_osm_ids_gtfs.add(match['osm_node_id'])
                row_matched = True
                continue

            # Stage 2
            match, matched = _perform_stage2_matching(
                csv_row, business_org_abbr, route, direction,
                osm_by_route_dir, osm_by_route_dir_normalized, max_distance, create_gtfs_match_dict_fn,
                all_stage2_allowed_keys, used_osm_ids_gtfs, used_osm_ids_gtfs
            )
            if matched:
                matches.append(match)
                used_osm_ids_gtfs.add(match['osm_node_id'])
                row_matched = True

    # --- End of placeholder logic ---
    logger.info(f"GTFS matching found {len(matches)} new matches.")
    return matches, used_osm_ids_gtfs


def route_matching(unmatched_df, xml_nodes, osm_xml_file, max_distance=50, strategy='gtfs_hrdf'):
    """
    Orchestrates route matching based on a selected strategy.
    
    Strategies:
      - 'gtfs': Use only GTFS-based matching.
      - 'hrdf': Use only HRDF-based matching.
      - 'gtfs_hrdf': Try GTFS first, then HRDF on the remainder.
      - 'hrdf_gtfs': Try HRDF first, then GTFS on the remainder.
    """
    logger.info(f"Starting route matching with strategy: {strategy}")
    
    all_matches = []
    used_osm_nodes = set()
    
    strategies = strategy.split('_')
    df_to_process = unmatched_df.copy()

    for i, current_strategy in enumerate(strategies):
        if df_to_process.empty:
            logger.info(f"No more unmatched entries to process for strategy '{current_strategy}'.")
            break
        
        logger.info(f"--- Running strategy part {i+1}: {current_strategy} ---")
        new_matches = []
        newly_used_osm_ids = set()

        if current_strategy == 'gtfs':
            new_matches, newly_used_osm_ids = _perform_gtfs_matching(df_to_process, xml_nodes, max_distance, used_osm_nodes)
        elif current_strategy == 'hrdf':
            new_matches, newly_used_osm_ids = _perform_hrdf_matching(df_to_process, xml_nodes, osm_xml_file, used_osm_nodes)
        else:
            logger.warning(f"Unknown strategy part '{current_strategy}' found in '{strategy}'. Skipping.")
            continue
            
        if new_matches:
            all_matches.extend(new_matches)
            used_osm_nodes.update(newly_used_osm_ids)
            
            # Update df_to_process for the next strategy part
            matched_sloids = {m['sloid'] for m in new_matches}
            df_to_process = df_to_process[~df_to_process['sloid'].isin(matched_sloids)]

    logger.info(f"Route matching complete. Total matches: {len(all_matches)}")
    return all_matches

def _build_osm_indexes(xml_nodes, osm_route_map):
    """Builds OSM node indexes for route matching."""
    osm_by_uic_route_dir = defaultdict(list)
    osm_by_route_dir = defaultdict(list)
    # Add normalized indexes for fallback matching
    osm_by_uic_route_dir_normalized = defaultdict(list)
    osm_by_route_dir_normalized = defaultdict(list)
    logger.info("Building OSM node indexes for route matching...")

    for (xml_lat, xml_lon), xml_node in xml_nodes.items():
        node_id = str(xml_node['node_id']) # Ensure xml_node['node_id'] is a string
        uic_ref = xml_node['tags'].get('uic_ref', '')
        
        route_directions = [] 
        if node_id in osm_route_map: 
            route_directions = osm_route_map[node_id]
        
        for rd in route_directions:
            route = rd['route']
            direction = rd['direction']
            route_normalized = _normalize_route_id_for_matching(route)
            
            candidate_info = {
                'lat': xml_lat,
                'lon': xml_lon,
                'node': xml_node
            }
            
            if uic_ref:
                osm_by_uic_route_dir[(uic_ref, route, direction)].append(candidate_info)
                if route_normalized:
                    osm_by_uic_route_dir_normalized[(uic_ref, route_normalized, direction)].append(candidate_info)
            
            osm_by_route_dir[(route, direction)].append(candidate_info)
            if route_normalized:
                osm_by_route_dir_normalized[(route_normalized, direction)].append(candidate_info)
                
    return osm_by_uic_route_dir, osm_by_route_dir, osm_by_uic_route_dir_normalized, osm_by_route_dir_normalized

def _normalize_route_id_for_matching(route_id):
    """Remove year codes (j24, j25, etc.) from route IDs for fuzzy matching."""
    if not route_id:
        return None
    import re
    # Replace j24, j25, j22, etc. with a generic jXX for comparison
    normalized = re.sub(r'-j\d+', '-jXX', str(route_id))
    return normalized

def _load_and_prepare_route_data():
    """Loads and prepares route data from CSV files."""
    atlas_route_map = defaultdict(list)
    osm_route_map = defaultdict(list)
    files_loaded_successfully = True
    logger.info("Loading route information from CSV files...")
    try:
        # Load ATLAS routes data
        atlas_routes_csv_path = "data/processed/atlas_routes.csv"
        atlas_routes = pd.read_csv(atlas_routes_csv_path)
        required_atlas_cols = ['sloid', 'route_id', 'direction_id']
        for col in required_atlas_cols:
            if col not in atlas_routes.columns:
                logger.error(f"Missing required column '{col}' in {atlas_routes_csv_path}.")
                files_loaded_successfully = False
                break
        if not files_loaded_successfully: # If a required col was missing
            return defaultdict(list), defaultdict(list) # Return empty maps
                
        # Create a mapping from sloid to route/direction
        for _, row in atlas_routes.iterrows():
            if pd.notna(row['sloid']) and pd.notna(row['route_id']) and pd.notna(row['direction_id']):
                norm_dir = _normalize_direction(row['direction_id'])
                if norm_dir is None:
                    continue  # Skip rows with invalid direction
                atlas_route_map[str(row['sloid'])].append({
                    'route': str(row['route_id']).strip(),
                    'direction': norm_dir
                })
        logger.info(f"Loaded {len(atlas_routes)} ATLAS route entries for {len(atlas_route_map)} stops from {atlas_routes_csv_path}")
        
        # Load OSM nodes with routes
        osm_routes_csv_path = "data/processed/osm_nodes_with_routes.csv"
        osm_routes = pd.read_csv(osm_routes_csv_path)
        required_osm_cols = ['node_id', 'direction_id', 'gtfs_route_id']
        for col in required_osm_cols:
            if col not in osm_routes.columns:
                logger.error(f"Missing required column '{col}' in {osm_routes_csv_path}.")
                files_loaded_successfully = False
                break
        if not files_loaded_successfully: # If a required col was missing
             # Reset atlas_route_map too, to ensure consistent state on partial failure
            return defaultdict(list), defaultdict(list)
        
        # --- Build fallback mapping from GTFS route short/long names to route_id ---
        gtfs_routes_path = None
        gtfs_root = "data/raw"
        if os.path.isdir(gtfs_root):
            for fname in os.listdir(gtfs_root):
                if fname.startswith("gtfs_") and os.path.isdir(os.path.join(gtfs_root, fname)):
                    candidate = os.path.join(gtfs_root, fname, "routes.txt")
                    if os.path.exists(candidate):
                        gtfs_routes_path = candidate
                        break

        route_name_to_id = {}
        if gtfs_routes_path:
            try:
                gtfs_routes_df = pd.read_csv(gtfs_routes_path, dtype=str, usecols=['route_id', 'route_short_name', 'route_long_name'])
                for _, r in gtfs_routes_df.iterrows():
                    if pd.notna(r.get('route_short_name')):
                        route_name_to_id[str(r['route_short_name']).strip()] = str(r['route_id']).strip()
                    if pd.notna(r.get('route_long_name')):
                        route_name_to_id[str(r['route_long_name']).strip()] = str(r['route_id']).strip()
            except Exception as e:
                logger.warning(f"Failed to build GTFS route name mapping: {e}")

        for _, row in osm_routes.iterrows():
            # Skip row only if node_id is missing; direction can be NaN (handled below)
            if pd.isna(row['node_id']):
                continue

            node_id_str = str(row['node_id']).strip()
            direction_str = _normalize_direction(row['direction_id'])

            # If direction missing, create entries for both directions 0 and 1
            directions_to_add = []
            if direction_str is None:
                directions_to_add = ['0', '1']
            else:
                directions_to_add = [direction_str]

            route_id_val = None
            # Prefer explicit gtfs_route_id if present and non-empty
            if pd.notna(row.get('gtfs_route_id')) and str(row['gtfs_route_id']).strip() != '':
                route_id_val = str(row['gtfs_route_id']).strip()
            else:
                # Try mapping via route_name
                rname = str(row.get('route_name') or '').strip()
                if rname in route_name_to_id:
                    route_id_val = route_name_to_id[rname]
            if not route_id_val:
                continue  # Cannot determine route_id, skip

            for dir_val in directions_to_add:
                osm_route_map[node_id_str].append({
                    'route': route_id_val,
                    'direction': dir_val
                })
            
        logger.info(f"Loaded {len(osm_routes)} OSM route entries for {len(osm_route_map)} nodes from {osm_routes_csv_path}")
    
    except FileNotFoundError as e:
        logger.error(f"Error loading route data: {e}. One of the route CSV files was not found.")
        logger.warning("Proceeding with route matching without additional route data as files were not found.")
        return defaultdict(list), defaultdict(list) # Ensure consistent return on error
    except pd.errors.EmptyDataError as e:
        logger.error(f"Error loading route data: {e}. One of the route CSV files is empty.")
        logger.warning("Proceeding with route matching without additional route data as files were empty.")
        return defaultdict(list), defaultdict(list) # Ensure consistent return on error
    except Exception as e: # Catch other potential pandas or general errors
        logger.error(f"An unexpected error occurred while loading route data: {e}")
        logger.warning("Proceeding with route matching without additional route data due to an unexpected error.")
        return defaultdict(list), defaultdict(list) # Ensure consistent return on error
    
    if not files_loaded_successfully:
        # This case should ideally be caught by checks within the try block
        logger.warning("Proceeding with route matching without additional route data due to missing columns in CSV files.")
        return defaultdict(list), defaultdict(list)

    return atlas_route_map, osm_route_map

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the Haversine distance (in meters) between two points.
    """
    try:
        R = 6371000.0  # Earth radius in meters
        # Attempt to convert inputs to float first
        lat1_f, lon1_f, lat2_f, lon2_f = float(lat1), float(lon1), float(lat2), float(lon2)
        # Then map to radians
        rad_lat1, rad_lon1, rad_lat2, rad_lon2 = map(radians, [lat1_f, lon1_f, lat2_f, lon2_f])
        
        dlat = rad_lat2 - rad_lat1
        dlon = rad_lon2 - rad_lon1
        a = sin(dlat/2)**2 + cos(rad_lat1)*cos(rad_lat2)*sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c
    except (ValueError, TypeError) as e:
        logger.error(f"Error in haversine_distance with inputs ({lat1}, {lon1}, {lat2}, {lon2}): {e}")
        return None
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"Unexpected error in haversine_distance with inputs ({lat1}, {lon1}, {lat2}, {lon2}): {e}")
        return None

def _identify_stage1_candidates(atlas_by_uic_route_dir, osm_by_uic_route_dir, atlas_stop_route_combinations):
    """Identifies unique candidates for Stage 1 matching."""
    logger.info("Filtering unique (UIC, route, direction) tuples for Stage 1...")
    unique_uic_route_dir_keys = set()
    
    for key in atlas_by_uic_route_dir.keys():
        if key in osm_by_uic_route_dir:
            osm_count = len(osm_by_uic_route_dir[key])
            atlas_entries = atlas_by_uic_route_dir[key]
            atlas_unique_stops = len(atlas_stop_route_combinations[key])
            
            if osm_count == 1 and atlas_unique_stops == 1:
                unique_uic_route_dir_keys.add(key)
            else:
                if osm_count != 1:
                    logger.debug(f"Key {key} rejected for Stage 1: {osm_count} OSM nodes (expected 1)")
                if atlas_unique_stops != 1:
                    logger.debug(f"Key {key} rejected for Stage 1: {atlas_unique_stops} unique ATLAS stops (expected 1, found {len(atlas_entries)} total entries)")

    logger.info(f"Found {len(unique_uic_route_dir_keys)} unique (UIC, route, direction) tuples for Stage 1 matching")
    
    # Calculate rejection statistics
    rejected_osm_multiple = sum(1 for k in atlas_by_uic_route_dir 
                               if k in osm_by_uic_route_dir and len(osm_by_uic_route_dir[k]) > 1 and not (len(osm_by_uic_route_dir[k]) == 1 and len(atlas_stop_route_combinations[k]) == 1) )
    rejected_atlas_multiple = sum(1 for k in atlas_by_uic_route_dir 
                                 if k in osm_by_uic_route_dir and len(atlas_stop_route_combinations[k]) > 1 and not (len(osm_by_uic_route_dir[k]) == 1 and len(atlas_stop_route_combinations[k]) == 1) )
    missing_in_osm = len(atlas_by_uic_route_dir) - len([k for k in atlas_by_uic_route_dir if k in osm_by_uic_route_dir])

    rejection_stats = {
        "rejected_osm_multiple": rejected_osm_multiple,
        "rejected_atlas_multiple": rejected_atlas_multiple,
        "missing_in_osm": missing_in_osm
    }
            
    return unique_uic_route_dir_keys, rejection_stats

def _perform_stage1_matching(csv_row, uic_ref, business_org_abbr, 
                             route, direction,
                             unique_uic_route_dir_keys, 
                             osm_by_uic_route_dir, osm_by_uic_route_dir_normalized, create_match_dict_fn,
                             used_osm_nodes_stage1):
    """Performs Stage 1 matching for a single CSV row and a single route."""
    csv_lat = float(csv_row['wgs84North'])
    csv_lon = float(csv_row['wgs84East'])
    key = (uic_ref, route, direction)

    # Try exact match first
    if key in unique_uic_route_dir_keys and key in osm_by_uic_route_dir:
        candidates = osm_by_uic_route_dir[key]
        
        if len(candidates) == 1:
            candidate = candidates[0]
            osm_node_id = candidate['node']['node_id']
            
            # Check if this OSM node has already been used in Stage 1
            if osm_node_id in used_osm_nodes_stage1:
                logger.debug(f"Stage 1 exact: OSM node {osm_node_id} already used, skipping")
                return None, False  # OSM node already used, skip
            
            distance = haversine_distance(csv_lat, csv_lon, candidate['lat'], candidate['lon'])
            
            if distance is not None:
                match_dict = create_match_dict_fn(
                    csv_row, candidate['lat'], candidate['lon'], candidate['node'], distance,
                    'route_matching_1_exact', "Unique UIC reference, route, and direction match (1:1)",
                    1, route, direction, business_org_abbr
                )
                return match_dict, True # match_found = True
    
    # Try normalized match as fallback
    route_normalized = _normalize_route_id_for_matching(route)
    if route_normalized:
        key_normalized = (uic_ref, route_normalized, direction)
        if key_normalized in osm_by_uic_route_dir_normalized:
            candidates = osm_by_uic_route_dir_normalized[key_normalized]
            
            if len(candidates) == 1:
                candidate = candidates[0]
                osm_node_id = candidate['node']['node_id']
                
                # Check if this OSM node has already been used in Stage 1
                if osm_node_id in used_osm_nodes_stage1:
                    logger.debug(f"Stage 1 normalized: OSM node {osm_node_id} already used, skipping")
                    return None, False  # OSM node already used, skip
                
                distance = haversine_distance(csv_lat, csv_lon, candidate['lat'], candidate['lon'])
                
                if distance is not None:
                    match_dict = create_match_dict_fn(
                        csv_row, candidate['lat'], candidate['lon'], candidate['node'], distance,
                        'route_matching_1_normalized', "Unique UIC reference, route, and direction match (1:1, normalized)",
                        1, route, direction, business_org_abbr
                    )
                    return match_dict, True # match_found = True
    
    return None, False # match_found = False

def _perform_stage2_matching(csv_row, business_org_abbr, 
                             route, direction,
                             osm_by_route_dir, osm_by_route_dir_normalized, max_distance, create_match_dict_fn,
                             stage2_allowed_keys, used_osm_nodes_stage1, used_osm_nodes_stage2):
    """Performs Stage 2 matching for a single CSV row and a single route."""
    csv_lat = float(csv_row['wgs84North'])
    csv_lon = float(csv_row['wgs84East'])

    # Try exact match first
    key = (route, direction)
    if key in osm_by_route_dir and key in stage2_allowed_keys:
        candidates = []
        for candidate_info in osm_by_route_dir[key]:
            osm_node_id = candidate_info['node']['node_id']
            
            # Skip if OSM node already used in Stage 1 or Stage 2
            if osm_node_id in used_osm_nodes_stage1 or osm_node_id in used_osm_nodes_stage2:
                continue
            
            distance = haversine_distance(csv_lat, csv_lon, candidate_info['lat'], candidate_info['lon'])
            if distance is not None and distance <= max_distance:
                candidates.append({
                    'lat': candidate_info['lat'],
                    'lon': candidate_info['lon'],
                    'node': candidate_info['node'],
                    'distance': distance
                })
        
        if candidates:
            candidates.sort(key=lambda x: x['distance'])
            best_match = candidates[0]
            
            match_dict = create_match_dict_fn(
                csv_row, best_match['lat'], best_match['lon'], best_match['node'], best_match['distance'],
                'route_matching_2_exact', f"Same route and direction match within {max_distance}m",
                len(candidates), route, direction, business_org_abbr
            )
            return match_dict, True # match_found = True
    
    # Try normalized match as fallback
    route_normalized = _normalize_route_id_for_matching(route)
    if route_normalized:
        key_normalized = (route_normalized, direction)
        if key_normalized in osm_by_route_dir_normalized and key_normalized in stage2_allowed_keys:
            candidates = []
            for candidate_info in osm_by_route_dir_normalized[key_normalized]:
                osm_node_id = candidate_info['node']['node_id']
                
                # Skip if OSM node already used in Stage 1 or Stage 2
                if osm_node_id in used_osm_nodes_stage1 or osm_node_id in used_osm_nodes_stage2:
                    continue
                
                distance = haversine_distance(csv_lat, csv_lon, candidate_info['lat'], candidate_info['lon'])
                if distance is not None and distance <= max_distance:
                    candidates.append({
                        'lat': candidate_info['lat'],
                        'lon': candidate_info['lon'],
                        'node': candidate_info['node'],
                        'distance': distance
                    })
            
            if candidates:
                candidates.sort(key=lambda x: x['distance'])
                best_match = candidates[0]
                
                match_dict = create_match_dict_fn(
                    csv_row, best_match['lat'], best_match['lon'], best_match['node'], best_match['distance'],
                    'route_matching_2_normalized', f"Same route and direction match within {max_distance}m (normalized)",
                    len(candidates), route, direction, business_org_abbr
                )
                return match_dict, True # match_found = True
    
    return None, False # match_found = False

def _build_atlas_indexes(unmatched_df, atlas_route_map):
    """Builds ATLAS entry indexes for route matching."""
    atlas_by_uic_route_dir = defaultdict(list)
    atlas_stop_route_combinations = defaultdict(set)
    atlas_by_route_dir = defaultdict(list)
    logger.info("Building ATLAS entry indexes for route matching...")

    for idx, csv_row in unmatched_df.iterrows():
        sloid = str(csv_row['sloid'])
        uic_ref = str(csv_row.get('number', '')).strip() if pd.notna(csv_row.get('number')) else ""
        
        route_directions = []
        # Ensure atlas_route_map is accessible; it should be passed if not in scope
        # For now, assuming it might be available through closure or needs to be passed.
        # Corrected: atlas_route_map is passed as an argument.
        if sloid in atlas_route_map:
            route_directions = atlas_route_map[sloid]
        
        for rd in route_directions:
            route = rd['route'] # route is already string from _load_and_prepare_route_data
            direction = rd['direction'] # direction is already string from _load_and_prepare_route_data
            
            # Build Stage 2 index (route, direction) -> ATLAS stops
            atlas_by_route_dir[(route, direction)].append({
                'row': csv_row,
                'sloid': sloid,
                'route': route,
                'direction': direction
            })
            
            if uic_ref:
                key = (uic_ref, route, direction)
                atlas_by_uic_route_dir[key].append({
                    'row': csv_row,
                    'sloid': sloid,
                    'route': route,
                    'direction': direction
                })
                atlas_stop_route_combinations[key].add(sloid)
    return atlas_by_uic_route_dir, atlas_stop_route_combinations, atlas_by_route_dir

def _identify_stage2_allowed_keys(atlas_by_route_dir, osm_by_route_dir, osm_by_route_dir_normalized):
    """
    Identifies which (route, direction) keys are allowed for Stage 2 matching.
    Only allows keys that don't create many-to-many matches:
    - 1 ATLAS : 1 OSM → allowed (1:1)
    - 1 ATLAS : multiple OSM → allowed (1:many, pick closest)
    - multiple ATLAS : 1 OSM → allowed (many:1, pick closest)
    - multiple ATLAS : multiple OSM → NOT allowed (many:many)
    """
    allowed_keys = set()
    
    # Check exact matches
    for key in atlas_by_route_dir.keys():
        if key in osm_by_route_dir:
            atlas_count = len(set(item['sloid'] for item in atlas_by_route_dir[key]))  # Count unique sloids
            osm_count = len(osm_by_route_dir[key])
            
            # Allow if not many-to-many
            if not (atlas_count > 1 and osm_count > 1):
                allowed_keys.add(key)
                logger.debug(f"Stage 2 key {key} allowed: {atlas_count} ATLAS stops, {osm_count} OSM nodes")
            else:
                logger.debug(f"Stage 2 key {key} rejected: many-to-many ({atlas_count} ATLAS stops, {osm_count} OSM nodes)")
    
    # Check normalized matches
    normalized_allowed_keys = set()
    for key in atlas_by_route_dir.keys():
        route, direction = key
        route_normalized = _normalize_route_id_for_matching(route)
        if route_normalized:
            key_normalized = (route_normalized, direction)
            if key_normalized in osm_by_route_dir_normalized:
                atlas_count = len(set(item['sloid'] for item in atlas_by_route_dir[key]))  # Count unique sloids
                osm_count = len(osm_by_route_dir_normalized[key_normalized])
                
                # Allow if not many-to-many
                if not (atlas_count > 1 and osm_count > 1):
                    normalized_allowed_keys.add(key_normalized)
                    logger.debug(f"Stage 2 normalized key {key_normalized} allowed: {atlas_count} ATLAS stops, {osm_count} OSM nodes")
                else:
                    logger.debug(f"Stage 2 normalized key {key_normalized} rejected: many-to-many ({atlas_count} ATLAS stops, {osm_count} OSM nodes)")
    
    logger.info(f"Stage 2 allowed keys: {len(allowed_keys)} exact, {len(normalized_allowed_keys)} normalized")
    return allowed_keys, normalized_allowed_keys

# The original `route_matching` is now replaced by the orchestrator above.
# The original helper functions from the old file are assumed to be present below this line.
# For example: parse_osm_xml (though a simplified version is used by the new helpers now),
# _normalize_direction, haversine_distance, etc.

def _normalize_direction(direction_val):
    """Return direction as integer string ("0", "1") or None if invalid."""
    try:
        if pd.isna(direction_val):
            return None
        # Convert via float first to handle "0.0" & Int8/Numpy types, then to int
        return str(int(float(direction_val)))
    except Exception:
        return None

"""
def main():
    atlas_csv_file = "stops_ATLAS.csv"
    osm_xml_file = "osm_data.xml"
    
    atlas_df = pd.read_csv(atlas_csv_file, sep=";")
    all_osm_nodes, uic_ref_dict, name_index = parse_osm_xml(osm_xml_file)
    route_matches = route_matching(atlas_df, all_osm_nodes, max_distance=50)
    
    # Save route matches to CSV
    if route_matches:
        matches_df = pd.DataFrame(route_matches)
        matches_df.to_csv("route_matches.csv", index=False)
        logger.info(f"Saved {len(route_matches)} route matches to route_matches.csv")
    else:
        logger.warning("No route matches found to save")

# Add this at the end of the file (outside any function)
if __name__ == "__main__":
    main()
"""