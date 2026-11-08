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
import os
import tempfile
import time
from collections import defaultdict
from typing import Dict, Any, List, Optional

from backend.services.data_meta import load_data_meta
from backend.services.matching_rules import MATCHING_RULES, PROPAGATION_MATCH_TYPES
from backend.services.time_utils import (
    format_zurich_timestamp,
    get_zurich_now,
)
 
logger = logging.getLogger(__name__)


STATS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'stats.json'
)

STATS_SUMMARY_PDF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'documentation', 'generated', 'stats_summary.pdf'
)
 
GTFS_ATLAS_STATS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'gtfs_atlas_stats.json'
)


def _load_gtfs_atlas_stats(total_atlas_platforms: int | None = None) -> Optional[Dict[str, Any]]:
    """Load canonical GTFS-to-ATLAS stats from the GTFS sidecar."""
    if not os.path.exists(GTFS_ATLAS_STATS_PATH):
        return None

    try:
        with open(GTFS_ATLAS_STATS_PATH, 'r', encoding='utf-8') as f:
            stats = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load gtfs_atlas_stats.json: {e}")
        return None

    if total_atlas_platforms and stats.get('atlas', {}).get('total') in (None, 0):
        stats.setdefault('atlas', {})['total'] = total_atlas_platforms
        touched = int(stats['atlas'].get('resolved_by_gtfs') or 0)
        stats['atlas']['coverage_percent'] = round((touched / total_atlas_platforms) * 100, 1) if total_atlas_platforms > 0 else 0.0

    return stats


def _build_source_download_stats(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not meta:
        return None

    if 'acquisition' in meta:
        acquisition = meta.get('acquisition') or {}
        if not isinstance(acquisition, dict):
            return None
        preprocessing_sources = acquisition.get('sources') or {}
    else:
        preprocessing_sources = meta.get('preprocessing_sources') or {}
    if not isinstance(preprocessing_sources, dict):
        return None

    source_downloads: Dict[str, Any] = {}

    for source_name in ('atlas', 'gtfs'):
        snapshot = preprocessing_sources.get(source_name) or {}
        if not isinstance(snapshot, dict):
            continue

        # Keep timezone and seconds until presentation. Checking or preprocessing
        # cached files is not a download and must not manufacture a timestamp.
        downloaded_at = snapshot.get(f'{source_name}_downloaded_at') or snapshot.get('downloaded_at')
        source_download = {
            'downloaded_at': downloaded_at,
            f'{source_name}_downloaded_at': downloaded_at,
            'etag': snapshot.get('etag'),
            'last_modified': snapshot.get('last_modified'),
            'download_filename': snapshot.get('download_filename'),
            'final_url': snapshot.get('final_url'),
        }

        if any(value is not None for value in source_download.values()):
            source_downloads[source_name] = source_download

    return source_downloads or None


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


def _matching_rule_stats(match_type_counts: Dict[str, int], mto_pairs_by_type: Dict[str, int]) -> List[Dict[str, Any]]:
    """Count matches per rule and per match type, in rule order."""
    rules = []
    for rule in MATCHING_RULES:
        match_types = [
            {"match_type": match_type, "label": label,
             "count": match_type_counts.get(match_type, 0), "mto": mto_pairs_by_type.get(match_type, 0)}
            for match_type, label in rule.match_types
        ]
        rules.append({
            "rule": rule.key, "label": rule.label, "group": rule.group,
            "count": sum(row["count"] for row in match_types),
            "mto": sum(row["mto"] for row in match_types),
            "match_types": match_types,
        })
    return rules


def export_pipeline_stats(
    matched_records: list,
    unmatched_atlas: list,
    unmatched_osm: list,
    no_nearby_osm_sloids: set,
    osm_stop_units: list | None = None,
    total_atlas_platforms: int = None,
    total_osm_stops: int = None,
    total_osm_nodes: int = None,
    total_osm_stations: int = None,
    total_matched_osm_stops: int = None,
    total_unmatched_osm_stops: int = None,
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
        unmatched_osm: Unmatched OSM elements, without effectively matched two-sided stop middles
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
    
    # Compute "no ATLAS within 50m" for unmatched OSM nodes
    if no_nearby_atlas_osm_ids is not None:
        no_nearby_atlas_count = len(no_nearby_atlas_osm_ids)
    else:
        # Legacy callers without a bundle do not supply this optional metric.
        no_nearby_atlas_count = 0
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

    # Load data meta if available to get the actual data source update time
    last_pipeline_data_import_ended_at = None
    last_overpass_query_at = None
    osm_data_at = None
    source_downloads = None
    meta = {}
    try:
        meta = load_data_meta()
        last_pipeline_data_import_ended_at = meta.get('last_pipeline_data_import_ended_at') or meta.get('data_updated_at')
        last_overpass_query_at = meta.get('last_overpass_query_at')
        osm_data_at = meta.get('osm_data_at')
        source_downloads = _build_source_download_stats(meta)
    except Exception as e:
        logger.warning(f"Could not load data_meta.json: {e}")
 
    zurich_now = get_zurich_now()
    stats_computed_at = format_zurich_timestamp(zurich_now)
 
    # Build the stats object
    stats = {
        "active_run_id": meta.get('active_run_id'),
        "generated_at": stats_computed_at,
        "stats_computed_at": stats_computed_at,
        "last_pipeline_data_import_ended_at": last_pipeline_data_import_ended_at,
        "last_overpass_query_at": last_overpass_query_at,
        "osm_data_at": osm_data_at,
        "source_downloads": source_downloads,
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
        
        # Matches per rule, in run order, with the match types each rule writes
        "matching_rules": _matching_rule_stats(match_type_counts, mto_pairs_by_type),
        "propagation": [
            {"match_type": match_type, "label": label,
             "count": match_type_counts.get(match_type, 0), "mto": mto_pairs_by_type.get(match_type, 0)}
            for match_type, label in PROPAGATION_MATCH_TYPES
        ],

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
        
        # Raw match type counts for debugging/advanced use
        "match_type_counts": match_type_counts,
    }
    
    gtfs_atlas_stats = _load_gtfs_atlas_stats(total_atlas_platforms)
    if gtfs_atlas_stats:
        stats['gtfs_atlas'] = gtfs_atlas_stats

    if db_session:
        # Reuse existing compute_db_stats helper
        stats['problems'] = compute_db_stats(db_session)

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
    
    parent = os.path.dirname(filepath) or "."
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        temp_path = f.name
    os.replace(temp_path, filepath)
    
    return filepath


def refresh_stats_metadata(meta: Optional[Dict[str, Any]] = None, filepath: str = None) -> bool:
    """Update freshness after completion without regenerating database analytics."""
    meta = load_data_meta() if meta is None else meta
    stats = load_stats_from_file(filepath)
    if not isinstance(stats, dict):
        return False
    if meta.get('active_run_id') and stats.get('active_run_id') != meta['active_run_id']:
        return False
    stats.update(
        last_pipeline_data_import_ended_at=meta.get('last_pipeline_data_import_ended_at') or meta.get('data_updated_at'),
        last_overpass_query_at=meta.get('last_overpass_query_at'),
        osm_data_at=meta.get('osm_data_at'),
        source_downloads=_build_source_download_stats(meta),
    )
    save_stats_to_file(stats, filepath)
    return True


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
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load stats file %s: %s", filepath, exc)
        return None

    return payload if isinstance(payload, dict) else None


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

    total_stops = db_session.query(func.count(StopsMatched.id)).scalar() or 0

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
        'contradicts_route_matching': type_counts.get('contradicts_route_matching', 0),
        'duplicates': type_counts.get('duplicates', 0),
        'disused': type_counts.get('disused', 0),
        'identifier': type_counts.get('identifier', 0),
        'multiple_problems': multiple_problems,
        'stops_with_problems': stops_with_problems,
        'clean_entries': max(0, total_stops - stops_with_problems),
        'by_priority': by_priority,
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
    # Disused OSM elements are not stops; they have no stop unit either.
    active_osm_node = OsmNode.osm_lifecycle.is_(None)
    total_osm_nodes = db_session.query(func.count(OsmNode.osm_node_id)).filter(active_osm_node).scalar() or 0
    osm_stations = db_session.query(func.count(OsmNode.osm_node_id)).filter(
        active_osm_node, (OsmNode.osm_public_transport == 'station') | (OsmNode.osm_railway == 'station')
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


def ensure_stats_summary_pdf_generated(max_age_seconds: Optional[int] = None) -> str:
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

    if not is_fresh:
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
    
    problem_stats = stats.get('problems') if isinstance(stats, dict) else None
    if not problem_stats:
        from backend.extensions import db
        problem_stats = compute_db_stats(db.session)
    
    kwargs = {
        'stats': stats,
        'problem_breakdown': problem_stats.get('by_priority', {}),
        'probs': problem_stats,
        'generated_at': get_zurich_now(),
        'css_content': '',
        'pdf_assets_prefix': 'static/vendor/',
        'pdf_static_prefix': 'static/',
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
