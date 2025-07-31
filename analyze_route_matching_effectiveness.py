import pandas as pd
import logging
from collections import defaultdict
from tqdm import tqdm
import sys
import os
import xml.etree.ElementTree as ET

# Assuming the project structure allows this import path
from matching_process.route_matching import route_matching, parse_osm_xml, haversine_distance, _normalize_direction
from get_atlas_data import extract_gtfs_directions

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_osm_directions_from_xml(xml_file):
    """
    Parses the raw OSM XML to create a map of OSM node IDs to their route direction strings.
    Returns two maps: one for name-based directions and one for UIC-based directions.
    """
    logger.info("Parsing OSM XML for route direction strings (name and UIC)...")
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"Failed to parse {xml_file}: {e}")
        return defaultdict(set), defaultdict(set)

    # 1. Create maps of all node IDs to their names and UICs for quick lookup
    node_id_to_name = {}
    node_id_to_uic = {}
    for node in root.findall(".//node"):
        node_id = node.get('id')
        for tag in node.findall("./tag"):
            if tag.get('k') == 'name':
                node_id_to_name[node_id] = tag.get('v')
            elif tag.get('k') == 'uic_ref':
                node_id_to_uic[node_id] = tag.get('v')

    # 2. Create the maps from node ID to a set of direction strings
    osm_name_directions_map = defaultdict(set)
    osm_uic_directions_map = defaultdict(set)
    for relation in root.findall(".//relation"):
        is_route = any(tag.get('k') == 'type' and tag.get('v') == 'route' for tag in relation.findall("./tag"))
        if not is_route:
            continue

        # Find all node members of this route relation
        member_nodes = [member.get('ref') for member in relation.findall("./member[@type='node']")]
        
        if len(member_nodes) >= 2:
            first_node_id = member_nodes[0]
            last_node_id = member_nodes[-1]
            
            # Create name-based direction string
            first_stop_name = node_id_to_name.get(first_node_id)
            last_stop_name = node_id_to_name.get(last_node_id)
            if first_stop_name and last_stop_name:
                direction_string = f"{first_stop_name} → {last_stop_name}"
                for node_id in member_nodes:
                    osm_name_directions_map[node_id].add(direction_string)

            # Create UIC-based direction string
            first_stop_uic = node_id_to_uic.get(first_node_id)
            last_stop_uic = node_id_to_uic.get(last_node_id)
            if first_stop_uic and last_stop_uic:
                direction_string = f"{first_stop_uic} → {last_stop_uic}"
                for node_id in member_nodes:
                    osm_uic_directions_map[node_id].add(direction_string)
    
    logger.info(f"Derived name directions for {len(osm_name_directions_map)} and UIC directions for {len(osm_uic_directions_map)} OSM nodes from XML.")
    return osm_name_directions_map, osm_uic_directions_map

def hrdf_route_matching(atlas_df, xml_nodes, osm_xml_file):
    """
    Performs route matching using two conditions:
    1. Same UIC reference ('number' in ATLAS, 'uic_ref' tag in OSM).
    2. At least one shared direction string (either by name or by UIC).
    """
    logger.info("Starting HRDF-based route matching with UIC and direction string (name or UIC)...")

    # 1. Load HRDF directions for ATLAS stops
    try:
        hrdf_routes = pd.read_csv("data/processed/atlas_routes_hrdf.csv")
        atlas_name_directions = defaultdict(set)
        atlas_uic_directions = defaultdict(set)
        for _, row in hrdf_routes.iterrows():
            sloid_str = str(row['sloid'])
            if pd.notna(row['direction_name']):
                atlas_name_directions[sloid_str].add(row['direction_name'])
            if pd.notna(row['direction_uic']):
                atlas_uic_directions[sloid_str].add(row['direction_uic'])
        logger.info(f"Loaded HRDF name/UIC directions for {len(atlas_name_directions)} ATLAS sloids.")
    except FileNotFoundError:
        logger.error("Could not find 'data/processed/atlas_routes_hrdf.csv'. Please run get_atlas_data.py.")
        return []

    # 2. Prepare direction strings for OSM nodes directly from raw OSM XML
    osm_name_directions, osm_uic_directions = get_osm_directions_from_xml(osm_xml_file)

    # 3. Build an index of OSM nodes by their UIC reference for efficient lookup.
    osm_by_uic = defaultdict(list)
    for node in xml_nodes.values():
        uic_ref = node.get('tags', {}).get('uic_ref')
        if uic_ref:
            osm_by_uic[uic_ref.strip()].append(node)
    logger.info(f"Built OSM index for {len(osm_by_uic)} unique UIC references.")

    # 4. Perform the matching
    matches = []
    
    for _, atlas_row in tqdm(atlas_df.iterrows(), total=len(atlas_df), desc="HRDF Route Matching"):
        sloid = str(atlas_row['sloid'])
        atlas_uic_raw = atlas_row.get('number')
        
        # Normalize ATLAS UIC to a clean integer string
        if pd.isna(atlas_uic_raw):
            continue
        try:
            atlas_uic = str(int(float(atlas_uic_raw)))
        except (ValueError, TypeError):
            continue
            
        # Get the two sets of directions for this sloid
        atlas_name_dirs = atlas_name_directions.get(sloid, set())
        atlas_uic_dirs = atlas_uic_directions.get(sloid, set())

        if not atlas_name_dirs and not atlas_uic_dirs:
            continue

        # Condition 1: Find candidate OSM nodes with the same UIC
        candidate_nodes = osm_by_uic.get(atlas_uic, [])
        
        for osm_node in candidate_nodes:
            osm_id = osm_node['node_id']
            
            # Get OSM directions for this node
            osm_name_dirs = osm_name_directions.get(osm_id, set())
            osm_uic_dirs = osm_uic_directions.get(osm_id, set())

            # Condition 2: Check for a match on either name or UIC directions
            name_match = atlas_name_dirs.intersection(osm_name_dirs)
            uic_match = atlas_uic_dirs.intersection(osm_uic_dirs)
            
            if name_match or uic_match:
                # It's a match. Determine match type for notes.
                match_reason = []
                if name_match:
                    match_reason.append("name")
                if uic_match:
                    match_reason.append("uic")

                matches.append({
                    'sloid': sloid,
                    'number': atlas_row.get('number'),
                    'csv_lat': atlas_row['wgs84North'],
                    'csv_lon': atlas_row['wgs84East'],
                    'osm_node_id': osm_id,
                    'osm_lat': osm_node['lat'],
                    'osm_lon': osm_node['lon'],
                    'distance_m': haversine_distance(atlas_row['wgs84North'], atlas_row['wgs84East'], osm_node['lat'], osm_node['lon']), # Keep for info
                    'match_type': 'hrdf_uic_direction_match',
                    'match_subtype': "+".join(match_reason), # 'name', 'uic', or 'name+uic'
                    'matching_notes': f"Shared UIC ({atlas_uic}) and direction string."
                })

    logger.info(f"HRDF-based route matching complete: {len(matches)} matches found.")
    return matches


def main():
    """Main function to run the comparison."""
    # --- Load Data ---
    atlas_csv_file = "data/raw/stops_ATLAS.csv"
    osm_xml_file = "data/raw/osm_data.xml"

    if not all(os.path.exists(f) for f in [atlas_csv_file, osm_xml_file]):
        logger.error("Missing raw data files. Please run get_atlas_data.py and get_osm_data.py first.")
        return

    logger.info("Loading and parsing data files for comparison...")
    atlas_df = pd.read_csv(atlas_csv_file, sep=";")
    all_osm_nodes, _, _ = parse_osm_xml(osm_xml_file)

    # --- GTFS Route Matching ---
    logger.info("\n===== Running GTFS-based Route Matching =====")
    gtfs_matches = route_matching(atlas_df, all_osm_nodes, max_distance=50)
    gtfs_matched_sloids = {m['sloid'] for m in gtfs_matches}
    gtfs_matched_osm = {m['osm_node_id'] for m in gtfs_matches}

    # --- HRDF Route Matching ---
    logger.info("\n===== Running HRDF-based Route Matching =====")
    hrdf_matches = hrdf_route_matching(atlas_df, all_osm_nodes, osm_xml_file)
    hrdf_matched_sloids = {m['sloid'] for m in hrdf_matches}
    hrdf_matched_osm = {m['osm_node_id'] for m in hrdf_matches}

    # Count HRDF match subtypes
    hrdf_name_matches = sum(1 for m in hrdf_matches if 'name' in m.get('match_subtype', ''))
    hrdf_uic_matches = sum(1 for m in hrdf_matches if 'uic' in m.get('match_subtype', ''))
    hrdf_both_matches = sum(1 for m in hrdf_matches if m.get('match_subtype') == 'name+uic')

    # --- Comparison ---
    logger.info("\n===== Comparison of Route Matching Effectiveness =====")
    
    print("\n--- Match Counts ---")
    print(f"GTFS Matching Found: {len(gtfs_matches)} matches")
    print(f"HRDF Matching Found: {len(hrdf_matches)} matches")

    print("\n--- Unique ATLAS Stops (sloid) Matched ---")
    print(f"GTFS Matched: {len(gtfs_matched_sloids)} unique sloids")
    print(f"HRDF Matched: {len(hrdf_matched_sloids)} unique sloids")
    print(f"  ├─ Based on Name Direction: {hrdf_name_matches}")
    print(f"  ├─ Based on UIC Direction: {hrdf_uic_matches}")
    print(f"  └─ Matched by Both: {hrdf_both_matches}")

    print("\n--- Unique OSM Nodes Matched ---")
    print(f"GTFS Matched: {len(gtfs_matched_osm)} unique OSM nodes")
    print(f"HRDF Matched: {len(hrdf_matched_osm)} unique OSM nodes")

    # --- Overlap Analysis ---
    sloid_overlap = gtfs_matched_sloids.intersection(hrdf_matched_sloids)
    sloid_gtfs_only = gtfs_matched_sloids - hrdf_matched_sloids
    sloid_hrdf_only = hrdf_matched_sloids - gtfs_matched_sloids

    # --- Match Cardinality Analysis ---
    def analyze_cardinality(matches, method_name):
        sloid_to_osm = defaultdict(set)
        osm_to_sloid = defaultdict(set)
        for m in matches:
            sloid_to_osm[m['sloid']].add(m['osm_node_id'])
            osm_to_sloid[m['osm_node_id']].add(m['sloid'])

        one_to_one = sum(1 for sloid, osms in sloid_to_osm.items() if len(osms) == 1 and len(osm_to_sloid[list(osms)[0]]) == 1)
        one_to_many = sum(1 for sloid, osms in sloid_to_osm.items() if len(osms) > 1)
        many_to_one = sum(1 for osm, sloids in osm_to_sloid.items() if len(sloids) > 1)
        
        print(f"\n--- Match Cardinality ({method_name}) ---")
        print(f"One-to-One (Sloid ↔ OSM): {one_to_one}")
        print(f"One-to-Many (1 Sloid → N OSMs): {one_to_many}")
        print(f"Many-to-One (N Sloids → 1 OSM): {many_to_one}")

    analyze_cardinality(gtfs_matches, "GTFS")
    analyze_cardinality(hrdf_matches, "HRDF")

    print("\n--- Overlap Analysis (based on ATLAS sloids) ---")
    print(f"Matched by BOTH GTFS and HRDF: {len(sloid_overlap)}")
    print(f"Matched by GTFS ONLY: {len(sloid_gtfs_only)}")
    print(f"Matched by HRDF ONLY: {len(sloid_hrdf_only)}")

    print("\n--- Conclusion ---")
    if len(gtfs_matched_sloids) > len(hrdf_matched_sloids):
        print("GTFS appears to be more effective for route matching.")
        diff = len(gtfs_matched_sloids) - len(hrdf_matched_sloids)
        print(f"It matched {diff} more unique ATLAS sloids than HRDF.")
    elif len(hrdf_matched_sloids) > len(gtfs_matched_sloids):
        print("HRDF appears to be more effective for route matching.")
        diff = len(hrdf_matched_sloids) - len(gtfs_matched_sloids)
        print(f"It matched {diff} more unique ATLAS sloids than GTFS.")
    else:
        print("GTFS and HRDF appear to be similarly effective for route matching.")
        print(f"They both matched {len(gtfs_matched_sloids)} unique ATLAS sloids.")

    print("\nDetailed breakdown of matches exclusive to each method can indicate their respective strengths.")
    print("==========================================================")

if __name__ == "__main__":
    main() 