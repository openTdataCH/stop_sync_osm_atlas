# 1: Utility Functions and Data Loading
import pandas as pd
import xml.etree.ElementTree as ET
from collections import defaultdict
import logging
from matching_process.utils import is_osm_station
# Import functions from distance_matching.py
from matching_process.distance_matching import distance_matching, transform_for_distance_matching
# Import route_matching function
from matching_process.route_matching import route_matching
# Import standardize_operator from org_standaarization.py
from matching_process.org_standaarization import standardize_operator
# Import centralized isolation detection
from matching_process.problem_detection import detect_osm_isolation
# Import split-out matching stages
from matching_process.exact_matching import exact_matching
from matching_process.name_matching import name_based_matching

# Setup logging for detailed match candidate logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
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
# 3: Distance Matching


# 4: Final Pipeline

# Use module-level logger defined by basicConfig at import


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
            if match.get('match_type') == 'no_nearby_counterpart':
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
    # This df still contains the entries that will be marked as 'no_nearby_counterpart'
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

    # --- Detect isolated OSM nodes using centralized logic ---
    logger.info("Checking for isolated unmatched OSM nodes...")
    osm_isolation_status = {}
    if unmatched_osm_nodes:
        # Prepare ATLAS stop data for isolation detection
        atlas_stops_data = []
        for _, row in atlas_df.iterrows():
            atlas_stops_data.append({
                'lat': row['wgs84North'],
                'lon': row['wgs84East'],
                'sloid': row['sloid']
            })
        
        # Use centralized isolation detection
        osm_isolation_status = detect_osm_isolation(unmatched_osm_nodes, atlas_stops_data)
        isolated_count = sum(osm_isolation_status.values())
        logger.info(f"Found {isolated_count} isolated unmatched OSM nodes.")

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
    # The definition of final_unmatched_atlas naturally includes those identified as 'no_nearby_counterpart'
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
    # no_nearby_osm_entries = [match for match in all_matches if match.get('match_type') == 'no_nearby_counterpart'] # This line is removed as it's calculated earlier
    print(f"ATLAS entries with no OSM nodes within 50 meters: {len(no_nearby_osm_entries)}") # Use the count from separation
    
    # --- Prepare Data for Database Import ---
    # Add isolation status to unmatched OSM nodes for database import
    unmatched_osm_with_isolation = []
    for node in unmatched_osm_nodes:
        node_with_status = node.copy()  # Don't mutate the original
        node_id = node.get('node_id')
        node_with_status['is_isolated'] = osm_isolation_status.get(node_id, False)
        unmatched_osm_with_isolation.append(node_with_status)
    
    base_data = {
        "matched": all_matches_df.to_dict(orient="records"),
        "unmatched_atlas": final_unmatched_atlas, # Use the correctly calculated list
        "unmatched_osm": unmatched_osm_with_isolation
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

    print(f"Total matched (all methods): {len(all_matches_df)}") # all_matches now excludes 'no_nearby_counterpart'
    print(f"Unmatched ATLAS entries: {len(final_unmatched_atlas)}")
    # Report 'no_nearby_counterpart' as a subset of unmatched
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

