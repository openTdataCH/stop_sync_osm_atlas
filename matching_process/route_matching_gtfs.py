import logging
from collections import defaultdict
from tqdm import tqdm
import pandas as pd

from .utils import haversine_distance
from .route_matching import (
    _load_and_prepare_route_data,
    _build_osm_indexes,
    _build_atlas_indexes,
    _identify_stage1_candidates,
    _identify_stage2_allowed_keys,
    _perform_stage1_matching,
    _perform_stage2_matching,
)

logger = logging.getLogger(__name__)


def perform_gtfs_matching(unmatched_df: pd.DataFrame, xml_nodes, max_distance: float, used_osm_nodes: set):
    """Performs GTFS-based route matching using route/direction IDs."""
    logger.info("Performing GTFS-based route matching...")

    atlas_route_map, osm_route_map = _load_and_prepare_route_data()

    # Filter xml_nodes to exclude already used ones
    available_xml_nodes = {k: v for k, v in xml_nodes.items() if v['node_id'] not in used_osm_nodes}

    # Build indexes on available nodes
    (
        osm_by_uic_route_dir,
        osm_by_route_dir,
        osm_by_uic_route_dir_normalized,
        osm_by_route_dir_normalized,
    ) = _build_osm_indexes(available_xml_nodes, osm_route_map)
    (
        atlas_by_uic_route_dir,
        atlas_stop_route_combinations,
        atlas_by_route_dir,
    ) = _build_atlas_indexes(unmatched_df, atlas_route_map)

    unique_uic_route_dir_keys, _ = _identify_stage1_candidates(
        atlas_by_uic_route_dir, osm_by_uic_route_dir, atlas_stop_route_combinations
    )
    stage2_allowed_keys, stage2_normalized_allowed_keys = _identify_stage2_allowed_keys(
        atlas_by_route_dir, osm_by_route_dir, osm_by_route_dir_normalized
    )
    all_stage2_allowed_keys = stage2_allowed_keys | stage2_normalized_allowed_keys

    matches = []
    used_osm_ids_gtfs = set()

    def create_gtfs_match_dict_fn(csv_row, osm_lat, osm_lon, osm_node, distance, match_type,
                                  matching_notes, candidate_pool_size, route, direction, business_org_abbr):
        from .route_matching import _create_match_dict
        return _create_match_dict(
            csv_row, osm_node, distance, match_type, matching_notes,
            csv_route=route, csv_direction=direction, candidate_pool_size=candidate_pool_size
        )

    for _, csv_row in tqdm(unmatched_df.iterrows(), total=len(unmatched_df), desc="GTFS Route Matching"):
        sloid = str(csv_row['sloid'])
        uic_ref = str(csv_row.get('number', '')).strip() if pd.notna(csv_row.get('number')) else ""
        business_org_abbr = str(csv_row.get('servicePointBusinessOrganisationAbbreviationEn', '')).strip()

        route_directions = atlas_route_map.get(sloid, [])
        if not route_directions:
            continue

        row_matched = False
        for rd in route_directions:
            if row_matched:
                break
            route, direction = rd['route'], rd['direction']

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

            match, matched = _perform_stage2_matching(
                csv_row, business_org_abbr, route, direction,
                osm_by_route_dir, osm_by_route_dir_normalized, max_distance, create_gtfs_match_dict_fn,
                all_stage2_allowed_keys, used_osm_ids_gtfs, used_osm_ids_gtfs
            )
            if matched:
                matches.append(match)
                used_osm_ids_gtfs.add(match['osm_node_id'])
                row_matched = True

    logger.info(f"GTFS matching found {len(matches)} new matches.")
    return matches, used_osm_ids_gtfs


