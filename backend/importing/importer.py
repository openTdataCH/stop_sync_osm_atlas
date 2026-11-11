"""
Database import orchestrator.

Projects a validated result bundle into the review app's PostGIS schema.
Matching, grouping, route comparison and diagnostic decisions are already
complete in the bundle. Only application persistence happens here, plus one
derived review aid: each itinerary's best stop overlap with the other source.
"""
import os
import argparse
import ast
import json
from collections import Counter
from typing import Any

from sqlalchemy import inspect, text

# --- Internal modules -------------------------------------------------------
from backend.importing.session import session
from backend.importing.bulk import copy_rows
from backend.importing.helpers import safe_value, get_osm_node_type
from backend.importing.projection import project_bundle
from backend.importing.bundle import read_bundle
from backend.importing.progress import progress_stage, report
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
    ItineraryBestOverlap,
)
from backend.services.route_comparison import compute_best_overlaps
from backend.services.stats_export import export_pipeline_stats, save_stats_to_file


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
        'itinerary_best_overlaps',
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


def _remember_atlas_stop(atlas_stops_by_sloid: dict, operator_rows_by_abbr: dict[str, dict], atlas_node, duplicate_sloid_map) -> None:
    """Keep one ATLAS stop row per sloid, the first one seen, with its duplicate group and operator."""
    sloid = atlas_node.sloid
    if not sloid or sloid in atlas_stops_by_sloid:
        return
    dup_group = duplicate_sloid_map.get(str(sloid))
    _remember_atlas_operator(operator_rows_by_abbr, atlas_node)
    atlas_stops_by_sloid[sloid] = {
        'sloid': sloid,
        'uic_ref': atlas_node.uic_ref,
        'atlas_designation': atlas_node.designation,
        'atlas_designation_official': atlas_node.designation_official,
        'atlas_business_org_abbr': _normalize_text(atlas_node.business_org_abbr),
        'representative_sloid': dup_group[0] if dup_group and str(sloid) != dup_group[0] else None,
        'duplicate_group_sloids': dup_group,
    }


def _write_gtfs_atlas_stats(stats_payload: dict[str, object]) -> None:
    # Nothing in the application reads this file. The engine reads
    # <workspace>/data/gtfs_atlas_stats.json when its source metadata lacks the
    # GTFS identity statistics, and in Docker the workspace is this directory.
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
# Payload builder — runs before staging; readers keep the published snapshot
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
    for node in [*base_data.all_osm_nodes, *getattr(base_data, 'disused_osm', ())]:
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
            'osm_node_type': get_osm_node_type(node.tags) if node.tags else None,
            'duplicate_group_node_ids': problem_ctx.duplicate_osm_group_map.get(str(node.node_id)),
            'osm_lifecycle': getattr(node, 'lifecycle', None),
            'osm_tags': node.tags or None,
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

    # ---- Track processed osm_node_ids ----
    processed_osm_node_ids = set()

    # ---- 1. Matched stops ----
    stops_matched_dicts = []
    atlas_operator_rows_by_abbr = {}
    atlas_stops_by_sloid = {}
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
            'geom': geom_wkt,
        })

        for p in problems:
            problem_rows.append((stop_idx, p.problem_type, p.priority))

        _remember_atlas_stop(atlas_stops_by_sloid, atlas_operator_rows_by_abbr, current_match.atlas_node, duplicate_sloid_map)

        if osm_node_id:
            processed_osm_node_ids.add(osm_node_id)

        stop_idx += 1

    # ---- 2. Unmatched ATLAS ----
    for atlas_node in base_data.unmatched_atlas:
        atlas_lat, atlas_lon = atlas_node.lat, atlas_node.lon

        sloid = atlas_node.sloid
        precomputed_entry = unmatched_atlas_problem_map.get(id(atlas_node))

        if precomputed_entry is None:
            raise ValueError(f"Missing exported unmatched-source result: {sloid}")
        match_type_for_unmatched = precomputed_entry.get('match_type')
        problems = precomputed_entry.get('problems', [])

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
            'geom': geom_wkt,
        })

        for p in problems:
            problem_rows.append((stop_idx, p.problem_type, p.priority))

        _remember_atlas_stop(atlas_stops_by_sloid, atlas_operator_rows_by_abbr, atlas_node, duplicate_sloid_map)

        stop_idx += 1

    # ---- 3. Unmatched and disused OSM ----
    two_sided_middles_effectively_matched = set(base_data.effectively_matched_osm_ids)
    disused_osm = list(getattr(base_data, 'disused_osm', ()))
    disused_osm_ids = {str(node.node_id) for node in disused_osm}

    for osm_node in [*base_data.unmatched_osm, *disused_osm]:
        osm_lat, osm_lon = osm_node.lat, osm_node.lon

        osm_node_id = str(osm_node.node_id)
        stop_type = 'osm_unmatched'
        if osm_node_id in two_sided_middles_effectively_matched:
            stop_type = 'effectively_matched'
        elif osm_node_id in disused_osm_ids:
            stop_type = 'osm_disused'

        problems = unmatched_osm_problem_map[id(osm_node)]

        geom_wkt = _make_point_wkt(osm_lat, osm_lon)

        stops_matched_dicts.append({
            '_idx': stop_idx,
            'sloid': None,
            'stop_type': stop_type,
            # The bundle has no match for these elements, not even for an effectively
            # matched middle, so they have no match type; stop_type tells them apart.
            'match_type': None,
            'atlas_lat': None,
            'atlas_lon': None,
            'osm_node_id': osm_node_id,
            'osm_lat': osm_lat,
            'osm_lon': osm_lon,
            'distance_m': None,
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

    # Review aid, not a match decision: each itinerary's highest stop overlap
    # with any itinerary of the other source. Stored so route cards need no
    # per-request scan of every itinerary.
    with stage('import.itinerary_best_overlaps', itineraries=len(itinerary_dicts)):
        itinerary_best_overlap_dicts = compute_best_overlaps(line_family_dicts, itinerary_dicts, stop_call_dicts)

    unknown_stop_references = int(route_write_payload.get('unknown_source_stop_references', 0) or 0)

    if unknown_stop_references:
        print(f"  {unknown_stop_references} source stop calls reference stops outside this bundle")

    atlas_operator_dicts = sorted(
        atlas_operator_rows_by_abbr.values(),
        key=lambda row: row['atlas_business_org_abbr'],
    )
    atlas_stop_dicts = list(atlas_stops_by_sloid.values())
    importable_sloids = set(atlas_stops_by_sloid)
    gtfs_stop_dicts = base_data.gtfs_stops
    gtfs_identity_resolution_dicts = base_data.gtfs_atlas_state
    gtfs_identity_resolution_dicts = _filter_gtfs_identity_rows_to_known_sloids(
        gtfs_identity_resolution_dicts,
        importable_sloids,
    )

    # ---- Summary ----
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
        'itinerary_best_overlaps': itinerary_best_overlap_dicts,
        'matched_routes': route_write_payload.get('matched_routes', 0),
    }


# ---------------------------------------------------------------------------
# DB writer — loads an isolated staging schema while public tables remain readable
# ---------------------------------------------------------------------------

_BULK_BATCH = int(os.getenv('DB_IMPORT_BATCH_SIZE', '10000'))


def _bulk_insert_rows(db_session, model, rows: list[dict], label: str) -> None:
    """COPY rows into the staging schema of ``db_session``."""
    if not rows:
        return
    with stage('import.table', table=model.__tablename__, rows=len(rows)):
        for i in range(0, len(rows), _BULK_BATCH):
            copy_rows(db_session, model, rows[i:i + _BULK_BATCH])
    print(f"Imported {len(rows)} {label}")


# Bundle sections whose row counts must not collapse between two publications.
GUARDED_COUNTS = (('source_stops', 'ATLAS platforms'), ('osm_nodes', 'OSM elements'), ('matches', 'matches'))


def _max_drop_percent() -> float:
    value = float(os.getenv('PIPELINE_MAX_DROP_PERCENT', '20'))
    if not 0 <= value <= 100:
        raise ValueError('PIPELINE_MAX_DROP_PERCENT must be between 0 and 100')
    return value


def _published_manifest() -> dict | None:
    try:
        return session.execute(text("SELECT manifest FROM dataset_publication WHERE id = 1")).scalar()
    finally:
        session.rollback()


def check_against_published(manifest: dict, published: dict | None, max_drop_percent: float) -> None:
    """Refuse a snapshot that lost more than ``max_drop_percent`` of a published count.

    Broken inputs often still parse, but yield far fewer records; this keeps
    such a run from replacing a good dataset.
    """
    if not published:
        return
    for section, label in GUARDED_COUNTS:
        before = (published.get('files', {}).get(section) or {}).get('rows') or 0
        after = manifest['files'][section]['rows']
        if before and (before - after) * 100 > max_drop_percent * before:
            raise ValueError(f"Refused to publish: {label} fell from {before:,} to {after:,}, "
                             f"more than the {max_drop_percent:g}% allowed")


def _validate_refresh_payloads(db_payloads: dict) -> None:
    """Refuse destructive refreshes that would publish an empty map."""
    if not db_payloads.get('stops_matched'):
        raise RuntimeError(
            "Refusing to refresh import DB: payload contains no stops_matched rows. "
            "This usually means matching/precompute produced an empty result and the "
            "previous public data should be preserved."
        )


def _write_rows(db_session, db_payloads):
    _bulk_insert_rows(db_session, OsmNode, db_payloads.get('osm_nodes', []), 'OSM nodes')
    _bulk_insert_rows(db_session, OsmStop, db_payloads.get('osm_stops', []), 'OSM stop units')
    _bulk_insert_rows(db_session, OsmStopMember, db_payloads.get('osm_stop_members', []), 'OSM stop members')
    _bulk_insert_rows(db_session, AtlasOperator, db_payloads.get('atlas_operators', []), 'ATLAS operators')
    _bulk_insert_rows(db_session, AtlasStop, db_payloads.get('atlas_stops', []), 'ATLAS stops')
    _bulk_insert_rows(db_session, GtfsStopRaw, db_payloads.get('gtfs_stops_raw', []), 'GTFS raw stops')
    _bulk_insert_rows(db_session, GtfsStopIdentityResolution, db_payloads.get('gtfs_stop_identity_resolution', []),
                      'GTFS identity-resolution rows')
    # The staging tables are new and empty, so stop rows get explicit IDs in
    # payload order, and problems can reference them without a round trip.
    stops_rows = db_payloads.get('stops_matched', [])
    stop_idx_to_db_id = {row['_idx']: db_id for db_id, row in enumerate(stops_rows, 1)}
    _bulk_insert_rows(db_session, StopsMatched,
                      [{**{k: v for k, v in row.items() if k != '_idx'}, 'id': stop_idx_to_db_id[row['_idx']]}
                       for row in stops_rows],
                      'stops_matched rows')
    problems = [{'stop_id': stop_idx_to_db_id[idx], 'problem_type': kind, 'priority': priority}
                for idx, kind, priority in db_payloads.get('problem_rows', []) if idx in stop_idx_to_db_id]
    _bulk_insert_rows(db_session, Problem, problems, 'problem rows')
    _bulk_insert_rows(db_session, AtlasLineFamily, db_payloads.get('atlas_line_families', []), 'ATLAS line families')
    _bulk_insert_rows(db_session, OsmRouteRelation, db_payloads.get('osm_route_relations', []), 'OSM route relations')
    _bulk_insert_rows(db_session, LineFamily, db_payloads.get('line_families', []), 'line families')
    _bulk_insert_rows(db_session, Itinerary, db_payloads.get('itineraries', []), 'itineraries')
    _bulk_insert_rows(db_session, StopCall, db_payloads.get('stop_calls', []), 'stop calls')
    _bulk_insert_rows(db_session, LineFamilyMatch, db_payloads.get('line_family_matches', []), 'line family matches')
    _bulk_insert_rows(db_session, ItineraryMatch, db_payloads.get('itinerary_matches', []), 'itinerary matches')
    _bulk_insert_rows(db_session, ItineraryBestOverlap, db_payloads.get('itinerary_best_overlaps', []),
                      'itinerary best overlaps')


def import_to_database(
    db_payloads=None,
    *,
    manifest=None,
    progress_callback=None,
    stage_event_callback=None,
):
    """Stage a complete snapshot and atomically publish it in Postgres.

    Source caches remain an engine concern. Every bundle is a full snapshot, so
    selective ATLAS table reuse is deliberately not part of the wire protocol.
    """
    if db_payloads is None:
        raise ValueError("db_payloads must be provided")
    _validate_refresh_payloads(db_payloads)
    _ensure_import_schema_exists(session)
    session.rollback()
    from backend.importing.publication import publish_snapshot
    publish_snapshot(
        session.get_bind(),
        db_payloads,
        _write_rows,
        manifest=manifest,
        progress_callback=progress_callback,
        stage_event_callback=stage_event_callback,
    )
    session.expire_all()
    session.close()


def export_stats_after_import(base_data):
    """Write data/stats.json for the snapshot just published."""
    # A two-sided stop middle whose two sides are matched counts as matched, not unmatched.
    effectively_matched = {str(node_id) for node_id in base_data.effectively_matched_osm_ids}
    stats = export_pipeline_stats(
        session,
        matched_records=base_data.matched,
        unmatched_osm=[node for node in base_data.unmatched_osm if str(node.node_id) not in effectively_matched],
        isolated_osm_ids={str(node_id) for node_id in base_data.isolated_osm_ids},
        osm_stop_units=base_data.osm_stop_units,
        osm_nodes_with_routes=set(base_data.osm_node_routes),
        gtfs_atlas_stats=base_data.gtfs_atlas_stats,
    )
    stats['quality_metrics'] = base_data.quality_metrics
    if base_data.atlas_filtering:
        stats['atlas_filtering'] = base_data.atlas_filtering

    filepath = save_stats_to_file(stats)
    print(f"Stats saved to {filepath} at {stats['stats_computed_at']}: "
          f"{stats['summary']['matched_pairs']} matched pairs ({stats['summary']['match_rate_percent']}%)")
    return stats


class PublishedDatasetError(RuntimeError):
    """Publication committed, but its derived analytics need regeneration."""

    def __init__(self, manifest, error):
        self.manifest = manifest
        super().__init__(f"Dataset published, but analytics need regeneration: {error}")


def import_bundle(directory, *, progress_callback=None, stage_event_callback=None):
    """Consume a complete result snapshot without an engine installation."""
    report(progress_callback, 'database', 'Validating the result bundle')
    with progress_stage('database.validate', stage_event_callback):
        with stage('import.validate_bundle'):
            bundle = read_bundle(directory)
            check_against_published(bundle['manifest'], _published_manifest(), _max_drop_percent())
    report(progress_callback, 'database', 'Preparing application records')
    with progress_stage('database.prepare', stage_event_callback):
        with stage('import.project'):
            base_data, problems, routes = project_bundle(bundle)
        with stage('import.prepare_rows'):
            payload = build_fast_insert_payloads(base_data, problems, routes)
    report(progress_callback, 'database', 'Loading and indexing the staged database')
    with stage('import.load_and_publish'):
        import_to_database(
            db_payloads=payload,
            manifest=bundle['manifest'],
            progress_callback=progress_callback,
            stage_event_callback=stage_event_callback,
        )
    try:
        report(progress_callback, 'publish', 'Generating analytics for the published dataset')
        with progress_stage('publish.analytics', stage_event_callback):
            with stage('import.statistics'):
                from backend.services.data_meta import record_bundle_metadata
                record_bundle_metadata(bundle['manifest'])
                _write_gtfs_atlas_stats(base_data.gtfs_atlas_stats)
                if export_stats_after_import(base_data) is None:
                    raise RuntimeError("Analytics export returned no result")
    except Exception as exc:
        raise PublishedDatasetError(bundle['manifest'], exc) from exc
    return bundle['manifest']


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a versioned transport matching result bundle.")
    parser.add_argument("bundle", help="Directory containing manifest.json and compressed result records")
    args = parser.parse_args()
    import_bundle(args.bundle)
