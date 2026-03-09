"""
Statistics Export Service

This module exports pipeline statistics to a central JSON file for use in documentation
and SVG diagrams. Statistics are generated at the end of the matching pipeline and
stored in data/stats.json.

Statistics are divided into two categories:
1. Pipeline stats: Generated during matching (static until next import)
2. User stats: Queried from database in real-time (problem resolutions, etc.)
"""

import json
import logging
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


STATS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'stats.json'
)


def export_pipeline_stats(
    matched_records: list,
    unmatched_atlas: list,
    unmatched_osm: list,
    duplicate_sloid_map: dict,
    no_nearby_osm_sloids: set,
    total_atlas_platforms: int = None,
    total_osm_nodes: int = None,
    atlas_route_stats: Dict[str, int] = None,
    osm_route_stats: Dict[str, int] = None,
    osm_nodes_with_routes: set = None,
) -> Dict[str, Any]:
    """
    Export comprehensive pipeline statistics after matching.
    
    This function analyzes the matching results and generates statistics
    that are used in documentation and SVG diagrams.
    
    Args:
        matched_records: List of matched record dictionaries
        unmatched_atlas: List of unmatched ATLAS entries
        unmatched_osm: List of unmatched OSM nodes
        duplicate_sloid_map: Map of duplicate ATLAS sloids
        no_nearby_osm_sloids: Set of ATLAS sloids with no OSM within 50m
        total_atlas_platforms: Total ATLAS platforms (optional, calculated if not provided)
        total_osm_nodes: Total OSM nodes processed (optional)
    
    Returns:
        Dictionary containing all computed statistics
    """
    
    # Calculate totals
    total_matched = len(matched_records)
    total_unmatched_atlas = len(unmatched_atlas)
    total_unmatched_osm = len(unmatched_osm)
    
    # Calculate total ATLAS if not provided
    if total_atlas_platforms is None:
        matched_sloids = {getattr(r.atlas_node, 'sloid', None) for r in matched_records if getattr(r.atlas_node, 'sloid', None)}
        unmatched_sloids = {getattr(r, 'sloid', None) for r in unmatched_atlas if getattr(r, 'sloid', None)}
        total_atlas_platforms = len(matched_sloids | unmatched_sloids)

    # Count distinct matched ATLAS sloids
    distinct_matched_atlas = len({getattr(r.atlas_node, 'sloid', None) for r in matched_records if getattr(r.atlas_node, 'sloid', None)})
    
    # Match rate calculation
    match_rate = (distinct_matched_atlas / total_atlas_platforms * 100) if total_atlas_platforms > 0 else 0
    
    # Count matches by type
    match_type_counts = {}
    for record in matched_records:
        match_type = getattr(record, 'match_type', 'unknown') or 'unknown'
        match_type_counts[match_type] = match_type_counts.get(match_type, 0) + 1
    
    # Extract specific match counts
    exact_matches = match_type_counts.get('exact', 0)
    name_matches = match_type_counts.get('name', 0)
    exact_postpass_matches = match_type_counts.get('exact_postpass', 0)
    duplicate_propagation_matches = match_type_counts.get('duplicate_propagation', 0)
    osm_group_propagation_matches = match_type_counts.get('osm_group_propagation', 0)
    
    # Distance matching breakdown
    distance_stage1 = sum(
        v for k, v in match_type_counts.items() 
        if k.startswith('distance_matching_1_')
    )
    distance_stage2 = match_type_counts.get('distance_matching_2', 0)
    distance_stage3a = match_type_counts.get('distance_matching_3a', 0)
    distance_stage3b = match_type_counts.get('distance_matching_3b', 0)
    total_distance_matches = distance_stage1 + distance_stage2 + distance_stage3a + distance_stage3b
    
    # Route matching breakdown
    route_gtfs_matches = sum(
        v for k, v in match_type_counts.items() 
        if k.startswith('route_gtfs') or k.startswith('route_unified_gtfs')
    )
    route_hrdf_matches = sum(
        v for k, v in match_type_counts.items() 
        if k.startswith('route_hrdf') or k.startswith('route_unified_hrdf')
    )
    total_route_matches = route_gtfs_matches + route_hrdf_matches
    
    # Unmatched OSM analysis matrix
    unmatched_osm_matrix = {
        "uic_only": 0,
        "local_ref_only": 0,
        "routes_only": 0,
        "uic_and_local": 0,
        "uic_and_routes": 0,
        "local_and_routes": 0,
        "all_three": 0,
        "none": 0
    }
    
    osm_routes_set = osm_nodes_with_routes or set()
    
    for node in unmatched_osm:
        node_id_str = str(getattr(node, 'node_id', ''))
        tags = getattr(node, 'tags', None) or {}
        
        has_uic = 'uic_ref' in tags
        has_local = bool(getattr(node, 'local_ref', None) or tags.get('local_ref'))
        has_routes = node_id_str in osm_routes_set
        
        if has_uic and has_local and has_routes:
            unmatched_osm_matrix["all_three"] += 1
        elif has_uic and has_local:
            unmatched_osm_matrix["uic_and_local"] += 1
        elif has_uic and has_routes:
            unmatched_osm_matrix["uic_and_routes"] += 1
        elif has_local and has_routes:
            unmatched_osm_matrix["local_and_routes"] += 1
        elif has_uic:
            unmatched_osm_matrix["uic_only"] += 1
        elif has_local:
            unmatched_osm_matrix["local_ref_only"] += 1
        elif has_routes:
            unmatched_osm_matrix["routes_only"] += 1
        else:
            unmatched_osm_matrix["none"] += 1
    
    # No nearby OSM count
    no_nearby_osm_count = len(no_nearby_osm_sloids) if no_nearby_osm_sloids else 0
    
    # Duplicate counts
    total_duplicate_sloids = len(duplicate_sloid_map) if duplicate_sloid_map else 0
    matched_duplicate_items = sum(
        1 for r in matched_records
        if getattr(r.atlas_node, 'sloid', None) and str(r.atlas_node.sloid) in duplicate_sloid_map
    )
    unmatched_duplicate_items = sum(
        1 for r in unmatched_atlas
        if getattr(r, 'sloid', None) and str(r.sloid) in duplicate_sloid_map
    )
    
    # Calculate Many-to-One metrics per stage
    mto_pairs_by_type = defaultdict(int)
    atlas_to_osm = defaultdict(set)
    osm_to_atlas = defaultdict(set)
    for record in matched_records:
        sloid = getattr(getattr(record, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(record, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            atlas_to_osm[str(sloid)].add(str(osm_id))
            osm_to_atlas[str(osm_id)].add(str(sloid))

    atlas_multi = {s for s, ids in atlas_to_osm.items() if len(ids) > 1}
    osm_multi = {n for n, ids in osm_to_atlas.items() if len(ids) > 1}

    for record in matched_records:
        sloid = getattr(getattr(record, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(record, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            if str(sloid) in atlas_multi or str(osm_id) in osm_multi:
                mt = getattr(record, 'match_type', 'unknown') or 'unknown'
                mto_pairs_by_type[mt] += 1

    
    # Build the stats object
    stats = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "version": "1.0",
        
        # High-level summary (for overview)
        "summary": {
            "atlas_platforms": total_atlas_platforms,
            "osm_nodes": total_osm_nodes or (total_matched + total_unmatched_osm),
            "matched_pairs": total_matched,
            "distinct_matched_atlas": distinct_matched_atlas,
            "match_rate_percent": round(match_rate, 1),
            "unmatched_atlas": total_unmatched_atlas,
            "unmatched_osm": total_unmatched_osm,
        },
        
        # Matching stage breakdown
        "matching_stages": {
            "exact": {
                "count": exact_matches,
                "mto": mto_pairs_by_type.get('exact', 0),
                "description": "UIC reference number equality"
            },
            "name": {
                "count": name_matches,
                "mto": mto_pairs_by_type.get('name', 0),
                "description": "Official name string matching"
            },
            "distance": {
                "count": total_distance_matches,
                "mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('distance_matching')),
                "description": "Proximity-based spatial matching (≤50m)",
                "breakdown": {
                    "stage1_group": distance_stage1,
                    "stage1_group_mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('distance_matching_1_')),
                    "stage2_local_ref": distance_stage2,
                    "stage2_local_ref_mto": mto_pairs_by_type.get('distance_matching_2', 0),
                    "stage3a_single": distance_stage3a,
                    "stage3a_single_mto": mto_pairs_by_type.get('distance_matching_3a', 0),
                    "stage3b_relative": distance_stage3b,
                    "stage3b_relative_mto": mto_pairs_by_type.get('distance_matching_3b', 0),
                }
            },
            "route": {
                "count": total_route_matches,
                "mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('route')),
                "description": "Shared transit route validation",
                "breakdown": {
                    "gtfs": route_gtfs_matches,
                    "gtfs_mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('route_gtfs') or k.startswith('route_unified_gtfs')),
                    "hrdf": route_hrdf_matches,
                    "hrdf_mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('route_hrdf') or k.startswith('route_unified_hrdf')),
                }
            },
            "post_processing": {
                "unique_by_uic": exact_postpass_matches,
                "unique_by_uic_mto": mto_pairs_by_type.get('exact_postpass', 0),
                "duplicate_propagation": duplicate_propagation_matches,
                "duplicate_propagation_mto": mto_pairs_by_type.get('duplicate_propagation', 0),
                "osm_group_propagation": osm_group_propagation_matches,
                "osm_group_propagation_mto": mto_pairs_by_type.get('osm_group_propagation', 0),
            }
        },
        
        # Unmatched analysis
        "unmatched_analysis": {
            "atlas": {
                "total": total_unmatched_atlas,
                "no_osm_within_50m": no_nearby_osm_count,
                "has_nearby_osm": total_unmatched_atlas - no_nearby_osm_count,
            },
            "osm": {
                "total": total_unmatched_osm,
                "matrix": unmatched_osm_matrix,
            }
        },
        
        # Duplicate information
        "duplicates": {
            "total_duplicate_sloids": total_duplicate_sloids,
            "matched_duplicates": matched_duplicate_items,
            "unmatched_duplicates": unmatched_duplicate_items,
        },
        
        # Raw match type counts for debugging/advanced use
        "match_type_counts": match_type_counts,
    }
    
    # Add detailed route stats if provided
    if atlas_route_stats or osm_route_stats:
        stats['routes'] = {}
        if atlas_route_stats:
            stats['routes'].update(atlas_route_stats)
            # Calculate percentages if total atlas is available
            if total_atlas_platforms and total_atlas_platforms > 0:
                any_route = atlas_route_stats.get('atlas_with_routes', 0)
                gtfs_matches = atlas_route_stats.get('atlas_gtfs_matches', 0)
                hrdf_matches = atlas_route_stats.get('atlas_hrdf_matches', 0)
                stats['routes']['atlas_with_routes_percent'] = round((any_route / total_atlas_platforms * 100), 1)
                stats['routes']['gtfs_coverage_percent'] = round((gtfs_matches / total_atlas_platforms * 100), 1)
                stats['routes']['hrdf_coverage_percent'] = round((hrdf_matches / total_atlas_platforms * 100), 1)
                
        if osm_route_stats:
            stats['routes'].update(osm_route_stats)
            if total_osm_nodes and total_osm_nodes > 0:
                osm_with_routes = osm_route_stats.get('osm_with_routes', 0)
                stats['routes']['osm_with_routes_percent'] = round((osm_with_routes / total_osm_nodes * 100), 1)

    return stats


def _classify_match_type(match_type: str) -> str:
    """Map a raw match_type string to a display stage name."""
    if match_type == 'exact':
        return 'exact'
    if match_type == 'name':
        return 'name'
    if match_type.startswith('distance_matching_1_'):
        return 'distance_stage1'
    if match_type == 'distance_matching_2':
        return 'distance_stage2'
    if match_type == 'distance_matching_3a':
        return 'distance_stage3a'
    if match_type == 'distance_matching_3b':
        return 'distance_stage3b'
    if 'gtfs' in match_type:
        return 'route_gtfs'
    if 'hrdf' in match_type:
        return 'route_hrdf'
    if match_type in ('duplicate_propagation', 'osm_group_propagation', 'exact_postpass'):
        return 'post_processing'
    return 'post_processing'


def _distance_stats(distances: List[float]) -> Dict[str, Any]:
    """Compute mean, median, p95 for a list of distances."""
    if not distances:
        return {"mean_m": None, "median_m": None, "p95_m": None, "count": 0}
    distances_sorted = sorted(distances)
    p95_idx = int(math.ceil(0.95 * len(distances_sorted))) - 1
    return {
        "mean_m": round(statistics.mean(distances_sorted), 2),
        "median_m": round(statistics.median(distances_sorted), 2),
        "p95_m": round(distances_sorted[max(0, p95_idx)], 2),
        "count": len(distances_sorted),
    }


def compute_quality_metrics(
    matched_records: list,
    all_osm_nodes: list,
    osm_groups: List[Tuple[str, str, str]],
) -> Dict[str, Any]:
    """Compute matching quality metrics from pipeline results.

    Builds a temporary KDTree of all OSM nodes to evaluate whether each
    matched pair uses the nearest available OSM node.
    """
    from scipy.spatial import KDTree
    from matching_and_import_db.utils.spatial_index import batch_to_xyz, to_xyz

    # ------------------------------------------------------------------
    # 1. Distance quality
    # ------------------------------------------------------------------
    all_distances: List[float] = []
    distances_by_stage: Dict[str, List[float]] = defaultdict(list)

    for rec in matched_records:
        d = getattr(rec, 'distance_m', None)
        if d is not None and not math.isnan(d):
            all_distances.append(d)
            stage = _classify_match_type(getattr(rec, 'match_type', '') or '')
            distances_by_stage[stage].append(d)

    overall_dist = _distance_stats(all_distances)
    by_stage_dist = {stage: _distance_stats(dists) for stage, dists in sorted(distances_by_stage.items())}

    # Build KDTree for "not matched to closest" and cross-predicate consistency
    osm_coords: List[Tuple[float, float]] = []
    osm_node_ids: List[str] = []
    for node in all_osm_nodes:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is not None and lon is not None and lat != 0.0 and lon != 0.0:
            osm_coords.append((float(lat), float(lon)))
            osm_node_ids.append(str(node.node_id))

    not_closest_count = 0
    consistent_count = 0
    total_evaluated = 0

    if osm_coords:
        osm_xyz = batch_to_xyz(osm_coords)
        tree = KDTree(osm_xyz)

        for rec in matched_records:
            atlas_node = getattr(rec, 'atlas_node', None)
            osm_node = getattr(rec, 'osm_node', None)
            if atlas_node is None or osm_node is None:
                continue
            a_lat, a_lon = getattr(atlas_node, 'lat', None), getattr(atlas_node, 'lon', None)
            matched_osm_id = str(osm_node.node_id)
            if a_lat is None or a_lon is None:
                continue

            query_point = to_xyz(a_lat, a_lon)
            _, idx = tree.query(query_point, k=1)
            nearest_osm_id = osm_node_ids[idx]

            total_evaluated += 1
            if nearest_osm_id == matched_osm_id:
                consistent_count += 1
            else:
                not_closest_count += 1

    not_closest_pct = round(not_closest_count / total_evaluated * 100, 1) if total_evaluated else 0.0
    consistency_pct = round(consistent_count / total_evaluated * 100, 1) if total_evaluated else 0.0

    distance_quality = {
        "overall": overall_dist,
        "by_stage": by_stage_dist,
        "not_matched_to_closest": {
            "count": not_closest_count,
            "total_evaluated": total_evaluated,
            "percent": not_closest_pct,
        },
    }

    # ------------------------------------------------------------------
    # 2. Many-to-one analysis
    # ------------------------------------------------------------------
    atlas_to_osm: Dict[str, set] = defaultdict(set)
    osm_to_atlas: Dict[str, set] = defaultdict(set)

    for rec in matched_records:
        sloid = getattr(getattr(rec, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            atlas_to_osm[str(sloid)].add(str(osm_id))
            osm_to_atlas[str(osm_id)].add(str(sloid))

    atlas_multi = {s: ids for s, ids in atlas_to_osm.items() if len(ids) > 1}
    osm_multi = {n: ids for n, ids in osm_to_atlas.items() if len(ids) > 1}

    many_to_one = {
        "atlas_to_multiple_osm": {
            "count": len(atlas_multi),
            "max_per_atlas": max((len(v) for v in atlas_multi.values()), default=0),
        },
        "osm_to_multiple_atlas": {
            "count": len(osm_multi),
            "max_per_osm": max((len(v) for v in osm_multi.values()), default=0),
        },
    }

    # ------------------------------------------------------------------
    # 3. Cross-predicate consistency (reuses KDTree results from above)
    # ------------------------------------------------------------------
    cross_predicate = {
        "consistent_with_nearest": consistent_count,
        "would_differ_by_nearest": not_closest_count,
        "total_evaluated": total_evaluated,
        "consistency_percent": consistency_pct,
    }

    # ------------------------------------------------------------------
    # 4. OSM group stats
    # ------------------------------------------------------------------
    matched_osm_ids = set()
    for rec in matched_records:
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if osm_id:
            matched_osm_ids.add(str(osm_id))

    total_groups = len(osm_groups)
    by_type: Dict[str, int] = defaultdict(int)
    both_matched = 0
    neither_matched = 0

    for n1, n2, group_type in osm_groups:
        by_type[group_type] += 1
        m1 = str(n1) in matched_osm_ids
        m2 = str(n2) in matched_osm_ids
        if m1 or m2:
            both_matched += 1
        else:
            neither_matched += 1

    osm_group_stats = {
        "total_groups": total_groups,
        "by_type": dict(by_type),
        "both_members_matched": both_matched,
        "neither_matched": neither_matched,
    }

    logger.info(
        f"Quality metrics: consistency={consistency_pct}%, "
        f"not_closest={not_closest_count}, many_to_one_atlas={len(atlas_multi)}, "
        f"osm_groups={total_groups}"
    )

    return {
        "distance_quality": distance_quality,
        "many_to_one": many_to_one,
        "cross_predicate_consistency": cross_predicate,
        "osm_groups": osm_group_stats,
    }


def save_stats_to_file(stats: Dict[str, Any], filepath: str = None) -> str:
    """
    Save statistics to JSON file.
    
    Args:
        stats: Statistics dictionary to save
        filepath: Optional custom filepath (defaults to data/stats.json)
    
    Returns:
        Path where stats were saved
    """
    if filepath is None:
        filepath = STATS_FILE_PATH
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    return filepath


def load_stats_from_file(filepath: str = None) -> Optional[Dict[str, Any]]:
    """
    Load statistics from JSON file.
    
    Args:
        filepath: Optional custom filepath (defaults to data/stats.json)
    
    Returns:
        Statistics dictionary or None if file doesn't exist
    """
    if filepath is None:
        filepath = STATS_FILE_PATH
    
    if not os.path.exists(filepath):
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_pipeline_stats() -> Optional[Dict[str, Any]]:
    """
    Get the most recent pipeline statistics.
    
    This is a convenience function for use in documentation rendering.
    
    Returns:
        Statistics dictionary or None if not available
    """
    return load_stats_from_file()
