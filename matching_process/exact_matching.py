import sys
import pandas as pd
from tqdm import tqdm
from matching_process.utils import is_osm_station, haversine_distance
from matching_process.match_record import create_match_record, extract_atlas_fields


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

    # Bind frequently used globals to locals for faster access in tight loops
    is_station = is_osm_station
    haversine = haversine_distance
    pd_notna = pd.notna

    # Pre-group ATLAS rows in pure Python.
    #
    # Pandas `groupby(...)->to_dict()` per group can be surprisingly costly when
    # there are many small groups (which is common for UIC references).
    # Converting once and grouping in Python preserves:
    # - the same per-row dictionaries (same keys/values),
    # - the same within-group order (original CSV order),
    # - and the same group processing order as pandas `groupby` on `astype(str)`:
    #   lexicographic order of the stringified UIC key.
    atlas_records = atlas_df.to_dict(orient="records")
    atlas_by_uic = {}
    for rec in atlas_records:
        uic_key = str(rec.get("number"))
        atlas_by_uic.setdefault(uic_key, []).append(rec)

    uic_keys = sorted(atlas_by_uic.keys())

    # Disable tqdm when not attached to a TTY to reduce overhead in batch runs
    for uic_ref_str in tqdm(uic_keys, total=len(uic_keys), desc="Exact Matching", disable=not sys.stderr.isatty()):
        atlas_entries = atlas_by_uic[uic_ref_str]
        osm_candidates = uic_ref_dict.get(uic_ref_str, [])

        # Skip if no OSM candidates for this UIC reference
        if not osm_candidates:
            unmatched.extend(atlas_entries)
            continue

        # Filter out already used OSM nodes and OSM stations
        available_osm = [
            cand for cand in osm_candidates
            if cand['node_id'] not in used_osm_ids and not is_station(cand)
        ]

        # Case 1: No available OSM nodes (all used previously or are stations)
        if not available_osm:
            unmatched.extend(atlas_entries)
            continue

        # Case 2: Only one OSM node for this UIC - match all ATLAS entries to it
        available_osm_len = len(available_osm)
        if available_osm_len == 1:
            osm_node = available_osm[0]
            osm_node_id = osm_node['node_id']
            tags = osm_node['tags']
            osm_network = tags.get('network', '')
            osm_operator = tags.get('operator', '')
            osm_amenity = tags.get('amenity', '')
            osm_railway = tags.get('railway', '')
            osm_aerialway = tags.get('aerialway', '')
            osm_name = tags.get('name', '')
            osm_uic_name = tags.get('uic_name', '')
            osm_uic_ref = tags.get('uic_ref', '')
            osm_public_transport = tags.get('public_transport', '')
            osm_original_operator = tags.get('original_operator')

            for atlas_entry in atlas_entries:
                csv_lat = atlas_entry['wgs84North']
                csv_lon = atlas_entry['wgs84East']
                dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])

                # Use centralized factory function for match record creation
                match = create_match_record(
                    sloid=atlas_entry['sloid'],
                    csv_lat=csv_lat,
                    csv_lon=csv_lon,
                    osm_node=osm_node,
                    distance_m=dist,
                    match_type='exact',
                    matching_notes="Single OSM node for this UIC reference",
                    number=atlas_entry['number'],
                    uic_ref=uic_ref_str,
                    candidate_pool_size=available_osm_len,
                    **extract_atlas_fields(atlas_entry, pd_notna),
                )
                matches.append(match)
            used_osm_ids.add(osm_node_id)
            continue

        # Case 3: Only one ATLAS entry - match to all available OSM nodes
        if len(atlas_entries) == 1:
            atlas_entry = atlas_entries[0]
            csv_lat = atlas_entry['wgs84North']
            csv_lon = atlas_entry['wgs84East']
            atlas_fields = extract_atlas_fields(atlas_entry, pd_notna)

            # Match to all available OSM nodes
            for osm_node in available_osm:
                dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])

                # Use centralized factory function for match record creation
                match = create_match_record(
                    sloid=atlas_entry['sloid'],
                    csv_lat=csv_lat,
                    csv_lon=csv_lon,
                    osm_node=osm_node,
                    distance_m=dist,
                    match_type='exact',
                    matching_notes="Single ATLAS entry matched to multiple OSM nodes with same UIC reference",
                    number=atlas_entry['number'],
                    uic_ref=uic_ref_str,
                    candidate_pool_size=available_osm_len,
                    **atlas_fields,
                )
                matches.append(match)
                used_osm_ids.add(osm_node['node_id'])
            continue

        # Case 4: Multiple ATLAS and multiple OSM nodes - try to match by designation/local_ref
        matched_atlas_ids = set()
        matched_osm_ids = set()

        # First pass: Try to match based on exact local_ref/designation match (case-insensitive).
        #
        # Performance note:
        # The original implementation scanned *all* available OSM candidates for every ATLAS entry.
        # That can become O(N*M) for large UIC groups.
        # Here we build a lookup from normalized local_ref -> candidates (in original order)
        # and then only scan the much smaller candidate list for the relevant local_ref.
        local_ref_lookup = {}
        for cand in available_osm:
            lr = str(cand.get('local_ref') or "").strip()
            if not lr:
                continue
            local_ref_lookup.setdefault(lr.lower(), []).append((cand, lr))

        for atlas_entry in atlas_entries:
            sloid = atlas_entry['sloid']
            if sloid in matched_atlas_ids:
                continue

            otdp_designation = str(atlas_entry['designation']).strip() if pd_notna(atlas_entry['designation']) else ""
            if not otdp_designation:
                continue

            cand_list = local_ref_lookup.get(otdp_designation.lower())
            if not cand_list:
                continue

            for osm_node, osm_local_ref in cand_list:
                osm_id = osm_node['node_id']
                if osm_id in matched_osm_ids or osm_id in used_osm_ids:
                    continue

                csv_lat = atlas_entry['wgs84North']
                csv_lon = atlas_entry['wgs84East']
                dist = haversine(csv_lat, csv_lon, osm_node['lat'], osm_node['lon'])

                # Use centralized factory function for match record creation
                match = create_match_record(
                    sloid=sloid,
                    csv_lat=csv_lat,
                    csv_lon=csv_lon,
                    osm_node=osm_node,
                    distance_m=dist,
                    match_type='exact',
                    matching_notes="Exact local_ref/designation match",
                    number=atlas_entry['number'],
                    uic_ref=uic_ref_str,
                    candidate_pool_size=available_osm_len,
                    **extract_atlas_fields(atlas_entry, pd_notna),
                )
                matches.append(match)

                matched_atlas_ids.add(sloid)
                matched_osm_ids.add(osm_id)
                used_osm_ids.add(osm_id)
                break

        # Add all unmatched atlas entries to the unmatched list
        for atlas_entry in atlas_entries:
            if atlas_entry['sloid'] not in matched_atlas_ids:
                unmatched.append(atlas_entry)

    return matches, unmatched, used_osm_ids


