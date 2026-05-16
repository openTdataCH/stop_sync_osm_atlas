"""
Database import orchestrator.

Imports pipeline output (matched / unmatched ATLAS & OSM records) into the
normalized PostGIS schema and runs problem detection.  Route data is loaded
via :mod:`matching_and_import_db.database.route_loader`, helpers come from
:mod:`matching_and_import_db.database.helpers`, and engine / session objects from
:mod:`matching_and_import_db.database.session`.
"""
import math
import os
import time
import argparse
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import text, inspect, insert

# --- Internal modules -------------------------------------------------------
from matching_and_import_db.orchestrator import run_matching
from matching_and_import_db.models import MatchingOutput
from matching_and_import_db.problem_detection.context import ProblemContext
from matching_and_import_db.problem_detection.pipeline import evaluate_unmatched_problems, STOP_PROBLEM_PIPELINE
from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.database.session import session
from matching_and_import_db.database.helpers import (
    make_point_geom,
    safe_value,
    get_osm_node_type,
)
from matching_and_import_db.database.route_loader import load_all_route_data, build_route_write_payload
from matching_and_import_db.downloader.get_atlas_gtfs import (
    GTFS_DB_STATE_CACHE_PATH,
    GTFS_DB_STOPS_CACHE_PATH,
    build_gtfs_atlas_payload,
    build_gtfs_db_payload_rows,
    load_gtfs_data_streaming,
    write_gtfs_db_payload_cache,
)
from matching_and_import_db.scheduler.job_types import PipelineRunType

# --- External models --------------------------------------------------------
from backend.models import (
    StopsMatched,
    AtlasOperator,
    AtlasStop,
    GtfsStopRaw,
    GtfsStopIdentityResolution,
    OsmNode,
    OsmStop,
    OsmStopMember,
    Problem,
    AtlasLineFamily,
    AtlasItinerary,
    AtlasItineraryStopCall,
    OsmRouteMaster,
    OsmRouteMasterTag,
    OsmRouteMasterMember,
    OsmRouteRelation,
    OsmRouteRelationTag,
    OsmRouteRelationMember,
    OsmRouteRelationStop,
    LineFamily,
    Itinerary,
    StopCall,
    LineFamilyMatch,
    ItineraryMatch,
)
from backend.services.stats_export import (
    export_pipeline_stats,
    save_stats_to_file,
    compute_db_stats,
    compute_route_route_stats,
)


def _ensure_import_schema_exists(db_session) -> None:
    """Fail fast with actionable guidance if import tables are missing."""
    required_tables = [
        'atlas_operators',
        'atlas_stops',
        'gtfs_stops_raw',
        'gtfs_stop_identity_resolution',
        'osm_nodes',
        'osm_stops',
        'osm_stop_members',
        'atlas_line_families',
        'atlas_itineraries',
        'atlas_itinerary_stop_calls',
        'osm_route_masters',
        'osm_route_master_tags',
        'osm_route_master_members',
        'osm_route_relations',
        'osm_route_relation_tags',
        'osm_route_relation_members',
        'osm_route_relation_stops',
        'line_families',
        'itineraries',
        'stop_calls',
        'line_family_matches',
        'itinerary_matches',
        'problems',
        'stops_matched',
    ]

    inspector = inspect(db_session.get_bind())
    missing = [table for table in required_tables if not inspector.has_table(table)]
    if not missing:
        return

    missing_str = ', '.join(sorted(missing))
    raise RuntimeError(
        "Import DB schema is not initialized. Missing tables: "
        f"{missing_str}. Run DB migrations first (for Docker: task 'Docker: Run Flask DB Upgrade')."
    )


STATIC_IMPORT_TABLES = [
    'atlas_operators',
    'atlas_stops',
    'gtfs_stops_raw',
    'gtfs_stop_identity_resolution',
    'atlas_line_families',
    'atlas_itineraries',
    'atlas_itinerary_stop_calls',
]

ATLAS_CACHED_REFRESH_TABLES = [
    'itinerary_matches',
    'line_family_matches',
    'stop_calls',
    'itineraries',
    'line_families',
    'osm_route_relation_stops',
    'osm_route_relation_members',
    'osm_route_relation_tags',
    'osm_route_relations',
    'osm_route_master_members',
    'osm_route_master_tags',
    'osm_route_masters',
    'problems',
    'stops_matched',
    'osm_stop_members',
    'osm_stops',
    'osm_nodes',
]

FULL_REFRESH_TABLES = ATLAS_CACHED_REFRESH_TABLES[:15] + STATIC_IMPORT_TABLES[::-1] + ATLAS_CACHED_REFRESH_TABLES[15:]

STATIC_PAYLOAD_KEYS = [
    'atlas_operators',
    'atlas_stops',
    'gtfs_stops_raw',
    'gtfs_stop_identity_resolution',
    'atlas_line_families',
    'atlas_itineraries',
    'atlas_itinerary_stop_calls',
]

DYNAMIC_PAYLOAD_KEYS = [
    'osm_nodes',
    'osm_stops',
    'osm_stop_members',
    'stops_matched',
    'problem_rows',
    'osm_route_masters',
    'osm_route_master_tags',
    'osm_route_master_members',
    'osm_route_relations',
    'osm_route_relation_tags',
    'osm_route_relation_members',
    'osm_route_relation_stops',
    'line_families',
    'itineraries',
    'stop_calls',
    'line_family_matches',
    'itinerary_matches',
]

META_PAYLOAD_KEYS = [
    'matched_routes',
    'no_nearby_osm_sloids',
]


@dataclass(frozen=True)
class ImportPayloadGroups:
    static: dict[str, Any]
    dynamic: dict[str, Any]
    meta: dict[str, Any]


def split_import_payloads(db_payloads: dict[str, Any]) -> ImportPayloadGroups:
    return ImportPayloadGroups(
        static={key: db_payloads.get(key, []) for key in STATIC_PAYLOAD_KEYS},
        dynamic={key: db_payloads.get(key, []) for key in DYNAMIC_PAYLOAD_KEYS},
        meta={key: db_payloads.get(key) for key in META_PAYLOAD_KEYS},
    )


def get_refresh_scope_tables(run_type: PipelineRunType) -> tuple[list[str], list[str]]:
    if run_type == PipelineRunType.ATLAS_CACHED:
        return list(ATLAS_CACHED_REFRESH_TABLES), list(STATIC_IMPORT_TABLES)
    return list(FULL_REFRESH_TABLES), []


def _validate_atlas_cached_refresh_preconditions(db_session) -> None:
    required_non_empty_tables = [
        'atlas_stops',
        'gtfs_stops_raw',
        'gtfs_stop_identity_resolution',
        'atlas_line_families',
        'atlas_itineraries',
        'atlas_itinerary_stop_calls',
    ]
    empty_tables = []
    for table_name in required_non_empty_tables:
        has_rows = db_session.execute(text(f'SELECT 1 FROM {table_name} LIMIT 1')).scalar() is not None
        if not has_rows:
            empty_tables.append(table_name)
    if empty_tables:
        raise RuntimeError(
            'ATLAS-cached refresh requested, but required static tables are empty: '
            f"{', '.join(empty_tables)}. Run a full refresh first."
        )


def _collect_importable_sloids(base_data: MatchingOutput) -> set[str]:
    """Collect the SLOIDs that will actually exist in atlas_stops after import."""
    importable = set()

    for rec in getattr(base_data, 'matched', []):
        sloid = safe_value(getattr(getattr(rec, 'atlas_node', None), 'sloid', None))
        if sloid:
            importable.add(str(sloid))

    for atlas_node in getattr(base_data, 'unmatched_atlas', []):
        atlas_lat, atlas_lon = atlas_node.lat, atlas_node.lon
        if atlas_lat == 0.0 and atlas_lon == 0.0:
            continue
        sloid = safe_value(getattr(atlas_node, 'sloid', None))
        if sloid:
            importable.add(str(sloid))

    return importable


def _normalize_text(value):
    value = safe_value(value)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _build_atlas_operator_record(atlas_node) -> dict | None:
    abbr = _normalize_text(getattr(atlas_node, 'business_org_abbr', None))
    if not abbr:
        return None

    return {
        'atlas_business_org_abbr': abbr,
        'sboid': _normalize_text(getattr(atlas_node, 'business_org_id', None)),
        'atlas_business_org_name': _normalize_text(getattr(atlas_node, 'business_org_name', None)),
    }


def _remember_atlas_operator(operator_rows_by_abbr: dict[str, dict], atlas_node) -> None:
    record = _build_atlas_operator_record(atlas_node)
    if record is None:
        return

    abbr = record['atlas_business_org_abbr']
    existing = operator_rows_by_abbr.get(abbr)
    if existing is None:
        operator_rows_by_abbr[abbr] = record
        return

    if not existing.get('sboid') and record.get('sboid'):
        existing['sboid'] = record['sboid']
    if not existing.get('atlas_business_org_name') and record.get('atlas_business_org_name'):
        existing['atlas_business_org_name'] = record['atlas_business_org_name']


def _write_gtfs_atlas_stats(stats_payload: dict[str, object]) -> None:
    stats_path = os.path.join('data', 'gtfs_atlas_stats.json')
    os.makedirs(os.path.dirname(stats_path), exist_ok=True)
    with open(stats_path, 'w', encoding='utf-8') as handle:
        json.dump(stats_payload, handle, indent=2)


def _normalize_cached_insert_records(rows: list[dict]) -> list[dict]:
    """Convert pandas missing sentinels from cached CSV payloads into plain None."""
    normalized_rows = []
    for row in rows:
        normalized_row = {}
        for key, value in row.items():
            cleaned = safe_value(value)
            if key.endswith('_json') and isinstance(cleaned, str):
                try:
                    cleaned = json.loads(cleaned)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            normalized_row[key] = cleaned
        normalized_rows.append(normalized_row)
    return normalized_rows


def _load_gtfs_insert_payload_cache() -> tuple[list[dict], list[dict]] | None:
    if not (os.path.exists(GTFS_DB_STOPS_CACHE_PATH) and os.path.exists(GTFS_DB_STATE_CACHE_PATH)):
        return None

    try:
        gtfs_stops_df = pd.read_csv(GTFS_DB_STOPS_CACHE_PATH)
        gtfs_state_df = pd.read_csv(GTFS_DB_STATE_CACHE_PATH)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return None

    gtfs_stop_rows = _normalize_cached_insert_records(
        gtfs_stops_df.to_dict(orient='records')
    )
    gtfs_state_rows = _normalize_cached_insert_records(
        gtfs_state_df.to_dict(orient='records')
    )
    return gtfs_stop_rows, gtfs_state_rows


def _build_gtfs_insert_payloads() -> tuple[list[dict], list[dict]]:
    cached_payload = _load_gtfs_insert_payload_cache()
    if cached_payload is not None:
        gtfs_stop_rows, gtfs_state_rows = cached_payload
        print(
            f"Loaded {len(gtfs_stop_rows)} GTFS stops and {len(gtfs_state_rows)} GTFS↔ATLAS state rows "
            "from cached GTFS import artifacts"
        )
        return gtfs_stop_rows, gtfs_state_rows

    atlas_csv_path = os.getenv('ATLAS_STOPS_CSV', 'data/raw/stops_ATLAS.csv')
    gtfs_folder = os.getenv('GTFS_FOLDER', os.path.join('data', 'raw', 'gtfs'))
    required_gtfs_files = ('stops.txt', 'stop_times.txt', 'trips.txt', 'routes.txt')

    if not os.path.exists(atlas_csv_path):
        raise FileNotFoundError(
            f"Required GTFS↔ATLAS import source is missing: {atlas_csv_path}"
        )

    missing_gtfs_files = [
        filename for filename in required_gtfs_files
        if not os.path.exists(os.path.join(gtfs_folder, filename))
    ]
    if missing_gtfs_files:
        raise FileNotFoundError(
            "Required GTFS source files are missing from "
            f"{gtfs_folder}: {', '.join(missing_gtfs_files)}"
        )

    traffic_points = pd.read_csv(atlas_csv_path, sep=';', dtype={'sloid': str, 'number': str}, low_memory=False)
    gtfs_stream = load_gtfs_data_streaming(gtfs_folder)
    gtfs_payload = build_gtfs_atlas_payload(gtfs_stream, traffic_points)
    _write_gtfs_atlas_stats(gtfs_payload['mapping_stats_export'])
    gtfs_stop_rows, gtfs_state_rows = build_gtfs_db_payload_rows(gtfs_payload, traffic_points)
    write_gtfs_db_payload_cache(gtfs_payload, traffic_points)

    matched_stop_ids = {
        row['stop_id']
        for row in gtfs_state_rows
        if row.get('resolved_sloid') and row.get('stop_id')
    }
    matched_sloids = {
        row['resolved_sloid']
        for row in gtfs_state_rows
        if row.get('resolved_sloid')
    }
    atlas_stop_ids = set(traffic_points['sloid'].dropna().astype(str).unique()) if 'sloid' in traffic_points.columns else set()

    print(
        "Prepared "
        f"{len(gtfs_stop_rows)} GTFS raw stops and {len(gtfs_state_rows)} GTFS identity-resolution rows "
        f"({len(matched_stop_ids)} GTFS matched, {len(gtfs_stop_rows) - len(matched_stop_ids)} GTFS unmatched, "
        f"{len(atlas_stop_ids) - len(matched_sloids)} ATLAS unmatched)"
    )
    return gtfs_stop_rows, gtfs_state_rows


def precompute_problem_artifacts(base_data: MatchingOutput) -> dict:
    """Precompute problem detection so maintenance phase only writes to DB."""
    problem_ctx = ProblemContext.build(base_data)

    matched_problem_map = {}
    for current_match in getattr(base_data, 'matched', []):
        current_match.evaluate_matched_problems(problem_ctx, STOP_PROBLEM_PIPELINE)
        matched_problem_map[id(current_match)] = list(current_match.problems)

    unmatched_atlas_problem_map = {}
    no_nearby_osm_sloids = set()
    for atlas_node in getattr(base_data, 'unmatched_atlas', []):
        atlas_lat, atlas_lon = atlas_node.lat, atlas_node.lon
        if atlas_lat == 0.0 and atlas_lon == 0.0:
            continue

        nearest_d = problem_ctx.nearest_osm_distance(atlas_lat, atlas_lon)
        is_isolated = True if nearest_d is None or nearest_d > 50 else False
        sloid = safe_value(getattr(atlas_node, 'sloid', None))
        if is_isolated and sloid:
            no_nearby_osm_sloids.add(str(sloid))

        unmatched_atlas_problem_map[id(atlas_node)] = {
            'match_type': 'no_nearby_counterpart' if is_isolated else None,
            'is_isolated': is_isolated,
            'problems': evaluate_unmatched_problems(STOP_PROBLEM_PIPELINE, problem_ctx, atlas_node),
        }

    unmatched_osm_problem_map = {}
    for osm_node in getattr(base_data, 'unmatched_osm', []):
        osm_lat, osm_lon = osm_node.lat, osm_node.lon
        if osm_lat == 0.0 and osm_lon == 0.0 and 'lat' not in osm_node.tags:
            continue
        unmatched_osm_problem_map[id(osm_node)] = evaluate_unmatched_problems(STOP_PROBLEM_PIPELINE, problem_ctx, osm_node)

    return {
        'problem_ctx': problem_ctx,
        'matched_problem_map': matched_problem_map,
        'unmatched_atlas_problem_map': unmatched_atlas_problem_map,
        'unmatched_osm_problem_map': unmatched_osm_problem_map,
        'no_nearby_osm_sloids': no_nearby_osm_sloids,
    }


def precompute_route_artifacts(base_data: MatchingOutput, all_route_data: dict | None = None) -> dict:
    """Prepare route-route write payload before maintenance begins."""
    route_data = all_route_data or load_all_route_data()
    importable_sloids = _collect_importable_sloids(base_data)
    route_write_payload = build_route_write_payload(route_data, importable_sloids, base_data=base_data)
    return {
        'all_route_data': route_data,
        'route_write_payload': route_write_payload,
        'known_sloids': importable_sloids,
    }


# ---------------------------------------------------------------------------
# WKT geometry helper (no SQLAlchemy server-side expressions)
# ---------------------------------------------------------------------------

def _make_point_wkt(lat, lon):
    """Create a WKT POINT string, or None if coordinates are missing."""
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    return f"SRID=4326;POINT({lon_f} {lat_f})"


# ---------------------------------------------------------------------------
# Payload builder — runs OUTSIDE the blocking maintenance window
# ---------------------------------------------------------------------------

def build_fast_insert_payloads(
    base_data: MatchingOutput,
    problem_artifacts: dict,
    route_artifacts: dict | None = None,
) -> dict:
    """Transform the full MatchingOutput into plain dicts ready for bulk DB insert.

    This function performs ALL CPU-bound work (coordinate formatting, duplicate
    group resolution, problem result attachment, trio-middle detection) so that
    the subsequent ``import_to_database`` call is pure I/O.

    Returns a dict of lists-of-dicts keyed by table name.
    """
    problem_ctx = problem_artifacts.get('problem_ctx') or ProblemContext.build(base_data)
    matched_problem_map = problem_artifacts.get('matched_problem_map', {})
    unmatched_atlas_problem_map = problem_artifacts.get('unmatched_atlas_problem_map', {})
    unmatched_osm_problem_map = problem_artifacts.get('unmatched_osm_problem_map', {})

    duplicate_sloid_map = base_data.duplicate_sloid_map

    # ---- Counters for the console summary ----
    all_sloids = []
    for rec in base_data.matched:
        sloid = safe_value(rec.atlas_node.sloid)
        if sloid:
            all_sloids.append(sloid)
    for rec in base_data.unmatched_atlas:
        sloid = safe_value(rec.sloid)
        if sloid:
            all_sloids.append(sloid)
    counts = Counter(all_sloids)
    duplicate_sloids = {s for s, c in counts.items() if c > 1}
    if duplicate_sloids:
        print(f"{len(duplicate_sloids)} sloids are matched to more than one OSM node")

    # ---- 0. OSM nodes ----
    osm_node_dicts = []
    for node in base_data.all_osm_nodes:
        osm_node_dicts.append({
            'osm_node_id': str(node.node_id),
            'osm_local_ref': node.local_ref,
            'osm_name': node.name,
            'osm_uic_name': node.uic_name,
            'osm_uic_ref': node.uic_ref,
            'osm_network': node.network,
            'osm_operator': node.operator,
            'osm_operator_wikidata': node.tags.get('operator:wikidata') if node.tags else None,
            'osm_network_wikidata': node.tags.get('network:wikidata') if node.tags else None,
            'osm_public_transport': node.public_transport,
            'osm_railway': node.railway,
            'osm_amenity': node.amenity,
            'osm_aerialway': node.aerialway,
            'osm_node_type': get_osm_node_type(node.tags, is_osm_unmatched=True) if node.tags else None,
            'duplicate_group_node_ids': problem_ctx.duplicate_osm_group_map.get(str(node.node_id)),
        })

    # ---- 0a. OSM stop units + members (assign sequential IDs in memory) ----
    osm_stop_dicts = []
    osm_stop_member_dicts = []
    next_stop_id = 1
    for stop_unit in base_data.osm_stop_units:
        stop_id = next_stop_id
        next_stop_id += 1
        osm_stop_dicts.append({
            'id': stop_id,
            'stop_kind': stop_unit.stop_kind,
            'group_kind': stop_unit.group_kind,
            'representative_node_id': stop_unit.representative_node_id,
        })
        for member in stop_unit.members:
            osm_stop_member_dicts.append({
                'osm_stop_id': stop_id,
                'node_id': member.node_id,
                'member_role': member.member_role,
            })

    # ---- Track processed sloids/osm_node_ids ----
    processed_sloids = set()
    processed_osm_node_ids = set()

    # ---- 1. Matched stops ----
    stops_matched_dicts = []
    atlas_operator_rows_by_abbr = {}
    atlas_stop_dicts = []
    # problems_dicts will be keyed by a temporary stop sequence number.
    # We use a list of (stop_sequence, problem_dicts) to pair them up later.
    problem_rows = []  # list of (temp_stop_idx, problem_type, priority)
    stop_idx = 0  # running index used as temporary PK for problems

    for current_match in base_data.matched:
        atlas_lat = current_match.atlas_node.lat
        atlas_lon = current_match.atlas_node.lon
        osm_lat = current_match.osm_node.lat
        osm_lon = current_match.osm_node.lon

        if id(current_match) in matched_problem_map:
            problems = matched_problem_map[id(current_match)]
        else:
            current_match.evaluate_matched_problems(problem_ctx, STOP_PROBLEM_PIPELINE)
            problems = current_match.problems

        sloid = current_match.atlas_node.sloid
        osm_node_id = current_match.osm_node.node_id
        distance_m = current_match.distance_m

        geom_wkt = _make_point_wkt(atlas_lat, atlas_lon) if atlas_lat is not None and atlas_lon is not None else _make_point_wkt(osm_lat, osm_lon)

        stops_matched_dicts.append({
            '_idx': stop_idx,
            'sloid': sloid,
            'stop_type': 'matched',
            'match_type': current_match.match_type,
            'atlas_lat': atlas_lat,
            'atlas_lon': atlas_lon,
            'osm_node_id': osm_node_id,
            'osm_lat': osm_lat,
            'osm_lon': osm_lon,
            'distance_m': distance_m,
            'matching_notes': current_match.notes,
            'geom': geom_wkt,
        })

        for p in problems:
            problem_rows.append((stop_idx, p.problem_type, p.priority))

        if sloid and sloid not in processed_sloids:
            dup_group = duplicate_sloid_map.get(str(sloid))
            rep_sloid = None
            if dup_group and str(sloid) != dup_group[0]:
                rep_sloid = dup_group[0]
            _remember_atlas_operator(atlas_operator_rows_by_abbr, current_match.atlas_node)
            atlas_stop_dicts.append({
                'sloid': sloid,
                'uic_ref': current_match.atlas_node.uic_ref,
                'atlas_designation': current_match.atlas_node.designation,
                'atlas_designation_official': current_match.atlas_node.designation_official,
                'atlas_business_org_abbr': _normalize_text(current_match.atlas_node.business_org_abbr),
                'representative_sloid': rep_sloid,
                'duplicate_group_sloids': dup_group,
            })
            processed_sloids.add(sloid)

        if osm_node_id:
            processed_osm_node_ids.add(osm_node_id)

        stop_idx += 1

    # ---- 2. Unmatched ATLAS ----
    no_nearby_osm_sloids = set()
    for atlas_node in base_data.unmatched_atlas:
        atlas_lat, atlas_lon = atlas_node.lat, atlas_node.lon
        if atlas_lat == 0.0 and atlas_lon == 0.0:
            continue

        sloid = atlas_node.sloid
        precomputed_entry = unmatched_atlas_problem_map.get(id(atlas_node))

        if precomputed_entry is not None:
            is_isolated = bool(precomputed_entry.get('is_isolated', False))
            match_type_for_unmatched = precomputed_entry.get('match_type')
            problems = precomputed_entry.get('problems', [])
        else:
            nearest_d = problem_ctx.nearest_osm_distance(atlas_lat, atlas_lon)
            is_isolated = True if nearest_d is None or nearest_d > 50 else False
            match_type_for_unmatched = 'no_nearby_counterpart' if is_isolated else None
            problems = evaluate_unmatched_problems(STOP_PROBLEM_PIPELINE, problem_ctx, atlas_node)

        if is_isolated and sloid:
            no_nearby_osm_sloids.add(sloid)

        geom_wkt = _make_point_wkt(atlas_lat, atlas_lon)

        stops_matched_dicts.append({
            '_idx': stop_idx,
            'sloid': sloid,
            'stop_type': 'atlas_unmatched',
            'match_type': match_type_for_unmatched,
            'atlas_lat': atlas_lat,
            'atlas_lon': atlas_lon,
            'osm_node_id': None,
            'osm_lat': None,
            'osm_lon': None,
            'distance_m': None,
            'matching_notes': None,
            'geom': geom_wkt,
        })

        for p in problems:
            problem_rows.append((stop_idx, p.problem_type, p.priority))

        if sloid and sloid not in processed_sloids:
            dup_group = duplicate_sloid_map.get(str(sloid))
            rep_sloid = None
            if dup_group and str(sloid) != dup_group[0]:
                rep_sloid = dup_group[0]
            _remember_atlas_operator(atlas_operator_rows_by_abbr, atlas_node)
            atlas_stop_dicts.append({
                'sloid': sloid,
                'uic_ref': atlas_node.uic_ref,
                'atlas_designation': atlas_node.designation,
                'atlas_designation_official': atlas_node.designation_official,
                'atlas_business_org_abbr': _normalize_text(atlas_node.business_org_abbr),
                'representative_sloid': rep_sloid,
                'duplicate_group_sloids': dup_group,
            })
            processed_sloids.add(sloid)

        stop_idx += 1

    # ---- 3. Unmatched OSM ----
    # Pre-calculate middle nodes where both sides are matched
    matched_osm_nodes = {str(r.osm_node.node_id) for r in base_data.matched if getattr(r, 'osm_node', None)}
    trio_middles_effectively_matched = set()
    for stop_unit in base_data.osm_stop_units:
        if stop_unit.stop_kind == 'trio':
            middle_id = None
            side_ids = []
            for m in stop_unit.members:
                if m.member_role == 'trio_middle':
                    middle_id = str(m.node_id)
                elif m.member_role == 'trio_side':
                    side_ids.append(str(m.node_id))
            if middle_id and len(side_ids) == 2:
                if all(s in matched_osm_nodes for s in side_ids):
                    trio_middles_effectively_matched.add(middle_id)

    for osm_node in base_data.unmatched_osm:
        osm_lat, osm_lon = osm_node.lat, osm_node.lon
        if osm_lat == 0.0 and osm_lon == 0.0 and 'lat' not in osm_node.tags:
            continue

        osm_node_id = str(osm_node.node_id)
        stop_type = 'osm_unmatched'
        match_type = None
        if osm_node_id in trio_middles_effectively_matched:
            stop_type = 'effectively_matched'
            match_type = 'distance_matching_trio'

        if id(osm_node) in unmatched_osm_problem_map:
            problems = unmatched_osm_problem_map[id(osm_node)]
        else:
            problems = evaluate_unmatched_problems(STOP_PROBLEM_PIPELINE, problem_ctx, osm_node)

        geom_wkt = _make_point_wkt(osm_lat, osm_lon)

        stops_matched_dicts.append({
            '_idx': stop_idx,
            'sloid': None,
            'stop_type': stop_type,
            'match_type': match_type,
            'atlas_lat': None,
            'atlas_lon': None,
            'osm_node_id': osm_node_id,
            'osm_lat': osm_lat,
            'osm_lon': osm_lon,
            'distance_m': None,
            'matching_notes': None,
            'geom': geom_wkt,
        })

        for p in problems:
            problem_rows.append((stop_idx, p.problem_type, p.priority))

        if osm_node_id:
            processed_osm_node_ids.add(osm_node_id)

        stop_idx += 1

    # ---- 4. Route payload + synthetic OSM nodes referenced by route rows ----
    route_artifacts = route_artifacts or {}
    all_route_data = route_artifacts.get('all_route_data')
    if all_route_data is None:
        all_route_data = load_all_route_data()

    route_write_payload = route_artifacts.get('route_write_payload')
    if route_write_payload is None:
        importable_sloids = {d['sloid'] for d in atlas_stop_dicts if d.get('sloid')}
        route_write_payload = build_route_write_payload(all_route_data, importable_sloids, base_data=base_data)

    known_osm_node_ids = {d['osm_node_id'] for d in osm_node_dicts}

    route_node_ids = {
        str(row['osm_node_id'])
        for row in route_write_payload.get('osm_route_relation_stops', [])
        if row.get('osm_node_id')
    }
    route_node_ids |= {
        str(row['source_node_id'])
        for row in route_write_payload.get('stop_calls', [])
        if row.get('source_node_id')
    }
    synthetic_node_ids = sorted(route_node_ids - known_osm_node_ids)
    if synthetic_node_ids:
        for node_id in synthetic_node_ids:
            osm_node_dicts.append({'osm_node_id': node_id})
        print(f"Prepared {len(synthetic_node_ids)} synthetic OSM nodes referenced by routes")

    # ---- 5. Route rows ----
    skipped_route_osm_nodes = 0
    atlas_line_family_dicts = route_write_payload.get('atlas_line_families', [])
    atlas_itinerary_dicts = route_write_payload.get('atlas_itineraries', [])
    atlas_itinerary_stop_call_dicts = route_write_payload.get('atlas_itinerary_stop_calls', [])
    osm_route_master_dicts = route_write_payload.get('osm_route_masters', [])
    osm_route_master_tag_dicts = route_write_payload.get('osm_route_master_tags', [])
    osm_route_master_member_dicts = route_write_payload.get('osm_route_master_members', [])
    osm_route_relation_dicts = route_write_payload.get('osm_route_relations', [])
    osm_route_relation_tag_dicts = route_write_payload.get('osm_route_relation_tags', [])
    osm_route_relation_member_dicts = route_write_payload.get('osm_route_relation_members', [])
    osm_route_relation_stop_dicts = route_write_payload.get('osm_route_relation_stops', [])
    line_family_dicts = route_write_payload.get('line_families', [])
    itinerary_dicts = route_write_payload.get('itineraries', [])
    stop_call_dicts = route_write_payload.get('stop_calls', [])
    line_family_match_dicts = route_write_payload.get('line_family_matches', [])
    itinerary_match_dicts = route_write_payload.get('itinerary_matches', [])

    skipped_sloids = int(route_write_payload.get('skipped_sloids', 0) or 0)
    matched_routes = int(route_write_payload.get('matched_routes', 0) or 0)

    if skipped_sloids:
        print(f"  Skipped {skipped_sloids} atlas itinerary stop calls with non-imported SLOIDs")

    gtfs_stop_dicts, gtfs_identity_resolution_dicts = _build_gtfs_insert_payloads()
    atlas_operator_dicts = sorted(
        atlas_operator_rows_by_abbr.values(),
        key=lambda row: row['atlas_business_org_abbr'],
    )

    # ---- Summary ----
    total_matched = sum(1 for d in stops_matched_dicts if d['stop_type'] == 'matched')
    print(f"Payload precompute complete: {len(stops_matched_dicts)} stop rows, "
          f"{len(osm_node_dicts)} OSM nodes, {len(atlas_operator_dicts)} ATLAS operators, {len(atlas_stop_dicts)} ATLAS stops, "
          f"{len(gtfs_stop_dicts)} GTFS raw stops, {len(gtfs_identity_resolution_dicts)} GTFS identity rows, "
          f"{len(problem_rows)} problem rows, {len(line_family_match_dicts)} matched line families")

    return {
        'osm_nodes': osm_node_dicts,
        'osm_stops': osm_stop_dicts,
        'osm_stop_members': osm_stop_member_dicts,
        'stops_matched': stops_matched_dicts,
        'atlas_operators': atlas_operator_dicts,
        'atlas_stops': atlas_stop_dicts,
        'gtfs_stops_raw': gtfs_stop_dicts,
        'gtfs_stop_identity_resolution': gtfs_identity_resolution_dicts,
        'problem_rows': problem_rows,
        'atlas_line_families': atlas_line_family_dicts,
        'atlas_itineraries': atlas_itinerary_dicts,
        'atlas_itinerary_stop_calls': atlas_itinerary_stop_call_dicts,
        'osm_route_masters': osm_route_master_dicts,
        'osm_route_master_tags': osm_route_master_tag_dicts,
        'osm_route_master_members': osm_route_master_member_dicts,
        'osm_route_relations': osm_route_relation_dicts,
        'osm_route_relation_tags': osm_route_relation_tag_dicts,
        'osm_route_relation_members': osm_route_relation_member_dicts,
        'osm_route_relation_stops': osm_route_relation_stop_dicts,
        'line_families': line_family_dicts,
        'itineraries': itinerary_dicts,
        'stop_calls': stop_call_dicts,
        'line_family_matches': line_family_match_dicts,
        'itinerary_matches': itinerary_match_dicts,
        'matched_routes': route_write_payload.get('matched_routes', 0),
        'no_nearby_osm_sloids': no_nearby_osm_sloids,
    }


# ---------------------------------------------------------------------------
# Fast DB writer — runs INSIDE the blocking maintenance window
# ---------------------------------------------------------------------------

_BULK_BATCH = int(os.getenv('DB_IMPORT_BATCH_SIZE', '10000'))


def _bulk_insert_rows(model, rows: list[dict], label: str | None = None) -> int:
    if not rows:
        return 0
    for i in range(0, len(rows), _BULK_BATCH):
        session.execute(insert(model), rows[i:i + _BULK_BATCH])
    session.commit()
    if label:
        print(f"Imported {len(rows)} {label}")
    return len(rows)


def import_to_database(
    db_payloads: dict | None = None,
    run_type: PipelineRunType = PipelineRunType.COMPLETE,
):
    """Fully refresh the database "Import DB".

    Expects precomputed payloads so the write phase stays focused on TRUNCATE
    plus bulk INSERT work.
    """
    _ensure_import_schema_exists(session)

    if db_payloads is None:
        raise ValueError("db_payloads must be provided")

    payload_groups = split_import_payloads(db_payloads)
    db_payloads = {
        **payload_groups.static,
        **payload_groups.dynamic,
        **payload_groups.meta,
    }
    rewritten_tables, reused_tables = get_refresh_scope_tables(run_type)
    if run_type == PipelineRunType.ATLAS_CACHED:
        _validate_atlas_cached_refresh_preconditions(session)

    # ---- TRUNCATE selected tables ----
    print(f"Truncating {len(rewritten_tables)} tables for {run_type.value} refresh...")
    if reused_tables:
        print(f"Reusing static tables: {', '.join(reused_tables)}")
    session.execute(text(f"TRUNCATE TABLE {', '.join(rewritten_tables)} CASCADE"))
    session.commit()

    _bulk_insert_rows(OsmNode, db_payloads.get('osm_nodes', []), 'OSM nodes')
    _bulk_insert_rows(OsmStop, db_payloads.get('osm_stops', []), 'OSM stop units')
    _bulk_insert_rows(OsmStopMember, db_payloads.get('osm_stop_members', []), 'OSM stop members')
    if run_type == PipelineRunType.COMPLETE:
        _bulk_insert_rows(AtlasOperator, db_payloads.get('atlas_operators', []), 'ATLAS operators')
        _bulk_insert_rows(AtlasStop, db_payloads.get('atlas_stops', []), 'ATLAS stops')
        _bulk_insert_rows(GtfsStopRaw, db_payloads.get('gtfs_stops_raw', []), 'GTFS raw stops')
        _bulk_insert_rows(
            GtfsStopIdentityResolution,
            db_payloads.get('gtfs_stop_identity_resolution', []),
            'GTFS identity-resolution rows',
        )

    # ---- Bulk insert: stops_matched (strip internal _idx before insert) ----
    stops_rows = db_payloads.get('stops_matched', [])
    if stops_rows:
        # Insert in batches and collect auto-generated IDs to link problems
        stop_idx_to_db_id = {}
        for i in range(0, len(stops_rows), _BULK_BATCH):
            batch = stops_rows[i:i + _BULK_BATCH]
            clean_batch = [{k: v for k, v in d.items() if k != '_idx'} for d in batch]
            result = session.execute(
                insert(StopsMatched).returning(StopsMatched.id),
                clean_batch,
            )
            db_ids = [row[0] for row in result]
            for d, db_id in zip(batch, db_ids):
                stop_idx_to_db_id[d['_idx']] = db_id
        session.commit()
        print(f"Imported {len(stops_rows)} stops_matched rows")

        # ---- Bulk insert: problems ----
        problem_raw = db_payloads['problem_rows']
        if problem_raw:
            problem_dicts = [
                {'stop_id': stop_idx_to_db_id[idx], 'problem_type': ptype, 'priority': prio}
                for idx, ptype, prio in problem_raw
                if idx in stop_idx_to_db_id
            ]
            if problem_dicts:
                for i in range(0, len(problem_dicts), _BULK_BATCH):
                    session.execute(insert(Problem), problem_dicts[i:i + _BULK_BATCH])
                session.commit()
                print(f"Imported {len(problem_dicts)} problem rows")

    if run_type == PipelineRunType.COMPLETE:
        _bulk_insert_rows(AtlasLineFamily, db_payloads.get('atlas_line_families', []), 'ATLAS line families')
        _bulk_insert_rows(AtlasItinerary, db_payloads.get('atlas_itineraries', []), 'ATLAS itineraries')
        _bulk_insert_rows(
            AtlasItineraryStopCall,
            db_payloads.get('atlas_itinerary_stop_calls', []),
            'ATLAS itinerary stop calls',
        )
    _bulk_insert_rows(OsmRouteMaster, db_payloads.get('osm_route_masters', []), 'OSM route masters')
    _bulk_insert_rows(
        OsmRouteMasterTag,
        db_payloads.get('osm_route_master_tags', []),
        'OSM route master tags',
    )
    _bulk_insert_rows(
        OsmRouteRelation,
        db_payloads.get('osm_route_relations', []),
        'OSM route relations',
    )
    _bulk_insert_rows(
        OsmRouteMasterMember,
        db_payloads.get('osm_route_master_members', []),
        'OSM route master members',
    )
    _bulk_insert_rows(
        OsmRouteRelationTag,
        db_payloads.get('osm_route_relation_tags', []),
        'OSM route relation tags',
    )
    _bulk_insert_rows(
        OsmRouteRelationMember,
        db_payloads.get('osm_route_relation_members', []),
        'OSM route relation members',
    )
    _bulk_insert_rows(
        OsmRouteRelationStop,
        db_payloads.get('osm_route_relation_stops', []),
        'OSM route relation stops',
    )
    _bulk_insert_rows(LineFamily, db_payloads.get('line_families', []), 'line families')
    _bulk_insert_rows(Itinerary, db_payloads.get('itineraries', []), 'itineraries')
    _bulk_insert_rows(StopCall, db_payloads.get('stop_calls', []), 'stop calls')
    _bulk_insert_rows(
        LineFamilyMatch,
        db_payloads.get('line_family_matches', []),
        'line family matches',
    )
    _bulk_insert_rows(
        ItineraryMatch,
        db_payloads.get('itinerary_matches', []),
        'itinerary matches',
    )

    matched_routes = db_payloads.get('matched_routes', 0)
    itinerary_matches = len(db_payloads.get('itinerary_matches', []))
    print(f"Route import completed: {matched_routes} line-family matches, {itinerary_matches} itinerary matches")

    session.close()
    print("Data import complete!")

    return db_payloads.get('no_nearby_osm_sloids', set())


def _print_problem_summary(session):
    ps = compute_db_stats(session)
    print("\n==== PROBLEM DETECTION SUMMARY ====")
    print(f"Total stops imported: {ps['total_stops']}")
    print(f"Distance problems: {ps['distance']}")
    print(f"Unmatched problems: {ps['unmatched']}")
    print(f"Attributes problems: {ps['attributes']}")
    print(f"Duplicates problems: {ps['duplicates']}")
    print(f"Entries with multiple problems: {ps['multiple_problems']}")
    print(f"Clean entries (no problems): {ps['clean_entries']}")


def print_problem_summary():
    """Print database problem summary, typically after blocking maintenance ends."""
    _print_problem_summary(session)

# --------------------------
# Data Import Function
# --------------------------
def export_stats_after_import(base_data, duplicate_sloid_map, no_nearby_sloids):
    """
    Export pipeline statistics to data/stats.json after import completes.
    """
    try:
        matched_records = getattr(base_data, 'matched', [])
        unmatched_atlas = getattr(base_data, 'unmatched_atlas', [])
        unmatched_osm = getattr(base_data, 'unmatched_osm', [])
        
        # Calculate total ATLAS platforms from records
        matched_sloids = {r.atlas_node.sloid for r in matched_records if getattr(r, 'atlas_node', None) and r.atlas_node.sloid}
        unmatched_sloids = {r.sloid for r in unmatched_atlas if getattr(r, 'sloid', None)}
        total_atlas = len(matched_sloids | unmatched_sloids)
        
        # Calculate OSM stop counts from canonical stop units
        osm_stop_units = getattr(base_data, 'osm_stop_units', [])
        total_osm_stops = len(osm_stop_units)
        
        # Calculate raw OSM nodes count
        all_osm_nodes = getattr(base_data, 'all_osm_nodes', [])
        total_osm_nodes = len(all_osm_nodes)
        total_osm_stations = sum(1 for node in all_osm_nodes if getattr(node, 'is_station', False))

        node_to_stop_id = {}
        for stop_idx, stop_unit in enumerate(osm_stop_units):
            for member in stop_unit.members:
                node_to_stop_id[str(member.node_id)] = stop_idx
        matched_osm_stops = len({
            node_to_stop_id[str(r.osm_node.node_id)]
            for r in matched_records
            if getattr(r, 'osm_node', None)
            and r.osm_node.node_id
            and str(r.osm_node.node_id) in node_to_stop_id
        })
        unmatched_osm_stops = max(0, total_osm_stops - matched_osm_stops)
        
        # Calculate OSM route stats
        osm_with_routes_count = 0
        try:
            routes_path = "data/processed/osm_route_relation_members.csv"
            if os.path.exists(routes_path):
                routes_df = pd.read_csv(routes_path)
                nodes_with_routes = set(routes_df['resolved_node_id'].dropna().astype(str).unique())

                osm_with_routes_count = sum(
                    1 for stop_unit in getattr(base_data, 'osm_stop_units', [])
                    if any(str(member.node_id) in nodes_with_routes for member in stop_unit.members)
                )
        except Exception as e:
            print(f"Warning: Could not calculate OSM route stats: {e}")

        osm_route_stats = {
            'osm_with_routes': osm_with_routes_count
        }
        
        # Calculate Wikidata tag counts
        osm_operator_wikidata_count = sum(1 for node in all_osm_nodes if node.tags.get('operator:wikidata'))
        osm_network_wikidata_count = sum(1 for node in all_osm_nodes if node.tags.get('network:wikidata'))

        stats = export_pipeline_stats(
            matched_records=matched_records,
            unmatched_atlas=unmatched_atlas,
            unmatched_osm=unmatched_osm,
            duplicate_sloid_map=duplicate_sloid_map,
            no_nearby_osm_sloids=no_nearby_sloids,
            osm_stop_units=osm_stop_units,
            total_atlas_platforms=total_atlas,
            total_osm_stops=total_osm_stops,
            total_osm_nodes=total_osm_nodes,
            total_osm_stations=total_osm_stations,
            total_matched_osm_stops=matched_osm_stops,
            total_unmatched_osm_stops=unmatched_osm_stops,
            osm_route_stats=osm_route_stats,
            osm_nodes_with_routes=nodes_with_routes if 'nodes_with_routes' in locals() else set(),
            total_osm_operator_wikidata=osm_operator_wikidata_count,
            total_osm_network_wikidata=osm_network_wikidata_count
        )

        # Compute quality metrics (distance quality, many-to-one, cross-predicate, OSM groups)
        try:
            from backend.services.stats_export import compute_quality_metrics
            quality = compute_quality_metrics(
                matched_records=matched_records,
                all_osm_nodes=getattr(base_data, 'all_osm_nodes', []),
                osm_stop_units=getattr(base_data, 'osm_stop_units', []),
            )
            stats['quality_metrics'] = quality
        except Exception as e:
            print(f"Warning: Could not compute quality metrics: {e}")

        # Compute problem statistics from DB
        try:
            from matching_and_import_db.database.session import session
            stats['problems'] = compute_db_stats(session)
        except Exception as e:
            print(f"Warning: Could not compute problem statistics: {e}")

        # Compute route-route statistics from DB route tables
        try:
            from matching_and_import_db.database.session import session
            stats['route_route_matching'] = compute_route_route_stats(session)
        except Exception as e:
            print(f"Warning: Could not compute route-route statistics: {e}")

        # Preserve only independent stats generated outside the final export pass.
        from backend.services.stats_export import load_stats_from_file
        existing_stats = load_stats_from_file() or {}
        for key in ('atlas_filtering',):
            if key in existing_stats:
                stats[key] = existing_stats[key]

        filepath = save_stats_to_file(stats)
        print(f"\n==== STATISTICS EXPORTED ====")
        print(f"Stats saved to: {filepath}")

        print(f"Generated at: {stats['generated_at']}")
        print(f"Summary: {stats['summary']['matched_pairs']} matched pairs ({stats['summary']['match_rate_percent']}%)")
        
        return stats
    except Exception as e:
        print(f"Warning: Failed to export stats: {e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the database import pipeline.")
    args = parser.parse_args()

    print("Running the final pipeline to obtain base data...")
    result = run_matching()
    problem_artifacts = precompute_problem_artifacts(result)
    route_artifacts = precompute_route_artifacts(result)
    db_payloads = build_fast_insert_payloads(result, problem_artifacts, route_artifacts)
    
    print("Importing data into the database...")
    no_nearby_sloids = import_to_database(db_payloads=db_payloads)

    export_stats_after_import(result, result.duplicate_sloid_map, no_nearby_sloids)
    print("Process completed successfully!")
