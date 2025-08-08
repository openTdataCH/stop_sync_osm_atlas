import logging
from collections import defaultdict
from tqdm import tqdm
import pandas as pd

from .utils import haversine_distance
from .route_matching import _get_osm_directions_from_xml, _create_match_dict

logger = logging.getLogger(__name__)


def perform_hrdf_matching(unmatched_df: pd.DataFrame, xml_nodes, osm_xml_file: str, used_osm_nodes: set):
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

        if pd.isna(atlas_uic_raw):
            continue
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
            if osm_id in used_osm_ids_hrdf:
                continue

            osm_name_dirs = osm_name_directions.get(osm_id, set())
            osm_uic_dirs = osm_uic_directions.get(osm_id, set())

            name_match = atlas_name_dirs.intersection(osm_name_dirs)
            uic_match = atlas_uic_dirs.intersection(osm_uic_dirs)

            if name_match or uic_match:
                match_subtype_parts = []
                if name_match:
                    match_subtype_parts.append("name")
                if uic_match:
                    match_subtype_parts.append("uic")

                match_type_str = f"route_hrdf_{'+'.join(match_subtype_parts)}"

                match = _create_match_dict(
                    atlas_row,
                    osm_node,
                    haversine_distance(atlas_row['wgs84North'], atlas_row['wgs84East'], osm_node['lat'], osm_node['lon']),
                    match_type_str,
                    f"Shared UIC ({atlas_uic}) and direction string.",
                )
                matches.append(match)
                used_osm_ids_hrdf.add(osm_id)
                break

    logger.info(f"HRDF matching found {len(matches)} new matches.")
    return matches, used_osm_ids_hrdf


