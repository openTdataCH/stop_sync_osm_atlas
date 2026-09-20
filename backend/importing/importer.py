"""
Database import orchestrator.

Projects a validated result bundle into the review app's PostGIS schema.
Matching, grouping, route comparison and diagnostic decisions are already
complete in the bundle. Only application persistence happens here.
"""
import os
import time
import argparse
import ast
import json
from collections import Counter
from typing import Any

from sqlalchemy import text, inspect, insert

# --- Internal modules -------------------------------------------------------
from backend.importing.session import session
from backend.importing.helpers import safe_value, get_osm_node_type
from backend.jobs.job_types import PipelineRunType
from backend.importing.projection import project_bundle
from backend.importing.bundle import read_bundle
from backend.importing.timing import stage

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
    OsmRouteRelation,
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
        'osm_route_relations',
        'line_families',
        'itineraries',
        'stop_calls',
        'line_family_matches',
        'itinerary_matches',
        'problems',
        'stops_matched',
        'dataset_publication',
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


FULL_REFRESH_TABLES = [
    'itinerary_matches',
    'line_family_matches',
    'stop_calls',
    'itineraries',
    'line_families',
    'osm_route_relations',
    'problems',
    'stops_matched',
    'osm_stop_members',
    'osm_stops',
    'osm_nodes',
    'atlas_line_families',
    'gtfs_stop_identity_resolution',
    'gtfs_stops_raw',
    'atlas_stops',
    'atlas_operators',
]


def get_refresh_scope_tables(run_type: PipelineRunType) -> tuple[list[str], list[str]]:
    return list(FULL_REFRESH_TABLES), []


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


def _filter_gtfs_identity_rows_to_known_sloids(
    gtfs_identity_rows: list[dict],
    known_sloids: set[str],
) -> list[dict]:
    filtered_rows = []
    dropped_resolutions = 0
    for row in gtfs_identity_rows:
        resolved_sloid = safe_value(row.get('resolved_sloid'))
        if resolved_sloid and str(resolved_sloid) not in known_sloids:
            row = dict(row)
            row['details_json'] = {
                **_coerce_details_json_mapping(row.get('details_json')),
                'dropped_resolved_sloid': str(resolved_sloid),
                'dropped_reason': 'resolved_sloid_not_imported',
            }
            row['resolved_sloid'] = None
            row['resolution_method'] = 'unmatched'
            row['confidence'] = 0.0
            row['distance_m'] = None
            row['atlas_lat'] = None
            row['atlas_lon'] = None
            dropped_resolutions += 1
        filtered_rows.append(row)

    if dropped_resolutions:
        print(
            "Dropped "
            f"{dropped_resolutions} GTFS↔ATLAS resolutions that referenced non-imported ATLAS SLOIDs"
        )
    return filtered_rows


def _coerce_details_json_mapping(value: Any) -> dict:
    cleaned = safe_value(value)
    if cleaned is None:
        return {}
    if isinstance(cleaned, dict):
        return dict(cleaned)
    if isinstance(cleaned, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(cleaned)
            except (TypeError, ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return {'raw_details_json': cleaned}
    return {'raw_details_json': str(cleaned)}


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
    base_data,
    problem_artifacts: dict,
    route_artifacts: dict | None = None,
) -> dict:
    """Transform the projected bundle into plain dicts ready for bulk DB insert.

    Format coordinates and attach the engine's exported groups, problems and
    effective-match decisions. Matching and detection are not repeated here.
    Prepare these rows before staging database inserts.

    Returns a dict of lists-of-dicts keyed by table name.
    """
    problem_ctx = problem_artifacts['problem_ctx']
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

        sloid = atlas_node.sloid
        precomputed_entry = unmatched_atlas_problem_map.get(id(atlas_node))

        if precomputed_entry is None:
            raise ValueError(f"Missing exported unmatched-source result: {sloid}")
        is_isolated = bool(precomputed_entry.get('is_isolated', False))
        match_type_for_unmatched = precomputed_entry.get('match_type')
        problems = precomputed_entry.get('problems', [])

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
    trio_middles_effectively_matched = set(base_data.effectively_matched_osm_ids)

    for osm_node in base_data.unmatched_osm:
        osm_lat, osm_lon = osm_node.lat, osm_node.lon

        osm_node_id = str(osm_node.node_id)
        stop_type = 'osm_unmatched'
        match_type = None
        if osm_node_id in trio_middles_effectively_matched:
            stop_type = 'effectively_matched'
            match_type = 'distance_matching_trio'

        problems = unmatched_osm_problem_map[id(osm_node)]

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
    route_write_payload = route_artifacts.get('route_write_payload', {})

    known_osm_node_ids = {d['osm_node_id'] for d in osm_node_dicts}

    route_node_ids = {
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
    def table_rows(model, name):
        # Portable route rows can contain adapter evidence not stored by the
        # application (e.g. normalized IDs on raw relations). ORM insertion used
        # to ignore these fields implicitly; project them explicitly for COPY.
        columns = set(model.__table__.columns.keys())
        return [{key: value for key, value in row.items() if key in columns}
                for row in route_write_payload.get(name, [])]

    atlas_line_family_dicts = table_rows(AtlasLineFamily, 'atlas_line_families')
    osm_route_relation_dicts = table_rows(OsmRouteRelation, 'osm_route_relations')
    line_family_dicts = table_rows(LineFamily, 'line_families')
    itinerary_dicts = table_rows(Itinerary, 'itineraries')
    stop_call_dicts = table_rows(StopCall, 'stop_calls')
    line_family_match_dicts = table_rows(LineFamilyMatch, 'line_family_matches')
    itinerary_match_dicts = table_rows(ItineraryMatch, 'itinerary_matches')

    skipped_sloids = int(route_write_payload.get('skipped_sloids', 0) or 0)
    matched_routes = int(route_write_payload.get('matched_routes', 0) or 0)

    if skipped_sloids:
        print(f"  Skipped {skipped_sloids} atlas itinerary stop calls with non-imported SLOIDs")

    atlas_operator_dicts = sorted(
        atlas_operator_rows_by_abbr.values(),
        key=lambda row: row['atlas_business_org_abbr'],
    )
    importable_sloids = {row['sloid'] for row in atlas_stop_dicts if row.get('sloid')}
    gtfs_stop_dicts = base_data.gtfs_stops
    gtfs_identity_resolution_dicts = base_data.gtfs_atlas_state
    gtfs_identity_resolution_dicts = _filter_gtfs_identity_rows_to_known_sloids(
        gtfs_identity_resolution_dicts,
        importable_sloids,
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
        'osm_route_relations': osm_route_relation_dicts,
        'line_families': line_family_dicts,
        'itineraries': itinerary_dicts,
        'stop_calls': stop_call_dicts,
        'line_family_matches': line_family_match_dicts,
        'itinerary_matches': itinerary_match_dicts,
        'matched_routes': route_write_payload.get('matched_routes', 0),
        'no_nearby_osm_sloids': no_nearby_osm_sloids,
    }


# ---------------------------------------------------------------------------
# DB writer — loads an isolated staging schema while public tables remain readable
# ---------------------------------------------------------------------------

_BULK_BATCH = int(os.getenv('DB_IMPORT_BATCH_SIZE', '10000'))


def _bulk_insert_rows(model, rows: list[dict], label: str | None = None, *, db_session=None) -> int:
    if not rows:
        return 0
    db_session = db_session or session
    method = os.getenv('DB_IMPORT_METHOD', 'copy')
    if method not in ('copy', 'insert'):
        raise ValueError('DB_IMPORT_METHOD must be copy or insert')
    use_copy = method == 'copy' and db_session.info.get('snapshot_schema')
    with stage('import.table', table=model.__tablename__, rows=len(rows), method='copy' if use_copy else 'insert'):
        for i in range(0, len(rows), _BULK_BATCH):
            batch = rows[i:i + _BULK_BATCH]
            if use_copy:
                from backend.importing.bulk import copy_rows
                copy_rows(db_session, model, batch)
            else:
                db_session.execute(insert(model), batch)
    if label:
        print(f"Imported {len(rows)} {label}")
    return len(rows)


def _validate_refresh_payloads(db_payloads: dict) -> None:
    """Refuse destructive refreshes that would publish an empty map."""
    if not db_payloads.get('stops_matched'):
        raise RuntimeError(
            "Refusing to refresh import DB: payload contains no stops_matched rows. "
            "This usually means matching/precompute produced an empty result and the "
            "previous public data should be preserved."
        )


def _write_rows(db_session, db_payloads):
    _bulk_insert_rows(OsmNode, db_payloads.get('osm_nodes', []), 'OSM nodes', db_session=db_session)
    _bulk_insert_rows(OsmStop, db_payloads.get('osm_stops', []), 'OSM stop units', db_session=db_session)
    _bulk_insert_rows(OsmStopMember, db_payloads.get('osm_stop_members', []), 'OSM stop members', db_session=db_session)
    _bulk_insert_rows(AtlasOperator, db_payloads.get('atlas_operators', []), 'ATLAS operators', db_session=db_session)
    _bulk_insert_rows(AtlasStop, db_payloads.get('atlas_stops', []), 'ATLAS stops', db_session=db_session)
    _bulk_insert_rows(GtfsStopRaw, db_payloads.get('gtfs_stops_raw', []), 'GTFS raw stops', db_session=db_session)
    _bulk_insert_rows(GtfsStopIdentityResolution, db_payloads.get('gtfs_stop_identity_resolution', []), 'GTFS identity-resolution rows', db_session=db_session)
    stops_rows = db_payloads.get('stops_matched', [])
    if stops_rows:
        stop_idx_to_db_id = {}
        if db_session.info.get('snapshot_schema') and os.getenv('DB_IMPORT_METHOD', 'copy') == 'copy':
            # These tables are new and empty. Stable explicit IDs avoid an ORM
            # INSERT RETURNING round trip while keeping problem links exact.
            clean_rows = []
            for db_id, row in enumerate(stops_rows, 1):
                stop_idx_to_db_id[row['_idx']] = db_id
                clean_rows.append({**{k: v for k, v in row.items() if k != '_idx'}, 'id': db_id})
            _bulk_insert_rows(StopsMatched, clean_rows, 'stops_matched rows', db_session=db_session)
        else:
            for i in range(0, len(stops_rows), _BULK_BATCH):
                batch = stops_rows[i:i + _BULK_BATCH]
                clean_batch = [{k: v for k, v in row.items() if k != '_idx'} for row in batch]
                result = db_session.execute(insert(StopsMatched).returning(StopsMatched.id, sort_by_parameter_order=True), clean_batch)
                for row, returned in zip(batch, result):
                    stop_idx_to_db_id[row['_idx']] = returned[0]
        problems = [{'stop_id': stop_idx_to_db_id[idx], 'problem_type': kind, 'priority': priority}
                    for idx, kind, priority in db_payloads['problem_rows'] if idx in stop_idx_to_db_id]
        _bulk_insert_rows(Problem, problems, 'problem rows', db_session=db_session)
    _bulk_insert_rows(AtlasLineFamily, db_payloads.get('atlas_line_families', []), 'ATLAS line families', db_session=db_session)
    _bulk_insert_rows(OsmRouteRelation, db_payloads.get('osm_route_relations', []), 'OSM route relations', db_session=db_session)
    _bulk_insert_rows(LineFamily, db_payloads.get('line_families', []), 'line families', db_session=db_session)
    _bulk_insert_rows(Itinerary, db_payloads.get('itineraries', []), 'itineraries', db_session=db_session)
    _bulk_insert_rows(StopCall, db_payloads.get('stop_calls', []), 'stop calls', db_session=db_session)
    _bulk_insert_rows(LineFamilyMatch, db_payloads.get('line_family_matches', []), 'line family matches', db_session=db_session)
    _bulk_insert_rows(ItineraryMatch, db_payloads.get('itinerary_matches', []), 'itinerary matches', db_session=db_session)


def import_to_database(db_payloads=None, run_type=PipelineRunType.COMPLETE, *, manifest=None):
    """Stage a complete snapshot and atomically publish it in Postgres.

    Source caches remain an engine concern. Every bundle is a full snapshot, so
    selective ATLAS table reuse is deliberately not part of the wire protocol.
    """
    if db_payloads is None:
        raise ValueError("db_payloads must be provided")
    if run_type != PipelineRunType.COMPLETE:
        raise ValueError("Result bundle imports require a complete snapshot")
    _validate_refresh_payloads(db_payloads)
    _ensure_import_schema_exists(session)
    session.rollback()
    from backend.importing.publication import publish_snapshot
    publish_snapshot(session.get_bind(), db_payloads, _write_rows, manifest=manifest)
    session.expire_all()
    session.close()
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
        
        nodes_with_routes = set(base_data.osm_node_routes)
        osm_with_routes_count = sum(
            1 for unit in osm_stop_units
            if any(str(member.node_id) in nodes_with_routes for member in unit.members)
        )
        osm_route_stats = {'osm_with_routes': osm_with_routes_count}

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
            total_osm_network_wikidata=osm_network_wikidata_count,
            no_nearby_atlas_osm_ids=set(base_data.isolated_osm_ids)
        )

        stats['quality_metrics'] = base_data.quality_metrics

        # Compute problem statistics from DB
        try:
            from backend.importing.session import session
            stats['problems'] = compute_db_stats(session)
        except Exception as e:
            print(f"Warning: Could not compute problem statistics: {e}")

        # Compute route-route statistics from DB route tables
        try:
            from backend.importing.session import session
            stats['route_route_matching'] = compute_route_route_stats(session)
        except Exception as e:
            print(f"Warning: Could not compute route-route statistics: {e}")

        if base_data.atlas_filtering:
            stats['atlas_filtering'] = base_data.atlas_filtering

        filepath = save_stats_to_file(stats)
        print(f"\n==== STATISTICS EXPORTED ====")
        print(f"Stats saved to: {filepath}")

        print(f"Generated at: {stats['generated_at']}")
        print(f"Summary: {stats['summary']['matched_pairs']} matched pairs ({stats['summary']['match_rate_percent']}%)")
        
        return stats
    except Exception as e:
        print(f"Warning: Failed to export stats: {e}")
        return None


def import_bundle(directory):
    """Consume a complete result snapshot without an engine installation."""
    with stage('import.validate_bundle'):
        bundle = read_bundle(directory)
    with stage('import.project'):
        base_data, problems, routes = project_bundle(bundle)
    with stage('import.prepare_rows'):
        payload = build_fast_insert_payloads(base_data, problems, routes)
    with stage('import.load_and_publish'):
        no_nearby = import_to_database(db_payloads=payload, manifest=bundle['manifest'])
    try:
        with stage('import.statistics'):
            _write_gtfs_atlas_stats(base_data.gtfs_atlas_stats)
            export_stats_after_import(base_data, base_data.duplicate_sloid_map, no_nearby)
            from backend.services.data_meta import update_data_meta
            update_data_meta(
                active_run_id=bundle['manifest']['run_id'],
                source_capabilities=bundle['manifest']['metadata'].get('capabilities', []),
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Dataset published, but report metadata needs regeneration')
    return bundle['manifest']


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a versioned transport matching result bundle.")
    parser.add_argument("bundle", help="Directory containing manifest.json and compressed result records")
    args = parser.parse_args()
    import_bundle(args.bundle)
