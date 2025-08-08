import sys
import pandas as pd
from tqdm import tqdm
from matching_process.utils import is_osm_station, haversine_distance


def exact_matching(atlas_df: pd.DataFrame, uic_ref_dict):
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

    # Group ATLAS entries by UIC reference (number). Avoid repeated astype in the loop
    number_as_str = atlas_df['number'].astype(str)
    grouped_atlas = atlas_df.groupby(number_as_str)

    # Bind frequently used globals to locals for faster access in tight loops
    is_station = is_osm_station
    haversine = haversine_distance

    # Disable tqdm when not attached to a TTY to reduce overhead in batch runs
    for uic_ref, group in tqdm(grouped_atlas, total=len(grouped_atlas), desc="Exact Matching", disable=not sys.stderr.isatty()):
        atlas_entries = group.to_dict(orient="records")
        uic_ref_str = str(uic_ref)
        osm_candidates = uic_ref_dict.get(uic_ref_str, [])

        # Skip if no OSM candidates for this UIC reference
        if not osm_candidates:
            for entry in atlas_entries:
                unmatched.append(entry)
            continue

        # Filter out already used OSM nodes and OSM stations
        available_osm = [
            cand for cand in osm_candidates
            if cand['node_id'] not in used_osm_ids and not is_station(cand)
        ]

        # Case 1: No available OSM nodes (all used previously or are stations)
        if not available_osm:
            for entry in atlas_entries:
                unmatched.append(entry)
            continue

        # Case 2: Only one OSM node for this UIC - match all ATLAS entries to it
        available_osm_len = len(available_osm)
        if available_osm_len == 1:
            osm_node = available_osm[0]
            for atlas_entry in atlas_entries:
                csv_lat = atlas_entry['wgs84North']
                csv_lon = atlas_entry['wgs84East']
                otdp_designation = str(atlas_entry['designation']).strip() if pd.notna(atlas_entry['designation']) else ""
                designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()

                dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                tags = osm_node['tags']
                osm_network = tags.get('network', '')
                osm_operator = tags.get('operator', '')
                osm_amenity = tags.get('amenity', '')
                osm_railway = tags.get('railway', '')
                osm_aerialway = tags.get('aerialway', '')

                matches.append({
                    'sloid': atlas_entry['sloid'],
                    'number': atlas_entry['number'],
                    'uic_ref': uic_ref_str,
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
                    'osm_original_operator': tags.get('original_operator'),
                    'osm_amenity': osm_amenity,
                    'osm_railway': osm_railway,
                    'osm_aerialway': osm_aerialway,
                    'osm_name': tags.get('name', ''),
                    'osm_uic_name': tags.get('uic_name', ''),
                    'osm_uic_ref': tags.get('uic_ref', ''),
                    'osm_public_transport': tags.get('public_transport', ''),
                    'distance_m': dist,
                    'match_type': 'exact',
                    'candidate_pool_size': available_osm_len,
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
                dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                tags = osm_node['tags']
                osm_network = tags.get('network', '')
                osm_operator = tags.get('operator', '')
                osm_amenity = tags.get('amenity', '')
                osm_railway = tags.get('railway', '')
                osm_aerialway = tags.get('aerialway', '')

                matches.append({
                    'sloid': atlas_entry['sloid'],
                    'number': atlas_entry['number'],
                    'uic_ref': uic_ref_str,
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
                    'osm_original_operator': tags.get('original_operator'),
                    'osm_amenity': osm_amenity,
                    'osm_railway': osm_railway,
                    'osm_aerialway': osm_aerialway,
                    'osm_name': tags.get('name', ''),
                    'osm_uic_name': tags.get('uic_name', ''),
                    'osm_uic_ref': tags.get('uic_ref', ''),
                    'osm_public_transport': tags.get('public_transport', ''),
                    'distance_m': dist,
                    'match_type': 'exact',
                    'candidate_pool_size': available_osm_len,
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

                osm_local_ref = str(osm_node.get('local_ref') or "").strip()

                # Check for exact designation/local_ref match
                if otdp_designation and osm_local_ref and otdp_designation.lower() == osm_local_ref.lower():
                    csv_lat = atlas_entry['wgs84North']
                    csv_lon = atlas_entry['wgs84East']
                    designation_official = str(atlas_entry.get('designationOfficial')).strip() if pd.notna(atlas_entry.get('designationOfficial')) else otdp_designation
                    business_org_abbr = str(atlas_entry.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()

                    dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])
                    tags = osm_node['tags']
                    osm_network = tags.get('network', '')
                    osm_operator = tags.get('operator', '')
                    osm_amenity = tags.get('amenity', '')
                    osm_railway = tags.get('railway', '')
                    osm_aerialway = tags.get('aerialway', '')

                    matches.append({
                        'sloid': sloid,
                        'number': atlas_entry['number'],
                        'uic_ref': uic_ref_str,
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
                        'osm_original_operator': tags.get('original_operator'),
                        'osm_amenity': osm_amenity,
                        'osm_railway': osm_railway,
                        'osm_aerialway': osm_aerialway,
                        'osm_name': tags.get('name', ''),
                        'osm_uic_name': tags.get('uic_name', ''),
                        'osm_uic_ref': tags.get('uic_ref', ''),
                        'osm_public_transport': tags.get('public_transport', ''),
                        'distance_m': dist,
                        'match_type': 'exact',
                        'candidate_pool_size': available_osm_len,
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


