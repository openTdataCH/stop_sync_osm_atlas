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
import os
from datetime import datetime
from typing import Dict, Any, Optional


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
    
    # Unmatched OSM analysis
    unmatched_osm_with_routes = 0
    unmatched_osm_with_uic_ref = 0
    unmatched_osm_with_local_ref = 0
    
    for node in unmatched_osm:
        tags = getattr(node, 'tags', None) or {}
        if 'uic_ref' in tags:
            unmatched_osm_with_uic_ref += 1
        if getattr(node, 'local_ref', None) or tags.get('local_ref'):
            unmatched_osm_with_local_ref += 1
        # Note: Route membership would need to be checked against osm_nodes_with_routes.csv
        # This is handled separately in the pipeline
    
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
                "description": "UIC reference number equality"
            },
            "name": {
                "count": name_matches,
                "description": "Official name string matching"
            },
            "distance": {
                "count": total_distance_matches,
                "description": "Proximity-based spatial matching (≤50m)",
                "breakdown": {
                    "stage1_group": distance_stage1,
                    "stage2_local_ref": distance_stage2,
                    "stage3a_single": distance_stage3a,
                    "stage3b_relative": distance_stage3b,
                }
            },
            "route": {
                "count": total_route_matches,
                "description": "Shared transit route validation",
                "breakdown": {
                    "gtfs": route_gtfs_matches,
                    "hrdf": route_hrdf_matches,
                }
            },
            "post_processing": {
                "unique_by_uic": exact_postpass_matches,
                "duplicate_propagation": duplicate_propagation_matches,
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
                "with_uic_ref": unmatched_osm_with_uic_ref,
                "with_local_ref": unmatched_osm_with_local_ref,
                # Routes count will be added by the caller if available
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
                stats['routes']['atlas_with_routes_percent'] = round((any_route / total_atlas_platforms * 100), 1)
                stats['routes']['gtfs_coverage_percent'] = round((gtfs_matches / total_atlas_platforms * 100), 1)
                
        if osm_route_stats:
            stats['routes'].update(osm_route_stats)

    return stats


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
