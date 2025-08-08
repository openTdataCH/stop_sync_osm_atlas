import pandas as pd
from tqdm import tqdm
from matching_process.utils import is_osm_station, haversine_distance


def name_based_matching(atlas_df: pd.DataFrame, name_index):
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


