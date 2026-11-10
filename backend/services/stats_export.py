"""
Statistics export service.

Writes the analytics of the published snapshot to data/stats.json, which the
analytics page, the statistics PDF and the documentation placeholders read.
The summary, the problems and the per-source sections are counted from the
published tables, by the import and by ``scripts/regenerate_stats.py`` alike.
The matches per rule and the unmatched OSM analysis come from the bundle,
which keeps details the tables do not.
"""

import json
import logging
import os
import time
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional

from backend.services.data_meta import load_data_meta
from backend.services.dataset_stats import add_dataset_stats
from backend.services.json_files import write_json_atomic
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

# Unmatched OSM elements by the identifiers they carry: (uic_ref, local_ref, route relation).
_IDENTIFIER_COMBINATIONS = {
    (True, True, True): 'all_three',
    (True, True, False): 'uic_and_local',
    (True, False, True): 'uic_and_routes',
    (False, True, True): 'local_and_routes',
    (True, False, False): 'uic_only',
    (False, True, False): 'local_ref_only',
    (False, False, True): 'routes_only',
    (False, False, False): 'none',
}


def _build_source_download_stats(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """When and from where the published bundle's ATLAS and GTFS files were downloaded."""
    acquisition = meta.get('acquisition')
    sources = acquisition.get('sources') if isinstance(acquisition, dict) else None
    if not isinstance(sources, dict):
        return None

    source_downloads: Dict[str, Any] = {}
    for source_name in ('atlas', 'gtfs'):
        snapshot = sources.get(source_name)
        if not isinstance(snapshot, dict):
            continue
        # Keep timezone and seconds until presentation. Checking or preprocessing
        # cached files is not a download and must not manufacture a timestamp.
        source_download = {key: snapshot.get(key) for key in
                           ('downloaded_at', 'etag', 'last_modified', 'download_filename', 'final_url')}
        if any(value is not None for value in source_download.values()):
            source_downloads[source_name] = source_download

    return source_downloads or None


def _source_freshness(meta: Dict[str, Any]) -> Dict[str, Any]:
    """The dates stats.json copies from data_meta.json: the last import and the source downloads."""
    return {
        'last_pipeline_data_import_ended_at': meta.get('last_pipeline_data_import_ended_at'),
        'last_overpass_query_at': meta.get('last_overpass_query_at'),
        'osm_data_at': meta.get('osm_data_at'),
        'source_downloads': _build_source_download_stats(meta),
    }


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


def _many_to_one_pairs_by_type(matched_records: list, osm_stop_units: list) -> Counter:
    """Matches per match type whose platform or OSM stop unit takes part in more than one match."""
    stop_unit_by_node = {str(member.node_id): index
                         for index, stop_unit in enumerate(osm_stop_units) for member in stop_unit.members}
    pairs = [(str(record.atlas_node.sloid),
              stop_unit_by_node.get(str(record.osm_node.node_id), f"node:{record.osm_node.node_id}"),
              record.match_type)
             for record in matched_records]
    stop_units_by_sloid, sloids_by_stop_unit = defaultdict(set), defaultdict(set)
    for sloid, stop_unit, _ in pairs:
        stop_units_by_sloid[sloid].add(stop_unit)
        sloids_by_stop_unit[stop_unit].add(sloid)
    return Counter(match_type for sloid, stop_unit, match_type in pairs
                   if len(stop_units_by_sloid[sloid]) > 1 or len(sloids_by_stop_unit[stop_unit]) > 1)


def export_pipeline_stats(
    db_session,
    *,
    matched_records: list,
    unmatched_osm: list,
    isolated_osm_ids: set,
    osm_stop_units: list,
    osm_nodes_with_routes: set,
    gtfs_atlas_stats: dict,
) -> Dict[str, Any]:
    """Compute stats.json for the snapshot just published.

    Args:
        db_session: session on the published tables
        matched_records: the bundle's matches
        unmatched_osm: unmatched OSM elements, without effectively matched two-sided stop middles
        isolated_osm_ids: IDs of the OSM elements with no ATLAS platform within 50 m
        osm_stop_units: OSM stop units, to count many-to-one matches per stop unit
        osm_nodes_with_routes: IDs of the OSM elements that belong to a route relation
        gtfs_atlas_stats: the engine's GTFS identity statistics, empty without GTFS
    """
    meta = load_data_meta()
    stats = {"active_run_id": meta.get('active_run_id'), **_source_freshness(meta)}
    recount_from_database(stats, db_session)

    match_type_counts = Counter(record.match_type for record in matched_records)
    mto_pairs_by_type = _many_to_one_pairs_by_type(matched_records, osm_stop_units)

    unmatched_atlas = stats['summary']['unmatched_atlas']
    isolated_atlas = _count_isolated_atlas(db_session)
    isolated_osm = sum(str(node.node_id) in isolated_osm_ids for node in unmatched_osm)
    identifier_matrix = dict.fromkeys(_IDENTIFIER_COMBINATIONS.values(), 0)
    for node in unmatched_osm:
        tags = node.tags or {}
        combination = ('uic_ref' in tags, bool(node.local_ref or tags.get('local_ref')),
                       str(node.node_id) in osm_nodes_with_routes)
        identifier_matrix[_IDENTIFIER_COMBINATIONS[combination]] += 1

    stats.update({
        # Matches per rule, in run order, with the match types each rule writes
        "matching_rules": _matching_rule_stats(match_type_counts, mto_pairs_by_type),
        "propagation": [
            {"match_type": match_type, "label": label,
             "count": match_type_counts.get(match_type, 0), "mto": mto_pairs_by_type.get(match_type, 0)}
            for match_type, label in PROPAGATION_MATCH_TYPES
        ],
        "unmatched_analysis": {
            "atlas": {
                "total": unmatched_atlas,
                "no_osm_within_50m": isolated_atlas,
                "has_nearby_osm": unmatched_atlas - isolated_atlas,
            },
            "osm": {
                "total": len(unmatched_osm),
                "no_atlas_within_50m": isolated_osm,
                "has_nearby_atlas": len(unmatched_osm) - isolated_osm,
                "matrix": identifier_matrix,
            },
        },
    })
    if gtfs_atlas_stats:
        stats['gtfs_atlas'] = gtfs_atlas_stats
    return stats


def recount_from_database(stats: Dict[str, Any], db_session) -> Dict[str, Any]:
    """Recount the sections the published tables hold, and stamp the time.

    These are the summary, the problems and the per-source sections. The
    import and ``scripts/regenerate_stats.py`` both call this, so they
    publish the same numbers.
    """
    stats['summary'] = compute_summary_from_db(db_session)
    stats['problems'] = compute_db_stats(db_session)
    add_dataset_stats(stats, db_session)
    stats['stats_computed_at'] = format_zurich_timestamp(get_zurich_now())
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
    return write_json_atomic(filepath or STATS_FILE_PATH, stats, indent=2, ensure_ascii=False)


def refresh_stats_metadata(meta: Optional[Dict[str, Any]] = None, filepath: str = None) -> bool:
    """Update freshness after completion without regenerating database analytics."""
    meta = load_data_meta() if meta is None else meta
    stats = load_stats_from_file(filepath)
    if not isinstance(stats, dict):
        return False
    if meta.get('active_run_id') and stats.get('active_run_id') != meta['active_run_id']:
        return False
    stats.update(_source_freshness(meta))
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


def _count_isolated_atlas(db_session) -> int:
    """Unmatched ATLAS platforms with no OSM element within 50 m."""
    from backend.models import StopsMatched
    from sqlalchemy import func

    return db_session.query(func.count(StopsMatched.id)).filter(
        StopsMatched.stop_type == 'atlas_unmatched',
        StopsMatched.match_type == 'no_nearby_counterpart'
    ).scalar() or 0


def compute_summary_from_db(db_session) -> Dict[str, Any]:
    """The summary section of stats.json, counted from the published tables.

    A matched pair is a ``matched`` row, or an effectively matched two-sided
    stop middle, as on the map.
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

    atlas_with_osm_within_50m = max(0, atlas_platforms - _count_isolated_atlas(db_session))
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

    # WeasyPrint is slow to load: import it only when a PDF is made, not with
    # every import of this module by the importer and the job runner.
    from flask import render_template
    from weasyprint import HTML

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
