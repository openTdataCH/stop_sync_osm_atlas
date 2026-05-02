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
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from backend.services.time_utils import get_zurich_now, format_zurich_timestamp
 
logger = logging.getLogger(__name__)


STATS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'stats.json'
)

STATS_SUMMARY_PDF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'documentation', 'generated', 'stats_summary.pdf'
)
 
DATA_META_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'data_meta.json'
)


def get_report_css_content(css_files: List[str]) -> str:
    """Load and concatenate CSS files relative to repository root."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    css_content = ""
    for css_file in css_files:
        try:
            with open(os.path.join(base_dir, css_file), 'r', encoding='utf-8') as f:
                css_content += f.read() + "\n"
        except Exception as e:
            logger.warning(f"Could not load CSS file {css_file} for PDF generation: {e}")
    return css_content


def _compute_no_nearby_atlas_count(
    matched_records: list,
    unmatched_atlas: list,
    unmatched_osm: list,
    radius_m: float = 50.0,
) -> int:
    """Count unmatched OSM nodes with no ATLAS node within *radius_m* metres.

    Builds a temporary KDTree of all ATLAS positions (matched + unmatched)
    and queries each unmatched OSM node against it.
    """
    try:
        from scipy.spatial import KDTree
        from matching_and_import_db.utils.spatial_index import batch_to_xyz, to_xyz
    except Exception:
        return 0

    atlas_coords = []
    for rec in matched_records:
        a = getattr(rec, 'atlas_node', None)
        if a and getattr(a, 'lat', None) is not None:
            atlas_coords.append((float(a.lat), float(a.lon)))
    for node in unmatched_atlas:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is not None and lon is not None and not (lat == 0.0 and lon == 0.0):
            atlas_coords.append((float(lat), float(lon)))

    if not atlas_coords:
        return len(unmatched_osm)

    atlas_xyz = batch_to_xyz(atlas_coords)
    tree = KDTree(atlas_xyz)

    # Convert radius to unit-sphere chord distance
    chord_r = 2 * math.sin(radius_m / (2 * 6_371_000))

    no_nearby_count = 0
    for node in unmatched_osm:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is None or lon is None:
            no_nearby_count += 1
            continue
        xyz = to_xyz(float(lat), float(lon))
        dist, _ = tree.query(xyz, k=1)
        if dist > chord_r:
            no_nearby_count += 1

    return no_nearby_count


def export_pipeline_stats(
    matched_records: list,
    unmatched_atlas: list,
    unmatched_osm: list,
    duplicate_sloid_map: dict,
    no_nearby_osm_sloids: set,
    osm_stop_units: list | None = None,
    total_atlas_platforms: int = None,
    total_osm_stops: int = None,
    total_osm_nodes: int = None,
    total_osm_stations: int = None,
    total_matched_osm_stops: int = None,
    total_unmatched_osm_stops: int = None,
    atlas_route_stats: Dict[str, int] = None,
    osm_route_stats: Dict[str, int] = None,
    osm_nodes_with_routes: set = None,
    no_nearby_atlas_osm_ids: set = None,
    db_session=None,
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
        osm_stop_units: Canonical OSM stop units (optional, used for stop-level many-to-one)
        total_atlas_platforms: Total ATLAS platforms (optional, calculated if not provided)
        total_osm_stops: Total OSM stop units processed (optional)
        total_osm_nodes: Total raw OSM nodes processed (optional)
        total_osm_stations: Total OSM stations (optional)
        total_matched_osm_stops: Matched OSM stop units (optional)
        total_unmatched_osm_stops: Unmatched OSM stop units (optional)
        db_session: Optional database session for live problem statistics
    
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

    matched_osm_stop_count = total_matched_osm_stops
    if matched_osm_stop_count is None:
        matched_osm_stop_count = len({
            str(getattr(getattr(r, 'osm_node', None), 'node_id', ''))
            for r in matched_records
            if getattr(getattr(r, 'osm_node', None), 'node_id', None)
        })

    unmatched_osm_stop_count = total_unmatched_osm_stops
    if unmatched_osm_stop_count is None:
        if total_osm_stops is not None:
            unmatched_osm_stop_count = max(0, total_osm_stops - matched_osm_stop_count)
        else:
            unmatched_osm_stop_count = total_unmatched_osm

    # OSM node counts
    total_osm_nodes_count = total_osm_nodes
    if total_osm_nodes_count is None:
        # Fallback to sum of lengths if not provided
        total_osm_nodes_count = total_matched + total_unmatched_osm
    
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
    distance_stage0 = match_type_counts.get('distance_matching_trio', 0)
    distance_stage1 = sum(
        v for k, v in match_type_counts.items() 
        if k.startswith('distance_matching_1_')
    )
    distance_stage1_uic_ref = match_type_counts.get('distance_matching_1_uic_ref', 0)
    distance_stage1_uic_name = match_type_counts.get('distance_matching_1_uic_name', 0)
    distance_stage1_name = match_type_counts.get('distance_matching_1_name', 0)
    distance_stage2 = match_type_counts.get('distance_matching_2', 0)
    distance_stage3a_pass1 = match_type_counts.get('distance_matching_3a', 0)
    distance_stage3a_pass2 = match_type_counts.get('distance_matching_3a_second_pass', 0)
    distance_stage3a = distance_stage3a_pass1 + distance_stage3a_pass2
    distance_stage3b = match_type_counts.get('distance_matching_3b', 0)
    total_distance_matches = distance_stage0 + distance_stage1 + distance_stage2 + distance_stage3a + distance_stage3b
    
    # Route matching breakdown
    route_gtfs_matches = sum(
        v for k, v in match_type_counts.items() 
        if k.startswith('route_gtfs') or k.startswith('route_unified_gtfs')
    )
    total_route_matches = route_gtfs_matches
    
    # Compute "no ATLAS within 50m" for unmatched OSM nodes
    if no_nearby_atlas_osm_ids is not None:
        no_nearby_atlas_count = len(no_nearby_atlas_osm_ids)
    else:
        # Compute from scratch using a KDTree of all ATLAS positions
        no_nearby_atlas_count = _compute_no_nearby_atlas_count(
            matched_records, unmatched_atlas, unmatched_osm
        )
    osm_has_nearby_atlas = max(0, len(unmatched_osm) - no_nearby_atlas_count)

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
    atlas_with_osm_within_50m = max(0, total_atlas_platforms - no_nearby_osm_count)
    matched_atlas_with_osm_within_50m_percent = (
        round((distinct_matched_atlas / atlas_with_osm_within_50m * 100), 1)
        if atlas_with_osm_within_50m > 0 else 0
    )
    
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
    osm_stop_units = osm_stop_units or []
    node_to_stop_id: Dict[str, str] = {}
    for stop_idx, stop_unit in enumerate(osm_stop_units):
        for member in getattr(stop_unit, 'members', []) or []:
            node_id = getattr(member, 'node_id', None)
            if node_id:
                node_to_stop_id[str(node_id)] = str(stop_idx)

    atlas_to_osm = defaultdict(set)
    osm_to_atlas = defaultdict(set)
    for record in matched_records:
        sloid = getattr(getattr(record, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(record, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            canonical_osm_stop = node_to_stop_id.get(str(osm_id), f"node:{osm_id}")
            atlas_to_osm[str(sloid)].add(canonical_osm_stop)
            osm_to_atlas[canonical_osm_stop].add(str(sloid))

    atlas_multi = {s for s, ids in atlas_to_osm.items() if len(ids) > 1}
    osm_multi = {n for n, ids in osm_to_atlas.items() if len(ids) > 1}

    for record in matched_records:
        sloid = getattr(getattr(record, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(record, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            canonical_osm_stop = node_to_stop_id.get(str(osm_id), f"node:{osm_id}")
            if str(sloid) in atlas_multi or canonical_osm_stop in osm_multi:
                mt = getattr(record, 'match_type', 'unknown') or 'unknown'
                mto_pairs_by_type[mt] += 1

    route_method_counts = {
        'gtfs_tokens': 0,
        'direction_name': 0,
        'other': 0,
    }
    for record in matched_records:
        mt = getattr(record, 'match_type', '') or ''
        if not mt.startswith('route_'):
            continue
        evidence = (getattr(record, 'notes', '') or '').strip()
        if evidence == 'gtfs_tokens':
            route_method_counts['gtfs_tokens'] += 1
        elif evidence == 'direction_name':
            route_method_counts['direction_name'] += 1
        else:
            route_method_counts['other'] += 1

    # Way-based OSM stops analysis
    matched_ways = {
        str(r.osm_node.node_id)
        for r in matched_records
        if getattr(r, 'osm_node', None) and str(r.osm_node.node_id).startswith('way_')
    }
    unmatched_ways = {
        str(n.node_id)
        for n in unmatched_osm
        if str(n.node_id).startswith('way_')
    }
    total_way_stops = len(matched_ways | unmatched_ways)
    way_match_rate = (len(matched_ways) / total_way_stops * 100) if total_way_stops > 0 else 0
    osm_way_stops = {
        "total": total_way_stops,
        "matched": len(matched_ways),
        "unmatched": len(unmatched_ways),
        "match_rate_percent": round(way_match_rate, 1)
    }

    
    # Load data meta if available to get the actual data source update time
    data_updated_at = None
    if os.path.exists(DATA_META_PATH):
        try:
            with open(DATA_META_PATH, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                data_updated_at = meta.get('data_updated_at')
        except Exception as e:
            logger.warning(f"Could not load data_meta.json: {e}")
 
    zurich_now = get_zurich_now()
    stats_computed_at = format_zurich_timestamp(zurich_now)
 
    # Build the stats object
    stats = {
        "generated_at": stats_computed_at,
        "stats_computed_at": stats_computed_at,
        "data_updated_at": data_updated_at,
        "version": "1.1",
        
        # High-level summary (for overview)
        "summary": {
            "atlas_platforms": total_atlas_platforms,
            "osm_stops": total_osm_stops if total_osm_stops is not None else (total_matched + total_unmatched_osm),
            "osm_nodes": total_osm_nodes_count,
            "osm_stations": total_osm_stations if total_osm_stations is not None else 0,
            "matched_osm_stops": matched_osm_stop_count,
            "matched_pairs": total_matched,
            "distinct_matched_atlas": distinct_matched_atlas,
            "match_rate_percent": round(match_rate, 1),
            "unmatched_atlas": total_unmatched_atlas,
            "unmatched_osm": unmatched_osm_stop_count,
            # Nearby OSM coverage (ATLAS with at least one OSM within 50m)
            "atlas_with_osm_within_50m": atlas_with_osm_within_50m,
            "atlas_with_osm_within_50m_percent": round((atlas_with_osm_within_50m / total_atlas_platforms * 100), 1) if total_atlas_platforms > 0 else 0,
            "matched_atlas_with_osm_within_50m_percent": matched_atlas_with_osm_within_50m_percent,
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
                    "stage0_trio": distance_stage0,
                    "stage0_trio_mto": mto_pairs_by_type.get('distance_matching_trio', 0),
                    "stage1_group": distance_stage1,
                    "stage1_group_mto": sum(v for k, v in mto_pairs_by_type.items() if k.startswith('distance_matching_1_')),
                    "stage1_group_by_key": {
                        "uic_ref": {
                            "count": distance_stage1_uic_ref,
                            "mto": mto_pairs_by_type.get('distance_matching_1_uic_ref', 0),
                        },
                        "uic_name": {
                            "count": distance_stage1_uic_name,
                            "mto": mto_pairs_by_type.get('distance_matching_1_uic_name', 0),
                        },
                        "name": {
                            "count": distance_stage1_name,
                            "mto": mto_pairs_by_type.get('distance_matching_1_name', 0),
                        },
                    },
                    "stage2_local_ref": distance_stage2,
                    "stage2_local_ref_mto": mto_pairs_by_type.get('distance_matching_2', 0),
                    "stage3a_single": distance_stage3a,
                    "stage3a_single_mto": mto_pairs_by_type.get('distance_matching_3a', 0) + mto_pairs_by_type.get('distance_matching_3a_second_pass', 0),
                    "stage3a_single_pass1": distance_stage3a_pass1,
                    "stage3a_single_pass1_mto": mto_pairs_by_type.get('distance_matching_3a', 0),
                    "stage3a_single_pass2": distance_stage3a_pass2,
                    "stage3a_single_pass2_mto": mto_pairs_by_type.get('distance_matching_3a_second_pass', 0),
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
                "no_atlas_within_50m": no_nearby_atlas_count,
                "has_nearby_atlas": osm_has_nearby_atlas,
                "matrix": unmatched_osm_matrix,
            }
        },
        
        # Duplicate information
        "duplicates": {
            "total_duplicate_sloids": total_duplicate_sloids,
            "matched_duplicates": matched_duplicate_items,
            "unmatched_duplicates": unmatched_duplicate_items,
        },
        
        # Non-node OSM stops (Ways)
        "osm_way_stops": osm_way_stops,
        
        # Raw match type counts for debugging/advanced use
        "match_type_counts": match_type_counts,

        # Route matching details for analytics table
        "route_matching": {
            "total": total_route_matches,
            "by_source": {
                "gtfs": route_gtfs_matches,
            },
            "by_method": {
                "gtfs_tokens": route_method_counts['gtfs_tokens'],
                "direction_name_fallback": route_method_counts['direction_name'],
                "other_or_legacy": route_method_counts['other'],
            },
        },
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
                stats['routes']['atlas_with_routes_percent'] = round((any_route / total_atlas_platforms * 100), 1)
                stats['routes']['gtfs_coverage_percent'] = round((gtfs_matches / total_atlas_platforms * 100), 1)
                
        if osm_route_stats:
            stats['routes'].update(osm_route_stats)
            if total_osm_stops and total_osm_stops > 0:
                osm_with_routes = osm_route_stats.get('osm_with_routes', 0)
                stats['routes']['osm_with_routes_percent'] = round((osm_with_routes / total_osm_stops * 100), 1)

    # Load GTFS mapping stats if available
    gtfs_mapping_stats_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'data', 'gtfs_mapping_stats.json'
    )
    if os.path.exists(gtfs_mapping_stats_path):
        try:
            with open(gtfs_mapping_stats_path, 'r', encoding='utf-8') as f:
                stats['gtfs_mapping'] = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load gtfs_mapping_stats.json: {e}")

    if db_session:
        # Reuse existing compute_db_stats helper
        stats['problems'] = compute_db_stats(db_session)
        stats['route_problems'] = compute_route_problem_stats(db_session)

    return stats


def _classify_match_type(match_type: str) -> str:
    """Map a raw match_type string to a display stage name."""
    if match_type == 'exact':
        return 'exact'
    if match_type == 'name':
        return 'name'
    if match_type == 'distance_matching_trio':
        return 'distance_trio'
    if match_type == 'distance_matching_1_uic_ref':
        return 'distance_stage1_uic_ref'
    if match_type == 'distance_matching_1_uic_name':
        return 'distance_stage1_uic_name'
    if match_type == 'distance_matching_1_name':
        return 'distance_stage1_name'
    if match_type.startswith('distance_matching_1_'):
        return 'distance_stage1'
    if match_type == 'distance_matching_2':
        return 'distance_stage2'
    if match_type == 'distance_matching_3a':
        return 'distance_stage3a_pass1'
    if match_type == 'distance_matching_3a_second_pass':
        return 'distance_stage3a_pass2'
    if match_type == 'distance_matching_3b':
        return 'distance_stage3b'
    if 'gtfs' in match_type:
        return 'route_gtfs'
    if match_type.startswith('route_'):
        return 'route_gtfs'
    if match_type == 'exact_postpass':
        return 'post_unique_by_uic'
    if match_type == 'duplicate_propagation':
        return 'post_duplicate_propagation'
    if match_type == 'osm_group_propagation':
        return 'post_osm_group_propagation'
    return 'other'


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
    osm_stop_units: list | None = None,
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
    not_closest_by_stage: Dict[str, int] = {}

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
            
            stage = _classify_match_type(getattr(rec, 'match_type', '') or '')

            total_evaluated += 1
            if nearest_osm_id == matched_osm_id:
                consistent_count += 1
            else:
                not_closest_count += 1
                not_closest_by_stage[stage] = not_closest_by_stage.get(stage, 0) + 1

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
        "not_matched_to_closest_by_stage": not_closest_by_stage,
    }

    # ------------------------------------------------------------------
    # 2. Many-to-one analysis
    # ------------------------------------------------------------------
    node_to_stop_id: Dict[str, str] = {}
    for stop_idx, stop_unit in enumerate(osm_stop_units):
        for member in getattr(stop_unit, 'members', []) or []:
            node_id = getattr(member, 'node_id', None)
            if node_id:
                node_to_stop_id[str(node_id)] = str(stop_idx)

    atlas_to_osm: Dict[str, set] = defaultdict(set)
    osm_to_atlas: Dict[str, set] = defaultdict(set)

    for rec in matched_records:
        sloid = getattr(getattr(rec, 'atlas_node', None), 'sloid', None)
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            canonical_osm_stop = node_to_stop_id.get(str(osm_id), f"node:{osm_id}")
            atlas_to_osm[str(sloid)].add(canonical_osm_stop)
            osm_to_atlas[canonical_osm_stop].add(str(sloid))

    atlas_multi = {s: ids for s, ids in atlas_to_osm.items() if len(ids) > 1}
    osm_multi = {n: ids for n, ids in osm_to_atlas.items() if len(ids) > 1}

    # Calculate distributions for many-to-one matches
    atlas_dist_counts = defaultdict(int)
    for ids in atlas_multi.values():
        atlas_dist_counts[len(ids)] += 1
    atlas_distribution = [
        {"ratio": f"1A:{n}O", "count": count}
        for n, count in sorted(atlas_dist_counts.items())
    ]

    osm_dist_counts = defaultdict(int)
    for ids in osm_multi.values():
        osm_dist_counts[len(ids)] += 1
    osm_distribution = [
        {"ratio": f"{n}A:1O", "count": count}
        for n, count in sorted(osm_dist_counts.items())
    ]

    many_to_one = {
        "atlas_to_multiple_osm": {
            "count": len(atlas_multi),
            "max_per_atlas": max((len(v) for v in atlas_multi.values()), default=0),
            "distribution": atlas_distribution,
        },
        "osm_to_multiple_atlas": {
            "count": len(osm_multi),
            "max_per_osm": max((len(v) for v in osm_multi.values()), default=0),
            "distribution": osm_distribution,
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
    # 4. OSM stop-unit grouping stats
    # ------------------------------------------------------------------
    osm_stop_units = osm_stop_units or []

    matched_osm_ids = set()
    for rec in matched_records:
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if osm_id:
            matched_osm_ids.add(str(osm_id))

    grouped_units = [u for u in osm_stop_units if getattr(u, 'stop_kind', 'single') in ('pair', 'trio')]
    total_groups = len(grouped_units)
    by_type: Dict[str, int] = defaultdict(int)
    both_matched = 0
    neither_matched = 0

    for stop_unit in grouped_units:
        group_key = getattr(stop_unit, 'group_kind', None) or getattr(stop_unit, 'stop_kind', 'unknown')
        by_type[group_key] += 1
        member_ids = [str(member.node_id) for member in getattr(stop_unit, 'members', [])]
        if any(member_id in matched_osm_ids for member_id in member_ids):
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


def compute_db_stats(db_session) -> Dict[str, Any]:
    """Compute problem statistics by querying the database after import.

    Args:
        db_session: SQLAlchemy session connected to import_db.

    Returns:
        Dictionary with problem totals, by-type counts, by-priority breakdown,
        and clean/dirty entry counts.
    """
    from backend.models import StopsMatched, Problem
    from sqlalchemy import func

    total_stops = db_session.query(StopsMatched).count()

    type_counts = dict(
        db_session.query(Problem.problem_type, func.count(Problem.id))
        .group_by(Problem.problem_type).all()
    )

    multiple_problems = (
        db_session.query(Problem.stop_id)
        .group_by(Problem.stop_id)
        .having(func.count(Problem.stop_id) > 1)
        .count()
    )
    stops_with_problems = (
        db_session.query(func.count(func.distinct(Problem.stop_id))).scalar() or 0
    )

    # Priority × type breakdown
    by_priority: Dict[int, Dict[str, int]] = {}
    rows = (
        db_session.query(Problem.priority, Problem.problem_type, func.count(Problem.id))
        .group_by(Problem.priority, Problem.problem_type).all()
    )
    for priority, ptype, cnt in rows:
        by_priority.setdefault(priority, {})[ptype] = cnt

    return {
        'total_stops': total_stops,
        'distance': type_counts.get('distance', 0),
        'unmatched': type_counts.get('unmatched', 0),
        'attributes': type_counts.get('attributes', 0),
        'duplicates': type_counts.get('duplicates', 0),
        'multiple_problems': multiple_problems,
        'stops_with_problems': stops_with_problems,
        'clean_entries': max(0, total_stops - stops_with_problems),
        'by_priority': by_priority,
    }

def compute_route_problem_stats(db_session) -> Dict[str, Any]:
    """Compute route problem statistics by querying the database after import."""
    from backend.models import RoutesMatched, RouteProblem
    from sqlalchemy import func

    total_routes_matched = db_session.query(RoutesMatched).count()

    type_counts = dict(
        db_session.query(RouteProblem.problem_type, func.count(RouteProblem.id))
        .group_by(RouteProblem.problem_type).all()
    )

    # Priority × type breakdown
    by_priority: Dict[int, Dict[str, int]] = {}
    rows = (
        db_session.query(RouteProblem.priority, RouteProblem.problem_type, func.count(RouteProblem.id))
        .group_by(RouteProblem.priority, RouteProblem.problem_type).all()
    )
    for priority, ptype, cnt in rows:
        by_priority.setdefault(priority, {})[ptype] = cnt
        
    total_problems = db_session.query(RouteProblem).count()

    return {
        'total_routes_matched': total_routes_matched,
        'total_problems': total_problems,
        'by_type': type_counts,
        'by_priority': by_priority,
    }



def compute_route_route_stats(db_session) -> Dict[str, Any]:
    """Compute route-route linking statistics from route tables in the import DB."""
    from backend.models import RouteAtlasStops, RouteOsmStops, RoutesMatched

    total_links = db_session.query(RoutesMatched).count()

    atlas_routes_linked = (
        db_session.query(RoutesMatched.atlas_route_id)
        .filter(RoutesMatched.atlas_route_id.isnot(None))
        .distinct()
        .count()
    )
    osm_routes_linked = (
        db_session.query(RoutesMatched.osm_route_id)
        .filter(RoutesMatched.osm_route_id.isnot(None))
        .distinct()
        .count()
    )

    atlas_route_ids_total = (
        db_session.query(RouteAtlasStops.atlas_route_id)
        .filter(RouteAtlasStops.atlas_route_id.isnot(None))
        .distinct()
        .count()
    )
    osm_route_ids_total = (
        db_session.query(RouteOsmStops.osm_route_id)
        .filter(RouteOsmStops.osm_route_id.isnot(None))
        .distinct()
        .count()
    )

    atlas_route_directions_total = (
        db_session.query(RouteAtlasStops.atlas_route_id, RouteAtlasStops.direction_id)
        .distinct()
        .count()
    )
    osm_route_directions_total = (
        db_session.query(RouteOsmStops.osm_route_id, RouteOsmStops.direction_id)
        .distinct()
        .count()
    )

    atlas_routes_without_link = max(atlas_route_ids_total - atlas_routes_linked, 0)
    osm_routes_without_link = max(osm_route_ids_total - osm_routes_linked, 0)

    atlas_link_coverage_percent = (
        round((atlas_routes_linked / atlas_route_ids_total) * 100, 1)
        if atlas_route_ids_total > 0 else 0.0
    )
    osm_link_coverage_percent = (
        round((osm_routes_linked / osm_route_ids_total) * 100, 1)
        if osm_route_ids_total > 0 else 0.0
    )

    return {
        'total_links': total_links,
        'atlas_routes_linked': atlas_routes_linked,
        'osm_routes_linked': osm_routes_linked,
        'atlas_route_ids_total': atlas_route_ids_total,
        'osm_route_ids_total': osm_route_ids_total,
        'atlas_route_directions_total': atlas_route_directions_total,
        'osm_route_directions_total': osm_route_directions_total,
        'atlas_routes_without_link': atlas_routes_without_link,
        'osm_routes_without_link': osm_routes_without_link,
        'atlas_link_coverage_percent': atlas_link_coverage_percent,
        'osm_link_coverage_percent': osm_link_coverage_percent,
    }


def compute_summary_from_db(db_session) -> Dict[str, Any]:
    """Compute summary stats directly from source tables.

    This path remains exact and does not depend on bucket-table additive assumptions.
    """
    from backend.models import StopsMatched, OsmStop, OsmNode, OsmStopMember
    from sqlalchemy import func

    atlas_platforms = db_session.query(
        func.count(func.distinct(StopsMatched.sloid))
    ).filter(StopsMatched.sloid.isnot(None)).scalar() or 0

    total_osm_stops = db_session.query(func.count(OsmStop.id)).scalar() or 0
    total_osm_nodes = db_session.query(func.count(OsmNode.osm_node_id)).scalar() or 0
    osm_stations = db_session.query(func.count(OsmNode.osm_node_id)).filter(
        (OsmNode.osm_public_transport == 'station') | (OsmNode.osm_railway == 'station')
    ).scalar() or 0

    matched_type_condition = StopsMatched.stop_type.in_(['matched', 'effectively_matched'])
    matched_pairs = db_session.query(func.count(StopsMatched.id)).filter(
        matched_type_condition
    ).scalar() or 0
    distinct_matched_atlas = db_session.query(
        func.count(func.distinct(StopsMatched.sloid))
    ).filter(matched_type_condition).scalar() or 0

    matched_osm_stops = db_session.query(
        func.count(func.distinct(OsmStopMember.osm_stop_id))
    ).join(
        StopsMatched,
        OsmStopMember.node_id == StopsMatched.osm_node_id,
    ).filter(
        matched_type_condition
    ).scalar() or 0

    unmatched_atlas = db_session.query(func.count(StopsMatched.id)).filter(
        StopsMatched.stop_type == 'atlas_unmatched'
    ).scalar() or 0
    unmatched_osm_stops = max(0, total_osm_stops - matched_osm_stops)

    no_nearby_osm_count = db_session.query(func.count(StopsMatched.id)).filter(
        StopsMatched.stop_type == 'atlas_unmatched',
        StopsMatched.match_type == 'no_nearby_counterpart'
    ).scalar() or 0

    atlas_with_osm_within_50m = max(0, atlas_platforms - no_nearby_osm_count)
    matched_atlas_with_osm_within_50m_percent = (
        round((distinct_matched_atlas / atlas_with_osm_within_50m * 100), 1)
        if atlas_with_osm_within_50m > 0 else 0
    )

    return {
        "atlas_platforms": atlas_platforms,
        "osm_stops": total_osm_stops,
        "osm_nodes": total_osm_nodes,
        "osm_stations": osm_stations,
        "matched_osm_stops": matched_osm_stops,
        "matched_pairs": matched_pairs,
        "distinct_matched_atlas": distinct_matched_atlas,
        "match_rate_percent": round((distinct_matched_atlas / atlas_platforms * 100), 1) if atlas_platforms > 0 else 0,
        "unmatched_atlas": unmatched_atlas,
        "unmatched_osm": unmatched_osm_stops,
        "atlas_with_osm_within_50m": atlas_with_osm_within_50m,
        "atlas_with_osm_within_50m_percent": round((atlas_with_osm_within_50m / atlas_platforms * 100), 1) if atlas_platforms > 0 else 0,
        "matched_atlas_with_osm_within_50m_percent": matched_atlas_with_osm_within_50m_percent,
    }


def get_pipeline_stats() -> Optional[Dict[str, Any]]:
    """
    Get the most recent pipeline statistics.
    
    This is a convenience function for use in documentation rendering.
    
    Returns:
        Statistics dictionary or None if not available
    """
    return load_stats_from_file()


def ensure_stats_summary_pdf_generated(force: bool = False, max_age_seconds: Optional[int] = None) -> str:
    """Ensure the stats summary PDF exists and is up to date with stats.json.

    Must be called inside a Flask app context.
    """
    stats = load_stats_from_file()
    if not stats:
        raise RuntimeError("Statistics file does not exist yet. Run a pipeline import first.")

    output_path = STATS_SUMMARY_PDF_PATH
    stats_mtime = os.path.getmtime(STATS_FILE_PATH) if os.path.exists(STATS_FILE_PATH) else None

    is_fresh = os.path.exists(output_path)
    if is_fresh and stats_mtime is not None:
        is_fresh = os.path.getmtime(output_path) >= stats_mtime

    if is_fresh and max_age_seconds is not None:
        is_fresh = (time.time() - os.path.getmtime(output_path)) <= max_age_seconds

    if force or not is_fresh:
        generate_stats_summary_pdf(stats, output_path=output_path)

    return output_path


def generate_stats_summary_pdf(stats: Dict[str, Any], output_path: str = None) -> str:
    """
    Generate a PDF summary report from the stats and save it.
    
    This function should be called within a Flask application context.
    
    Args:
        stats: Statistics dictionary
        output_path: Optional custom path (defaults to documentation/generated/stats_summary.pdf)
        
    Returns:
        Path where PDF was saved
    """
    if output_path is None:
        output_path = STATS_SUMMARY_PDF_PATH
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Import PDF/web rendering dependencies lazily so pipeline-only environments
    # (e.g. scheduler image) can still import this module.
    from flask import render_template
    try:
        from weasyprint import HTML
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "WeasyPrint is required for PDF export. Install web dependencies to generate reports."
        ) from exc
    
    from backend.extensions import db
    problem_stats = compute_db_stats(db.session)
    route_problem_stats = compute_route_problem_stats(db.session)
    
    kwargs = {
        'stats': stats,
        'problem_breakdown': problem_stats.get('by_priority', {}),
        'route_problem_breakdown': route_problem_stats.get('by_priority', {}),
        'probs': problem_stats,
        'route_probs': route_problem_stats,
        'generated_at': datetime.now(),
        'css_content': '',
        'pdf_assets_prefix': 'static/vendor/'
    }
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    core_css_files = [
        'static/css/src/01-settings/tokens.css',
        'static/css/pages/stats.css',
        'static/css/pages/reports.css'
    ]
    kwargs['css_content'] = get_report_css_content(core_css_files)
    
    report_html = render_template('reports/stats_summary.html', **kwargs)
    
    # Render PDF using WeasyPrint
    HTML(string=report_html, base_url=base_dir).write_pdf(output_path)
    
    return output_path
