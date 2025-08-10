import pandas as pd
import logging
from collections import defaultdict
from tqdm import tqdm
import sys
from math import radians, sin, cos
from scipy.spatial import KDTree
import numpy as np
import traceback

# Local isolation radius (formerly from detection_config)
def get_isolation_radius() -> int:
    return 50
from .utils import haversine_distance

# Setup logging
logger = logging.getLogger(__name__)

def transform_for_distance_matching(all_osm_nodes, filtered=False, used_node_ids=None):
    """
    Transform the comprehensive OSM nodes dictionary into the format needed for distance matching.
    
    Parameters:
        all_osm_nodes (dict): Dictionary of OSM nodes keyed by (lat, lon)
        filtered (bool): Whether to filter out already used nodes
        used_node_ids (set): Set of node IDs that have already been matched
        
    Returns:
        dict: Dictionary keyed by (lat, lon) with node data for distance matching
    """
    if filtered and used_node_ids:
        return {coord: info for coord, info in all_osm_nodes.items() 
                if info['node_id'] not in used_node_ids}
    return all_osm_nodes

## haversine_distance centralized in utils.py

def create_spatial_index(xml_nodes):
    """
    Create a KDTree spatial index from the coordinates in xml_nodes.
    
    Parameters:
        xml_nodes (dict): Dictionary where keys are (lat, lon) tuples and values are XML node dictionaries.
        
    Returns:
        tuple: (KDTree, list of points, list of corresponding xml_nodes)
    """
    # Extract coordinates and convert to radians
    points = []
    nodes_list = []
    
    for (lat, lon), node in xml_nodes.items():
        # Convert to radians for better accuracy in spherical calculations
        lat_rad = radians(float(lat))
        lon_rad = radians(float(lon))
        # Store as a 3D point on a unit sphere 
        # (x, y, z) = (cos(lat)*cos(lon), cos(lat)*sin(lon), sin(lat))
        x = cos(lat_rad) * cos(lon_rad)
        y = cos(lat_rad) * sin(lon_rad)
        z = sin(lat_rad)
        
        points.append((x, y, z))
        nodes_list.append(((lat, lon), node))
    
    # Create KDTree
    if points:
        tree = KDTree(points)
        return tree, points, nodes_list
    else:
        return None, [], []

def distance_matching(unmatched_df, xml_nodes, run_stage1=True, run_stage2=True, max_distance=50, all_xml_nodes_for_stage4=None):
    """
    Three-stage distance matching with boolean flags to control execution.
    
    Stage 1:
      For unmatched ATLAS entries that share a UIC reference, uic_name, or name, check if there's an equal number of OSM nodes
      with that UIC reference, uic_name, or name. If so, try to match them using a conflict-free proximity matching where
      each ATLAS entry matches to its closest OSM node and vice versa.
    
    Stage 2:
      When run_stage1 is True, attempts to find an OSM node within max_distance whose local_ref
      exactly (case-insensitive) matches the ATLAS designation.
      When stage 3 is disabled, the code is optimized by checking for a valid local_ref before
      computing the distance.

    Stage 3:
      When run_stage2 is True and no Stage 2 match is found, the following conditions are checked:
      1. If there is exactly one candidate within max_distance, match to that candidate.
      2. If there are multiple candidates within max_distance:
         - Determine the closest OSM node (distance d1) and the second closest node (distance d2)
         - Match to the closest node only if both:
           a) The second closest node is at least 10 meters away (d2 >= 10)
           b) The closest node is at least 4 times closer than the second closest (d2/d1 >= 4)
           
    Stage 4:
      Identifies ATLAS entries that have no OSM nodes within 100 meters and tags them.
      This helps identify areas where OSM coverage is lacking compared to ATLAS data.

    Parameters:
        unmatched_df (pd.DataFrame): CSV rows with coordinate and designation info.
        xml_nodes (dict): Dictionary where keys are (lat, lon) tuples and values are XML node dictionaries.
        run_stage1 (bool): If True, run Stage 2 matching.
        run_stage2 (bool): If True, run Stage 3 matching.
        max_distance (float): Maximum allowed distance (meters) for a match.
        all_xml_nodes_for_stage4 (dict): Dictionary where keys are (lat, lon) tuples and values are XML node dictionaries for Stage 4.

    Returns:
        List[dict]: List of match records (dictionaries) with candidate pool info.
    """
    matches = []
    
    # Create spatial index for efficient nearest neighbor queries (Stage 1–3)
    spatial_tree, points, nodes_list = create_spatial_index(xml_nodes)
    
    # Convert max_distance from meters to radians for KDTree query
    # Approximate conversion (small distances): 1 meter ≈ 1/6371000 radians
    # Convert max_distance from meters to radians for KDTree query
    # We're using 3D points on a unit sphere, so need to convert from meters to chord length
    # For small distances, we can approximate: chord_length ≈ 2 * sin(angle/2)
    # where angle = distance/R
    max_distance_rad = 2 * sin((max_distance / 6371000.0) / 2)
    
    operator_mismatches = []
    # Track unique organization mismatches
    unique_org_mismatches = set()
    
    # Helper function to create match dictionary and handle operator mismatches
    def create_match_dict(csv_row, osm_lat, osm_lon, osm_node, distance, match_type, 
                          matching_notes, candidate_pool_size, designation, designation_official, business_org_abbr):
        
        #Create a standardized match dictionary and handle operator mismatches.
        
        osm_local_ref = str(osm_node.get('local_ref', "")).strip() if osm_node.get('local_ref') is not None else ""
        osm_network = osm_node.get('tags', {}).get('network', '')
        osm_operator = osm_node.get('tags', {}).get('operator', '')
        osm_railway = osm_node.get('tags', {}).get('railway', '')
        osm_amenity = osm_node.get('tags', {}).get('amenity', '')
        osm_aerialway = osm_node.get('tags', {}).get('aerialway', '')
        
        # Check operator match if OSM operator is not null
        operator_match = True
        if osm_operator:
            operator_match = (osm_operator == business_org_abbr)
        
        match_dict = {
            'sloid': csv_row['sloid'],
            'number': csv_row.get('number'),
            'csv_lat': csv_row['wgs84North'],
            'csv_lon': csv_row['wgs84East'],
            'csv_business_org_abbr': business_org_abbr,
            'osm_lat': osm_lat,
            'osm_lon': osm_lon,
            'distance_m': distance,
            'osm_node_id': osm_node['node_id'],
            'osm_local_ref': osm_local_ref,
            'osm_network': osm_network,
            'osm_operator': osm_operator,
            'osm_railway': osm_railway,
            'osm_amenity': osm_amenity,
            'osm_aerialway': osm_aerialway,
            'osm_name': osm_node['tags'].get('name', ''),
            'osm_uic_name': osm_node['tags'].get('uic_name', ''),
            'osm_uic_ref': osm_node['tags'].get('uic_ref', ''),
            'osm_public_transport': osm_node['tags'].get('public_transport', ''),
            'csv_designation': designation,
            'csv_designation_official': designation_official,
            'match_type': match_type,
            'candidate_pool_size': candidate_pool_size,
            'matching_notes': matching_notes
        }
        
        # If there's an operator mismatch, record it
        if not operator_match and osm_operator:
            match_dict['matching_notes'] += f" [OPERATOR MISMATCH: OSM={osm_operator}, ATLAS={business_org_abbr}]"
            operator_mismatches.append(match_dict.copy())
            # Add to unique mismatches set
            unique_org_mismatches.add((osm_operator, business_org_abbr))
        
        return match_dict

    # Stage 0: Group-based proximity matching for UIC references, uic_name, or name
    # Create dictionaries of OSM nodes by different identifiers
    osm_by_uic = defaultdict(list)
    osm_by_uic_name = defaultdict(list)
    osm_by_name = defaultdict(list)
    # Create separate dictionaries for stop_position nodes
    osm_by_uic_stop_position = defaultdict(list)
    osm_by_uic_name_stop_position = defaultdict(list)
    osm_by_name_stop_position = defaultdict(list)
    
    for (xml_lat, xml_lon), xml_node in xml_nodes.items():
        # Check if this is a stop_position node
        is_stop_position = xml_node['tags'].get('public_transport') == 'stop_position'
        
        # Group by UIC reference
        uic_ref = xml_node['tags'].get('uic_ref')
        if uic_ref:
            osm_by_uic[uic_ref].append({
                'lat': xml_lat,
                'lon': xml_lon,
                'node': xml_node
            })
            if is_stop_position:
                osm_by_uic_stop_position[uic_ref].append({
                    'lat': xml_lat,
                    'lon': xml_lon,
                    'node': xml_node
                })
        
        # Group by uic_name
        uic_name = xml_node['tags'].get('uic_name')
        if uic_name:
            osm_by_uic_name[uic_name].append({
                'lat': xml_lat,
                'lon': xml_lon,
                'node': xml_node
            })
            if is_stop_position:
                osm_by_uic_name_stop_position[uic_name].append({
                    'lat': xml_lat,
                    'lon': xml_lon,
                    'node': xml_node
                })
        
        # Group by name
        name = xml_node['tags'].get('name')
        if name:
            osm_by_name[name].append({
                'lat': xml_lat,
                'lon': xml_lon,
                'node': xml_node
            })
            if is_stop_position:
                osm_by_name_stop_position[name].append({
                    'lat': xml_lat,
                    'lon': xml_lon,
                    'node': xml_node
                })
    
    # Keep track of matched ATLAS entries to exclude from later stages
    matched_sloids = set()
    used_osm_node_ids = set()
    
    # Function to process matches for a group
    def process_group_matches(atlas_entries, osm_entries, osm_stop_position_entries, match_field):
        group_matches = []
        
        # Filter out already used OSM nodes
        osm_entries = [e for e in osm_entries if e['node']['node_id'] not in used_osm_node_ids]
        osm_stop_position_entries = [e for e in osm_stop_position_entries if e['node']['node_id'] not in used_osm_node_ids]
        
        # Try the original condition first (equal number of ATLAS and all OSM entries)
        if len(atlas_entries) == len(osm_entries) and len(atlas_entries) > 0:
            # Build distance matrix between all pairs
            distance_matrix = []
            for a_idx, atlas_entry in enumerate(atlas_entries):
                csv_lat = float(atlas_entry['wgs84North'])
                csv_lon = float(atlas_entry['wgs84East'])
                
                for o_idx, osm_entry in enumerate(osm_entries):
                    osm_lat = osm_entry['lat']
                    osm_lon = osm_entry['lon']
                    
                    distance = haversine_distance(csv_lat, csv_lon, osm_lat, osm_lon)
                    if distance is not None:
                        distance_matrix.append((a_idx, o_idx, distance))
            
            # Sort by distance
            distance_matrix.sort(key=lambda x: x[2])
            
            # For each ATLAS entry, find its closest OSM node
            atlas_to_osm = {}
            for a_idx, o_idx, distance in distance_matrix:
                if a_idx not in atlas_to_osm:
                    atlas_to_osm[a_idx] = (o_idx, distance)
            
            # For each OSM node, find its closest ATLAS entry
            osm_to_atlas = {}
            for a_idx, o_idx, distance in distance_matrix:
                if o_idx not in osm_to_atlas:
                    osm_to_atlas[o_idx] = (a_idx, distance)
            
            # Check if the mapping is reciprocal (conflict-free)
            is_conflict_free = True
            for a_idx, (o_idx, _) in atlas_to_osm.items():
                if o_idx in osm_to_atlas and osm_to_atlas[o_idx][0] != a_idx:
                    is_conflict_free = False
                    break
            
            # If conflict-free, create matches
            if is_conflict_free:
                # NEW: Check if all proposed matches are within the max_distance
                all_within_distance = True
                for a_idx, (o_idx, distance) in atlas_to_osm.items():
                    if distance > max_distance:
                        all_within_distance = False
                        logger.debug(f"Group match for {match_field} invalidated. Distance {distance:.2f}m > {max_distance}m.")
                        break

                if all_within_distance:
                    for a_idx, (o_idx, distance) in atlas_to_osm.items():
                        atlas_entry = atlas_entries[a_idx]
                        osm_entry = osm_entries[o_idx]
                        
                        sloid = atlas_entry['sloid']
                        if sloid in matched_sloids: continue
                        matched_sloids.add(sloid)
                        used_osm_node_ids.add(osm_entry['node']['node_id'])
                        
                        otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
                        designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                        business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip() if pd.notna(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn')) else ""
                        
                        osm_node = osm_entry['node']
                        osm_lat = osm_entry['lat']
                        osm_lon = osm_entry['lon']
                        
                        match_dict = create_match_dict(
                            atlas_entry, osm_lat, osm_lon, osm_node, distance,
                            f'distance_matching_1_{match_field}', 
                            f"Conflict-free proximity match for the same {match_field}",
                            len(osm_entries), otdp_designation, designation_official, business_org_abbr
                        )
                        
                        group_matches.append(match_dict)
        
        # If no matches found with all nodes, try matching only with stop_position nodes
        if not group_matches and len(atlas_entries) == len(osm_stop_position_entries) and len(atlas_entries) > 0:
            # Build distance matrix between all pairs
            distance_matrix = []
            for a_idx, atlas_entry in enumerate(atlas_entries):
                csv_lat = float(atlas_entry['wgs84North'])
                csv_lon = float(atlas_entry['wgs84East'])
                
                for o_idx, osm_entry in enumerate(osm_stop_position_entries):
                    osm_lat = osm_entry['lat']
                    osm_lon = osm_entry['lon']
                    
                    distance = haversine_distance(csv_lat, csv_lon, osm_lat, osm_lon)
                    if distance is not None:
                        distance_matrix.append((a_idx, o_idx, distance))
            
            # Sort by distance
            distance_matrix.sort(key=lambda x: x[2])
            
            # For each ATLAS entry, find its closest OSM node
            atlas_to_osm = {}
            for a_idx, o_idx, distance in distance_matrix:
                if a_idx not in atlas_to_osm:
                    atlas_to_osm[a_idx] = (o_idx, distance)
            
            # For each OSM node, find its closest ATLAS entry
            osm_to_atlas = {}
            for a_idx, o_idx, distance in distance_matrix:
                if o_idx not in osm_to_atlas:
                    osm_to_atlas[o_idx] = (a_idx, distance)
            
            # Check if the mapping is reciprocal (conflict-free)
            is_conflict_free = True
            for a_idx, (o_idx, _) in atlas_to_osm.items():
                if o_idx in osm_to_atlas and osm_to_atlas[o_idx][0] != a_idx:
                    is_conflict_free = False
                    break
            
            # If conflict-free, create matches
            if is_conflict_free:
                # NEW: Check if all proposed matches are within the max_distance
                all_within_distance = True
                for a_idx, (o_idx, distance) in atlas_to_osm.items():
                    if distance > max_distance:
                        all_within_distance = False
                        logger.debug(f"Group match for {match_field} (stop_position) invalidated. Distance {distance:.2f}m > {max_distance}m.")
                        break

                if all_within_distance:
                    for a_idx, (o_idx, distance) in atlas_to_osm.items():
                        atlas_entry = atlas_entries[a_idx]
                        osm_entry = osm_stop_position_entries[o_idx]
                        
                        sloid = atlas_entry['sloid']
                        if sloid in matched_sloids: continue
                        matched_sloids.add(sloid)
                        used_osm_node_ids.add(osm_entry['node']['node_id'])
                        
                        otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
                        designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                        business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip() if pd.notna(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn')) else ""
                        
                        osm_node = osm_entry['node']
                        osm_lat = osm_entry['lat']
                        osm_lon = osm_entry['lon']
                        
                        match_dict = create_match_dict(
                            atlas_entry, osm_lat, osm_lon, osm_node, distance,
                            f'distance_matching_1_{match_field}_stop_position', 
                            f"Conflict-free proximity match for the same {match_field} (stop_position nodes only)",
                            len(osm_stop_position_entries), otdp_designation, designation_official, business_org_abbr
                        )
                        
                        group_matches.append(match_dict)
        
        return group_matches
    
    try:
        # 1. First try to match by UIC reference
        grouped_atlas_by_uic = unmatched_df.groupby('number')
        for uic_ref, group in grouped_atlas_by_uic:
            # Convert to string for comparison
            uic_ref_str = str(uic_ref)
            
            # Skip if no OSM nodes for this UIC reference
            if uic_ref_str not in osm_by_uic:
                continue
                
            atlas_entries = group.to_dict(orient="records")
            osm_entries = osm_by_uic[uic_ref_str]
            osm_stop_position_entries = osm_by_uic_stop_position[uic_ref_str]
            
            matches.extend(process_group_matches(atlas_entries, osm_entries, osm_stop_position_entries, "UIC reference"))
        
        # Filter out already matched entries before trying next matching method
        remaining_df = unmatched_df[~unmatched_df['sloid'].isin(matched_sloids)]
        
        # 2. Then try to match by uic_name if available
        if 'designationOfficial' in remaining_df.columns:
            grouped_atlas_by_uic_name = remaining_df.groupby('designationOfficial')
            for uic_name, group in grouped_atlas_by_uic_name:
                if not pd.isna(uic_name) and uic_name in osm_by_uic_name:
                    atlas_entries = group.to_dict(orient="records")
                    osm_entries = osm_by_uic_name[uic_name]
                    osm_stop_position_entries = osm_by_uic_name_stop_position[uic_name]
                    
                    matches.extend(process_group_matches(atlas_entries, osm_entries, osm_stop_position_entries, "uic_name"))
        
        # Filter again
        remaining_df = unmatched_df[~unmatched_df['sloid'].isin(matched_sloids)]
        
        # 3. Finally try to match by name (using designationOfficial instead of designation)
        if 'designationOfficial' in remaining_df.columns:
            grouped_atlas_by_name = remaining_df.groupby('designationOfficial')
            for name, group in grouped_atlas_by_name:
                if not pd.isna(name) and name in osm_by_name:
                    atlas_entries = group.to_dict(orient="records")
                    osm_entries = osm_by_name[name]
                    osm_stop_position_entries = osm_by_name_stop_position[name]
                    
                    matches.extend(process_group_matches(atlas_entries, osm_entries, osm_stop_position_entries, "name"))
    
    except Exception as e:
        logger.error(f"Error in Stage 0 distance matching: {e}")
    
    # Filter out already matched ATLAS entries for the remaining stages
    remaining_df = unmatched_df[~unmatched_df['sloid'].isin(matched_sloids)]
    
    # Continue with existing stages for remaining entries
    for idx, csv_row in tqdm(remaining_df.iterrows(), total=len(remaining_df), desc="Distance Matching", file=sys.stdout, mininterval=1.0, ascii=True, smoothing=0.1):
        try:
            csv_lat = float(csv_row['wgs84North'])
            csv_lon = float(csv_row['wgs84East'])
            designation = str(csv_row['designation']).strip() if pd.notna(csv_row['designation']) else ""
            # Get designation_official similar to other locations in the code
            designation_official = str(csv_row.get('designationOfficial')).strip() if pd.notna(csv_row.get('designationOfficial')) else designation
            # Get business organization abbreviation 
            business_org_abbr = str(csv_row.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip() if pd.notna(csv_row.get('servicePointBusinessOrganisationAbbreviationEn')) else ""
            # Debug logging for troubleshooting
            logger.debug(f"Processing ATLAS entry with designation: '{designation}' (type: {type(designation)})")
            
            # Convert csv_lat, csv_lon to 3D point on unit sphere for KDTree query
            csv_lat_rad = radians(csv_lat)
            csv_lon_rad = radians(csv_lon)
            query_point = [
                cos(csv_lat_rad) * cos(csv_lon_rad),
                cos(csv_lat_rad) * sin(csv_lon_rad),
                sin(csv_lat_rad)
            ]
        except Exception as e:
            logger.error(f"Skipping CSV row (sloid: {csv_row.get('sloid', 'NA')}) due to invalid data: {e}")
            continue

        candidate_pool = []
        stage1_match = None
        min_distance_1 = float('inf')
        
        # Use KDTree to find nearby nodes
        if spatial_tree is not None:
            # Query KDTree for nodes within max_distance
            # Return distances & indices of points within max_distance_rad
            dists, indices = spatial_tree.query(query_point, k=len(points), distance_upper_bound=max_distance_rad)
            
            # Filter out invalid indices (beyond number of points)
            valid_indices = [i for i in range(len(indices)) if indices[i] < len(nodes_list)]
            
            # Check each nearby node
            for i in valid_indices:
                try:
                    idx = indices[i]
                    (xml_lat, xml_lon), xml_node = nodes_list[idx]
                    
                    # Exclude already matched OSM nodes
                    if xml_node['node_id'] in used_osm_node_ids:
                        continue
                    
                    # Calculate actual haversine distance (more accurate)
                    distance = haversine_distance(csv_lat, csv_lon, xml_lat, xml_lon)
                    if distance is None or distance > max_distance:
                        continue
                    
                    # Get the OSM local_ref, making sure it's a string
                    osm_local_ref = str(xml_node.get('local_ref', "")).strip() if xml_node.get('local_ref') is not None else ""
                    # Get OSM network and operator
                    osm_network = xml_node.get('tags', {}).get('network', '')
                    osm_operator = xml_node.get('tags', {}).get('operator', '')
                    
                    # Check operator match if OSM operator is not null
                    operator_match = True
                    if osm_operator:
                        operator_match = (osm_operator == business_org_abbr)
                    
                    # Build candidate pool
                    candidate_pool.append({
                        'lat': xml_lat,
                        'lon': xml_lon,
                        'node': xml_node,
                        'distance': distance,
                        'operator_match': operator_match
                    })
                    
                    # Stage 1 check - if enabled and node has matching local_ref
                    if run_stage1 and osm_local_ref and osm_local_ref.lower() == designation.lower():
                        if distance < min_distance_1:
                            min_distance_1 = distance
                            stage1_match = create_match_dict(
                                csv_row, xml_lat, xml_lon, xml_node, distance,
                                'distance_matching_2', "Exact local_ref match within max_distance",
                                len(candidate_pool), designation, designation_official, business_org_abbr
                            )
                except Exception as e:
                    logger.error(f"Error processing nearby node: {e}")
                    continue
        
        # If a Stage 1 match was found, add it to the results.
        if stage1_match:
            matches.append(stage1_match)
            used_osm_node_ids.add(stage1_match['osm_node_id'])
            matched_sloids.add(stage1_match['sloid'])
        # Otherwise, if Stage 2 is enabled, check the new relative distance comparison conditions
        elif run_stage2 and candidate_pool:
            # Sort candidate pool by distance
            candidate_pool.sort(key=lambda x: x['distance'])
            
            # Case 1: Only one candidate within max_distance
            if len(candidate_pool) == 1:
                candidate = candidate_pool[0]
                match_dict = create_match_dict(
                    csv_row, candidate['lat'], candidate['lon'], candidate['node'], candidate['distance'],
                    'distance_matching_3a', "Single candidate within max_distance",
                    len(candidate_pool), designation, designation_official, business_org_abbr
                )
                matches.append(match_dict)
                used_osm_node_ids.add(candidate['node']['node_id'])
                matched_sloids.add(csv_row['sloid'])
            # Case 2: Multiple candidates - check relative distance conditions
            elif len(candidate_pool) > 1:
                # Get the closest and second closest candidates
                closest = candidate_pool[0]
                second_closest = candidate_pool[1]
                
                d1 = closest['distance']
                d2 = second_closest['distance']
                
                # Check conditions:
                # 1. Second closest node is at least 10 meters away (d2 >= 10)
                # 2. Closest node is at least 4 times closer than second closest (d2/d1 >= 4)
                if d2 >= 10 and d2/d1 >= 4:
                    match_dict = create_match_dict(
                        csv_row, closest['lat'], closest['lon'], closest['node'], d1,
                        'distance_matching_3b', 
                        f"Closest node ({d1:.2f}m) matched with relative distance ratio {d2/d1:.2f} > 4 to second closest ({d2:.2f}m)",
                        len(candidate_pool), designation, designation_official, business_org_abbr
                    )
                    matches.append(match_dict)
                    used_osm_node_ids.add(closest['node']['node_id'])
                    matched_sloids.add(csv_row['sloid'])
    
    # Stage 4: Check for ATLAS entries with no nearby OSM nodes (within isolation radius)
    extended_distance = get_isolation_radius()  # meters
    extended_distance_rad = 2 * sin((extended_distance / 6371000.0) / 2)

    # Get the final unmatched entries
    final_unmatched_atlas = unmatched_df[~unmatched_df['sloid'].isin(matched_sloids)]

    # Prepare spatial index for Stage 4 up-front
    if all_xml_nodes_for_stage4 is not None:
        stage4_spatial_tree, _, stage4_nodes_list = create_spatial_index(all_xml_nodes_for_stage4)
        if stage4_spatial_tree is None:
            logger.warning("Failed to create spatial index from all_xml_nodes_for_stage4 for Stage 4. Falling back to Stage 1–3 index.")
            stage4_spatial_tree, stage4_nodes_list = spatial_tree, nodes_list
    else:
        stage4_spatial_tree, stage4_nodes_list = spatial_tree, nodes_list
    
    for idx, csv_row in tqdm(final_unmatched_atlas.iterrows(), total=len(final_unmatched_atlas), desc="Stage 4 - Identifying entries with no nearby OSM nodes", file=sys.stdout, mininterval=1.0, ascii=True, smoothing=0.1):
        try:
            csv_lat = float(csv_row['wgs84North'])
            csv_lon = float(csv_row['wgs84East'])
            designation = str(csv_row['designation']).strip() if pd.notna(csv_row['designation']) else ""
            designation_official = str(csv_row.get('designationOfficial')).strip() if pd.notna(csv_row.get('designationOfficial')) else designation
            business_org_abbr = str(csv_row.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip() if pd.notna(csv_row.get('servicePointBusinessOrganisationAbbreviationEn')) else ""
            
            # Convert to 3D point for KDTree query
            csv_lat_rad = radians(csv_lat)
            csv_lon_rad = radians(csv_lon)
            query_point = [
                cos(csv_lat_rad) * cos(csv_lon_rad),
                cos(csv_lat_rad) * sin(csv_lon_rad),
                sin(csv_lat_rad)
            ]
            
            has_nearby_nodes = False
            
            # Use KDTree to check for nearby nodes within 50 meters
            if stage4_spatial_tree is not None:
                # Query KDTree for the nearest node within extended_distance
                # k=1 returns scalar dists/indices if no neighbor found, array otherwise
                dists, indices = stage4_spatial_tree.query(query_point, k=1, distance_upper_bound=extended_distance_rad)

                # Check if *any* node was found within the radius by checking the distance
                # np.inf is returned for dists if no neighbor is found
                if np.isfinite(dists): # If distance is finite, a neighbor was found
                    # For k=1, 'indices' is the index of the found neighbor (scalar)
                    node_idx = indices

                    # Ensure the index is within the bounds of the nodes list
                    if node_idx < len(stage4_nodes_list):
                        try:
                            # Retrieve Node Data
                            (xml_lat, xml_lon), xml_node = stage4_nodes_list[node_idx]

                            # Calculate actual haversine distance (more accurate)
                            distance = haversine_distance(csv_lat, csv_lon, xml_lat, xml_lon)
                            if distance is not None and distance <= extended_distance:
                                has_nearby_nodes = True
                        except Exception as inner_e:
                            logger.error(f"Error processing nearby node data for sloid {csv_row.get('sloid', 'NA')} (node index {node_idx}): {inner_e}")
                            # Treat as no nearby node if processing fails
                            has_nearby_nodes = False
                    else:
                        # This case should ideally not happen if np.isfinite(dists) is true and KDTree is correct
                        logger.warning(f"KDTree query returned finite distance but invalid index {node_idx} >= {len(stage4_nodes_list)} for sloid {csv_row.get('sloid', 'NA')}. Treating as no nearby node.")
                        has_nearby_nodes = False
                # If dists is infinite, has_nearby_nodes remains False, correctly indicating no nearby node found.

            # If no nearby nodes within 50 meters, create a special match entry
            if not has_nearby_nodes:
                # Create a dummy OSM node for record keeping
                dummy_node = {
                    'node_id': 'NA',
                    'tags': {},
                    'local_ref': None
                }
                
                match_dict = {
                    'sloid': csv_row['sloid'],
                    'number': csv_row.get('number'),
                    'csv_lat': csv_lat,
                    'csv_lon': csv_lon,
                    'csv_business_org_abbr': business_org_abbr,
                    'osm_lat': None,
                    'osm_lon': None,
                    'distance_m': None,
                    'osm_node_id': 'NA',
                    'osm_local_ref': '',
                    'osm_network': '',
                    'osm_operator': '',
                    'osm_railway': '',
                    'osm_amenity': '',
                    'osm_aerialway': '',
                    'osm_name': '',
                    'osm_uic_name': '',
                    'osm_uic_ref': '',
                    'osm_public_transport': '',
                    'csv_designation': designation,
                    'csv_designation_official': designation_official,
                    'match_type': 'no_nearby_counterpart',
                    'candidate_pool_size': 0,
                    'matching_notes': f"No OSM nodes found within {extended_distance} meters"
                }
                
                matches.append(match_dict)
                
        except Exception as e:
            # Enhanced logging: Include exception type and traceback
            tb_str = traceback.format_exc()
            logger.error(f"Error in Stage 4 processing for sloid {csv_row.get('sloid', 'NA')}: {type(e).__name__} - {e}\nTraceback:\n{tb_str}")
    
    # Write unique organization mismatches to file
    if unique_org_mismatches:
        with open('data/debug/org_mismatches_review.txt', 'w') as f:
            f.write("===== UNIQUE OPERATOR MISMATCHES (DISTANCE MATCHING) =====\n")
            f.write(f"Found {len(unique_org_mismatches)} unique operator mismatches:\n\n")
            for i, (osm_op, atlas_op) in enumerate(sorted(unique_org_mismatches), 1):
                f.write(f"{i}. OSM: {osm_op} | ATLAS: {atlas_op}\n")
        
        logger.info(f"Wrote {len(unique_org_mismatches)} unique operator mismatches to data/debug/org_mismatches_review.txt")
    
    return matches