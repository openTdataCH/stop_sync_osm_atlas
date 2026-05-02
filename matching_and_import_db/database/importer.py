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
from collections import Counter

import pandas as pd
from sqlalchemy import func, text, inspect, insert

# --- Internal modules -------------------------------------------------------
from matching_and_import_db.orchestrator import run_matching
from matching_and_import_db.models import MatchingOutput
from matching_and_import_db.problem_detection.context import ProblemContext
from matching_and_import_db.problem_detection.pipeline import run_problem_pipeline, STOP_PROBLEM_PIPELINE
from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.database.session import session
from matching_and_import_db.database.helpers import (
    make_point_geom,
    safe_value,
    get_osm_node_type,
    validate_coordinates,
    get_from_tags,
    apply_problem_results,
)
from matching_and_import_db.database.route_loader import load_all_route_data, build_route_write_payload

# --- External models --------------------------------------------------------
from backend.models import StopsMatched, AtlasStop, OsmNode, OsmStop, OsmStopMember, RouteAtlasStops, RouteOsmStops, RoutesMatched, Problem, AtlasRoute, AtlasRouteDirection, OsmRoute, OsmRouteTag
from backend.services.stats_export import (
    export_pipeline_stats,
    save_stats_to_file,
    compute_db_stats,
    compute_route_route_stats,
)


def _ensure_import_schema_exists(db_session) -> None:
    """Fail fast with actionable guidance if import tables are missing."""
    required_tables = [
        'atlas_stops',
        'osm_nodes',
        'osm_stops',
        'osm_stop_members',
        'route_atlas_stops',
        'route_osm_stops',
        'routes_matched',
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


def precompute_problem_artifacts(base_data: MatchingOutput) -> dict:
    """Precompute problem detection so maintenance phase only writes to DB."""
    problem_ctx = ProblemContext.build(base_data)

    matched_problem_map = {}
    for current_match in getattr(base_data, 'matched', []):
        current_match.evaluate_problems(problem_ctx, STOP_PROBLEM_PIPELINE)
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
            'problems': run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, atlas_node),
        }

    unmatched_osm_problem_map = {}
    for osm_node in getattr(base_data, 'unmatched_osm', []):
        osm_lat, osm_lon = osm_node.lat, osm_node.lon
        if osm_lat == 0.0 and osm_lon == 0.0 and 'lat' not in osm_node.tags:
            continue
        unmatched_osm_problem_map[id(osm_node)] = run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, osm_node)

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
    route_write_payload = build_route_write_payload(route_data, importable_sloids)
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
            current_match.evaluate_problems(problem_ctx, STOP_PROBLEM_PIPELINE)
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
            atlas_stop_dicts.append({
                'sloid': sloid,
                'uic_ref': current_match.atlas_node.uic_ref,
                'atlas_designation': current_match.atlas_node.designation,
                'atlas_designation_official': current_match.atlas_node.designation_official,
                'atlas_business_org_abbr': current_match.atlas_node.business_org_abbr,
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
            problems = run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, atlas_node)

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
            atlas_stop_dicts.append({
                'sloid': sloid,
                'uic_ref': atlas_node.uic_ref,
                'atlas_designation': atlas_node.designation,
                'atlas_designation_official': atlas_node.designation_official,
                'atlas_business_org_abbr': atlas_node.business_org_abbr,
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
            problems = run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, osm_node)

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

    # ---- 4. Synthetic OSM nodes referenced by route members ----
    route_artifacts = route_artifacts or {}
    all_route_data = route_artifacts.get('all_route_data')
    if all_route_data is None:
        all_route_data = load_all_route_data()

    known_osm_node_ids = {d['osm_node_id'] for d in osm_node_dicts}

    osm_route_dir_to_nodes = all_route_data.get('osm_route_dir_to_nodes', {})
    route_node_ids = {
        str(node_id)
        for _, osm_data in osm_route_dir_to_nodes.items()
        for node_id in osm_data.get('nodes', [])
        if node_id
    }
    synthetic_node_ids = sorted(route_node_ids - known_osm_node_ids)
    if synthetic_node_ids:
        for node_id in synthetic_node_ids:
            osm_node_dicts.append({'osm_node_id': node_id})
        print(f"Prepared {len(synthetic_node_ids)} synthetic OSM nodes referenced by routes")

    # ---- 5. Route rows ----
    route_write_payload = route_artifacts.get('route_write_payload')
    if route_write_payload is None:
        importable_sloids = {d['sloid'] for d in atlas_stop_dicts}
        route_write_payload = build_route_write_payload(all_route_data, importable_sloids)

    route_osm_dicts_raw = route_write_payload.get('route_osm_stops', [])
    known_osm_node_ids = {
        str(d.get('osm_node_id'))
        for d in osm_node_dicts
        if d.get('osm_node_id') is not None
    }
    route_osm_dicts = [
        row for row in route_osm_dicts_raw
        if row.get('osm_node_id') is not None and str(row.get('osm_node_id')) in known_osm_node_ids
    ]
    skipped_route_osm_nodes = len(route_osm_dicts_raw) - len(route_osm_dicts)
    route_atlas_dicts = route_write_payload.get('route_atlas_stops', [])
    routes_matched_dicts = route_write_payload.get('routes_matched', [])
    atlas_routes_dicts = route_write_payload.get('atlas_routes', [])
    atlas_dirs_dicts = route_write_payload.get('atlas_route_directions', [])
    osm_routes_dicts = route_write_payload.get('osm_routes', [])
    osm_tags_dicts = route_write_payload.get('osm_route_tags', [])

    skipped_sloids = int(route_write_payload.get('skipped_sloids', 0) or 0)
    matched_routes = int(route_write_payload.get('matched_routes', 0) or 0)

    if skipped_sloids:
        print(f"  Skipped {skipped_sloids} route-atlas entries (SLOID not in atlas_stops)")
    if skipped_route_osm_nodes:
        print(
            f"  Skipped {skipped_route_osm_nodes} route-OSM entries "
            "(OSM node_id not in osm_nodes)"
        )

    # ---- Summary ----
    total_matched = sum(1 for d in stops_matched_dicts if d['stop_type'] == 'matched')
    print(f"Payload precompute complete: {len(stops_matched_dicts)} stop rows, "
          f"{len(osm_node_dicts)} OSM nodes, {len(atlas_stop_dicts)} ATLAS stops, "
          f"{len(problem_rows)} problem rows, {len(route_osm_dicts)} route-OSM rows")

    return {
        'osm_nodes': osm_node_dicts,
        'osm_stops': osm_stop_dicts,
        'osm_stop_members': osm_stop_member_dicts,
        'stops_matched': stops_matched_dicts,
        'atlas_stops': atlas_stop_dicts,
        'problem_rows': problem_rows,
        'route_osm_stops': route_osm_dicts,
        'route_atlas_stops': route_atlas_dicts,
        'routes_matched': routes_matched_dicts,
        'atlas_routes': atlas_routes_dicts,
        'atlas_route_directions': atlas_dirs_dicts,
        'osm_routes': osm_routes_dicts,
        'osm_route_tags': osm_tags_dicts,
        'route_problems': route_write_payload.get('route_problems', []),
        'matched_routes': route_write_payload.get('matched_routes', 0),
        'no_nearby_osm_sloids': no_nearby_osm_sloids,
    }


# ---------------------------------------------------------------------------
# Fast DB writer — runs INSIDE the blocking maintenance window
# ---------------------------------------------------------------------------

_BULK_BATCH = int(os.getenv('DB_IMPORT_BATCH_SIZE', '10000'))


def import_to_database(
    db_payloads: dict | None = None,
):
    """Fully refresh the database "Import DB".

    Expects precomputed payloads so the write phase stays focused on TRUNCATE
    plus bulk INSERT work.
    """
    _ensure_import_schema_exists(session)

    if db_payloads is None:
        raise ValueError("db_payloads must be provided")

    # ---- TRUNCATE all tables ----
    print("Truncating all database tables...")
    session.execute(text("TRUNCATE TABLE atlas_stops, osm_nodes, osm_stops, osm_stop_members, route_atlas_stops, route_osm_stops CASCADE"))
    session.execute(text("TRUNCATE TABLE atlas_routes, atlas_route_directions, osm_routes, osm_route_tags, routes_matched, route_problems CASCADE"))
    session.execute(text("TRUNCATE TABLE problems, stops_matched CASCADE"))
    session.commit()

    # ---- Bulk insert: OSM nodes ----
    osm_node_rows = db_payloads['osm_nodes']
    if osm_node_rows:
        for i in range(0, len(osm_node_rows), _BULK_BATCH):
            session.execute(insert(OsmNode), osm_node_rows[i:i + _BULK_BATCH])
        session.commit()
        print(f"Imported {len(osm_node_rows)} OSM nodes")

    # ---- Bulk insert: OSM stop units ----
    osm_stop_rows = db_payloads['osm_stops']
    if osm_stop_rows:
        for i in range(0, len(osm_stop_rows), _BULK_BATCH):
            session.execute(insert(OsmStop), osm_stop_rows[i:i + _BULK_BATCH])
        session.commit()
        print(f"Imported {len(osm_stop_rows)} OSM stop units")

    # ---- Bulk insert: OSM stop members ----
    osm_member_rows = db_payloads['osm_stop_members']
    if osm_member_rows:
        for i in range(0, len(osm_member_rows), _BULK_BATCH):
            session.execute(insert(OsmStopMember), osm_member_rows[i:i + _BULK_BATCH])
        session.commit()
        print(f"Imported {len(osm_member_rows)} OSM stop members")

    # ---- Bulk insert: stops_matched (strip internal _idx before insert) ----
    stops_rows = db_payloads['stops_matched']
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

    # ---- Bulk insert: atlas_stops ----
    atlas_rows = db_payloads['atlas_stops']
    if atlas_rows:
        for i in range(0, len(atlas_rows), _BULK_BATCH):
            session.execute(insert(AtlasStop), atlas_rows[i:i + _BULK_BATCH])
        session.commit()
        print(f"Imported {len(atlas_rows)} ATLAS stops")

    # ---- Bulk insert: route tables ----
    atlas_routes = db_payloads.get('atlas_routes', [])
    if atlas_routes:
        for i in range(0, len(atlas_routes), _BULK_BATCH):
            session.execute(insert(AtlasRoute), atlas_routes[i:i + _BULK_BATCH])
        session.commit()

    atlas_route_dirs = db_payloads.get('atlas_route_directions', [])
    if atlas_route_dirs:
        for i in range(0, len(atlas_route_dirs), _BULK_BATCH):
            session.execute(insert(AtlasRouteDirection), atlas_route_dirs[i:i + _BULK_BATCH])
        session.commit()

    osm_routes = db_payloads.get('osm_routes', [])
    if osm_routes:
        for i in range(0, len(osm_routes), _BULK_BATCH):
            session.execute(insert(OsmRoute), osm_routes[i:i + _BULK_BATCH])
        session.commit()

    osm_route_tags = db_payloads.get('osm_route_tags', [])
    if osm_route_tags:
        for i in range(0, len(osm_route_tags), _BULK_BATCH):
            session.execute(insert(OsmRouteTag), osm_route_tags[i:i + _BULK_BATCH])
        session.commit()

    route_osm = db_payloads.get('route_osm_stops', [])
    if route_osm:
        for i in range(0, len(route_osm), _BULK_BATCH):
            session.execute(insert(RouteOsmStops), route_osm[i:i + _BULK_BATCH])
        session.commit()

    route_atlas = db_payloads.get('route_atlas_stops', [])
    if route_atlas:
        for i in range(0, len(route_atlas), _BULK_BATCH):
            session.execute(insert(RouteAtlasStops), route_atlas[i:i + _BULK_BATCH])
        session.commit()

    routes_matched = db_payloads.get('routes_matched', [])
    if routes_matched:
        for i in range(0, len(routes_matched), _BULK_BATCH):
            session.execute(insert(RoutesMatched), routes_matched[i:i + _BULK_BATCH])
        session.commit()

    route_problems = db_payloads.get('route_problems', [])
    if route_problems:
        from backend.models import RouteProblem
        for i in range(0, len(route_problems), _BULK_BATCH):
            session.execute(insert(RouteProblem), route_problems[i:i + _BULK_BATCH])
        session.commit()
        print(f"Imported {len(route_problems)} route problems")

    matched_routes = db_payloads.get('matched_routes', 0)
    print(f"Route import completed: {matched_routes} ATLAS↔OSM route pairs linked")

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
            routes_path = "data/processed/osm_nodes_with_routes.csv"
            if os.path.exists(routes_path):
                routes_df = pd.read_csv(routes_path)
                nodes_with_routes = set(routes_df['node_id'].astype(str).unique())

                osm_with_routes_count = sum(
                    1 for stop_unit in getattr(base_data, 'osm_stop_units', [])
                    if any(str(member.node_id) in nodes_with_routes for member in stop_unit.members)
                )
        except Exception as e:
            print(f"Warning: Could not calculate OSM route stats: {e}")

        # Calculate ATLAS route stats
        atlas_route_stats = {}
        try:
            gtfs_path = "data/processed/atlas_routes_gtfs.csv"
            if os.path.exists(gtfs_path):
                df_gtfs = pd.read_csv(gtfs_path, dtype=str)
                gtfs_rows = df_gtfs.copy()
                gtfs_rows = gtfs_rows[gtfs_rows['route_id'].notna()] if 'route_id' in gtfs_rows.columns else gtfs_rows

                gtfs_matches = gtfs_rows['sloid'].nunique() if 'sloid' in gtfs_rows.columns else 0
                any_route = gtfs_matches
                
                atlas_route_stats = {
                    'atlas_total': total_atlas if total_atlas else 0, # Passed earlier
                    'atlas_gtfs_matches': gtfs_matches,
                    'atlas_with_routes': any_route
                }
        except Exception as e:
            print(f"Warning: Could not calculate ATLAS route stats: {e}")
        
        osm_route_stats = {
            'osm_with_routes': osm_with_routes_count
        }
        
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
            atlas_route_stats=atlas_route_stats,
            osm_route_stats=osm_route_stats,
            osm_nodes_with_routes=nodes_with_routes if 'nodes_with_routes' in locals() else set()
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

        # Preserve independent stats generated by other pipeline stages (like atlas_filtering)
        from backend.services.stats_export import load_stats_from_file
        existing_stats = load_stats_from_file() or {}
        for k, v in existing_stats.items():
            if k not in stats:
                stats[k] = v

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
