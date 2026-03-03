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
from sqlalchemy import func, text

# --- Internal modules -------------------------------------------------------
from matching_and_import_db.orchestrator import run_matching
from matching_and_import_db.models import MatchingOutput
from matching_and_import_db.problem_detection.context import ProblemContext
from matching_and_import_db.problem_detection.pipeline import run_problem_pipeline, STOP_PROBLEM_PIPELINE
from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.database.session import session, user_input_session
from matching_and_import_db.database.helpers import (
    make_point_geom,
    safe_value,
    get_osm_node_type,
    ensure_schema_updated,
    validate_coordinates,
    get_from_tags,
    apply_problem_results,
)
from matching_and_import_db.database.route_loader import load_all_route_data
from matching_and_import_db.utils.route_id import normalize_route_id

# --- External models --------------------------------------------------------
from backend.models import StopsMatched, AtlasStop, OsmNode, OsmStopGroup, RouteAtlasStops, RouteOsmStops, RoutesMatched, Problem
from backend.services.stats_export import export_pipeline_stats, save_stats_to_file


def _import_all_osm_nodes(session, all_osm_nodes, problem_ctx):
    """Insert ALL OSM nodes upfront so FK constraints from route_osm_stops are always satisfied."""
    for node in all_osm_nodes:
        record = OsmNode(
            osm_node_id=str(node.node_id),
            osm_local_ref=node.local_ref,
            osm_name=node.name,
            osm_uic_name=node.uic_name,
            osm_uic_ref=node.uic_ref,
            osm_network=node.network,
            osm_operator=node.operator,
            osm_public_transport=node.public_transport,
            osm_railway=node.railway,
            osm_amenity=node.amenity,
            osm_aerialway=node.aerialway,
            osm_node_type=get_osm_node_type(node.tags, is_osm_unmatched=True) if node.tags else None,
            duplicate_group_node_ids=problem_ctx.duplicate_osm_group_map.get(str(node.node_id)),
        )
        session.add(record)
    session.commit()
    print(f"Imported {len(all_osm_nodes)} OSM nodes")


def _import_matched_stops(session, matched_records, problem_ctx, duplicate_sloid_map, processed_sloids, processed_osm_node_ids):
    print("\nDetecting problems and importing matched records...")
    print("  Checks: distance, attributes, duplicates")

    BATCH_SIZE = int(os.getenv('DB_IMPORT_BATCH_SIZE', '5000'))
    _t0 = time.time()
    inserted = 0

    total = len(matched_records)
    for idx, current_match in enumerate(matched_records):
        atlas_lat, atlas_lon = current_match.atlas_node.lat, current_match.atlas_node.lon
        osm_lat, osm_lon = current_match.osm_node.lat, current_match.osm_node.lon

        # Natively evaluate problems using domain components
        current_match.evaluate_problems(problem_ctx, STOP_PROBLEM_PIPELINE)

        sloid = current_match.atlas_node.sloid
        osm_node_id = current_match.osm_node.node_id
        distance_m = current_match.distance_m

        stop_record = StopsMatched(
            sloid=sloid,
            stop_type='matched',
            match_type=current_match.match_type,
            atlas_lat=atlas_lat,
            atlas_lon=atlas_lon,
            osm_node_id=osm_node_id,
            osm_lat=osm_lat,
            osm_lon=osm_lon,
            distance_m=distance_m,
            matching_notes=current_match.notes,
            geom=make_point_geom(atlas_lat, atlas_lon) if atlas_lat is not None and atlas_lon is not None else make_point_geom(osm_lat, osm_lon),
        )
        apply_problem_results(stop_record, current_match.problems)
        session.add(stop_record)

        if sloid and sloid not in processed_sloids:
            atlas_record = AtlasStop(
                sloid=sloid,
                uic_ref=current_match.atlas_node.uic_ref,
                atlas_designation=current_match.atlas_node.designation,
                atlas_designation_official=current_match.atlas_node.designation_official,
                atlas_business_org_abbr=current_match.atlas_node.business_org_abbr,
                duplicate_group_sloids=duplicate_sloid_map.get(str(sloid)) if str(sloid) in duplicate_sloid_map else None,
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)

        if osm_node_id:
            processed_osm_node_ids.add(osm_node_id)

        inserted += 1
        if BATCH_SIZE > 0 and (inserted % BATCH_SIZE) == 0:
            session.commit()
            session.expunge_all()
            elapsed = max(0.001, time.time() - _t0)
            progress = idx + 1
            rate = progress / elapsed
            pct = (progress / total) * 100.0
            eta_s = int((total - progress) / max(rate, 1e-9))
            print(f"  Committed batch: {progress:,}/{total:,} ({pct:.1f}%) | {rate:.1f}/s | ETA {eta_s}s")

    session.commit()
    session.expunge_all()
    print(f"Imported {len(matched_records)} matched records")


def _import_osm_groups(session, osm_group_siblings):
    """Import OSM node groups (platform ↔ stop_position pairs) into the dedicated table."""
    count = 0
    for rep_node_id, (group_type, siblings) in osm_group_siblings.items():
        for sib in siblings:
            session.add(OsmStopGroup(
                representative_node_id=rep_node_id,
                sibling_node_id=sib.node_id,
                group_type=group_type,
                sibling_lat=sib.lat,
                sibling_lon=sib.lon,
            ))
            count += 1
    session.commit()
    print(f"Imported {count} OSM group pairs")

def _import_unmatched_atlas(session, unmatched_records, problem_ctx, duplicate_sloid_map, processed_sloids):
    no_nearby_osm_sloids = set()
    for atlas_node in unmatched_records:
        atlas_lat, atlas_lon = atlas_node.lat, atlas_node.lon

        if atlas_lat == 0.0 and atlas_lon == 0.0:
            continue

        sloid = atlas_node.sloid

        nearest_d = problem_ctx.nearest_osm_distance(atlas_lat, atlas_lon)
        is_isolated = True if nearest_d is None or nearest_d > 50 else False
        if is_isolated and sloid:
             no_nearby_osm_sloids.add(sloid)

        match_type_for_unmatched = 'no_nearby_counterpart' if is_isolated else None

        stop_record = StopsMatched(
            sloid=sloid,
            stop_type='atlas_unmatched',
            match_type=match_type_for_unmatched,
            atlas_lat=atlas_lat,
            atlas_lon=atlas_lon,
            geom=make_point_geom(atlas_lat, atlas_lon),
        )

        # Natively evaluate problems for the purely unmatched Atlas node
        problems = run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, atlas_node)
        apply_problem_results(stop_record, problems)

        session.add(stop_record)

        if sloid and sloid not in processed_sloids:
            atlas_record = AtlasStop(
                sloid=sloid,
                uic_ref=atlas_node.uic_ref,
                atlas_designation=atlas_node.designation,
                atlas_designation_official=atlas_node.designation_official,
                atlas_business_org_abbr=atlas_node.business_org_abbr,
                duplicate_group_sloids=duplicate_sloid_map.get(str(sloid)) if str(sloid) in duplicate_sloid_map else None,
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)

    session.commit()
    return no_nearby_osm_sloids

def _import_unmatched_osm(session, unmatched_osm_records, problem_ctx, processed_osm_node_ids):
    for osm_node in unmatched_osm_records:
        osm_lat, osm_lon = osm_node.lat, osm_node.lon

        if osm_lat == 0.0 and osm_lon == 0.0 and 'lat' not in osm_node.tags:
             continue

        osm_node_id = str(osm_node.node_id)

        stop_record = StopsMatched(
            stop_type='osm_unmatched',
            osm_node_id=osm_node_id,
            osm_lat=osm_lat,
            osm_lon=osm_lon,
            geom=make_point_geom(osm_lat, osm_lon),
        )

        # Natively evaluate problems for the purely unmatched Osm node
        problems = run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, osm_node)
        apply_problem_results(stop_record, problems)

        session.add(stop_record)

        if osm_node_id:
            processed_osm_node_ids.add(osm_node_id)

    session.commit()

def _import_routes(session, all_route_data, known_sloids):
    matched_routes = 0
    routes_to_insert = []
    
    atlas_route_dir_to_sloids = all_route_data.get('atlas_route_dir_to_sloids', {})
    osm_route_dir_to_nodes = all_route_data.get('osm_route_dir_to_nodes', {})
    atlas_line_diruic_to_sloids = all_route_data.get('atlas_line_diruic_to_sloids', {})

    # Pre-build normalized index for ATLAS routes
    atlas_normalized_to_original = {}
    for (atlas_route_id, atlas_direction_id), atlas_info in atlas_route_dir_to_sloids.items():
        norm_id = normalize_route_id(atlas_route_id)
        if norm_id:
            atlas_normalized_to_original.setdefault((norm_id, atlas_direction_id), []).append(
                (atlas_route_id, atlas_info)
            )

    # Track distinct matches to avoid duplicate RoutesMatched records
    seen_route_matches = set()

    for (osm_route_id, direction_id), osm_data in osm_route_dir_to_nodes.items():
        for i, node_id in enumerate(osm_data['nodes']):
            routes_to_insert.append(RouteOsmStops(
                osm_route_id=osm_route_id, direction_id=direction_id, osm_node_id=node_id, stop_sequence=i
            ))
            
        atlas_data = atlas_route_dir_to_sloids.get((osm_route_id, direction_id))
        atlas_matched_route_id = None

        if atlas_data:
            atlas_matched_route_id = osm_route_id
        else:
            osm_route_normalized = normalize_route_id(osm_route_id)
            if osm_route_normalized:
                matches = atlas_normalized_to_original.get((osm_route_normalized, direction_id))
                if matches:
                    atlas_matched_route_id, atlas_data = matches[0]

        if atlas_matched_route_id and (atlas_matched_route_id, osm_route_id) not in seen_route_matches:
            seen_route_matches.add((atlas_matched_route_id, osm_route_id))
            routes_to_insert.append(RoutesMatched(
                atlas_route_id=atlas_matched_route_id,
                osm_route_id=osm_route_id,
                match_type='matched'
            ))
            matched_routes += 1
            
    skipped_sloids = 0
    for (atlas_route_id, direction_id), atlas_data in atlas_route_dir_to_sloids.items():
        for i, sloid in enumerate(atlas_data['sloids']):
            if sloid not in known_sloids:
                skipped_sloids += 1
                continue
            routes_to_insert.append(RouteAtlasStops(
                atlas_route_id=atlas_route_id, direction_id=direction_id, sloid=sloid, stop_sequence=i
            ))

    for (line_name, direction_uic), atlas_data in atlas_line_diruic_to_sloids.items():
        for i, sloid in enumerate(atlas_data['sloids']):
            if sloid not in known_sloids:
                skipped_sloids += 1
                continue
            routes_to_insert.append(RouteAtlasStops(
                atlas_route_id=line_name, direction_id=direction_uic, sloid=sloid, stop_sequence=i
            ))

    if skipped_sloids:
        print(f"  Skipped {skipped_sloids} route-atlas entries (SLOID not in atlas_stops)")
    
    session.bulk_save_objects(routes_to_insert)
    session.commit()
    print(f"Route import completed: {matched_routes} ATLAS↔OSM route pairs linked")

def _print_problem_summary(session):
    total_stops = session.query(StopsMatched).count()
    distance_problems = session.query(Problem).filter(Problem.problem_type == 'distance').count()
    isolated_problems = session.query(Problem).filter(Problem.problem_type == 'unmatched').count()
    attributes_problems = session.query(Problem).filter(Problem.problem_type == 'attributes').count()
    duplicates_problems = session.query(Problem).filter(Problem.problem_type == 'duplicates').count()
    
    multiple_problems = session.query(Problem.stop_id).group_by(Problem.stop_id).having(func.count(Problem.stop_id) > 1).count()
    stops_with_problems = session.query(func.count(func.distinct(Problem.stop_id))).scalar()
    clean_entries = total_stops - stops_with_problems

    print("\n==== PROBLEM DETECTION SUMMARY ====")
    print(f"Total stops imported: {total_stops}")
    print(f"Distance problems: {distance_problems}")
    print(f"Unmatched problems: {isolated_problems}")
    print(f"Attributes problems: {attributes_problems}")
    print(f"Duplicates problems: {duplicates_problems}")
    print(f"Entries with multiple problems: {multiple_problems}")
    print(f"Clean entries (no problems): {clean_entries}")

# --------------------------
# Data Import Function
# --------------------------
def import_to_database(base_data: MatchingOutput):
    """
    Fully refresh the database "Import DB" .
    """
    ensure_schema_updated()

    print("Truncating all database tables...")
    session.execute(text("TRUNCATE TABLE atlas_stops, osm_nodes, osm_stop_groups, route_atlas_stops, route_osm_stops CASCADE"))
    session.execute(text("TRUNCATE TABLE routes_matched CASCADE"))
    session.execute(text("TRUNCATE TABLE problems, stops_matched CASCADE"))
    session.commit()

    try:
        _preloaded_osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
    except Exception:
        _preloaded_osm_routes_df = None

    all_route_data = load_all_route_data(osm_routes_df=_preloaded_osm_routes_df)

    processed_sloids = set()
    processed_osm_node_ids = set()

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

    problem_ctx = ProblemContext.build(base_data)

    duplicate_sloid_map = base_data.duplicate_sloid_map

    # 0. Import ALL OSM nodes upfront (satisfies route_osm_stops FK by construction)
    _import_all_osm_nodes(session, base_data.all_osm_nodes, problem_ctx)

    # 0b. Import OSM groups (platform ↔ stop_position pairs) into dedicated table
    _import_osm_groups(session, base_data.osm_group_siblings)

    # 1. Import Matched
    _import_matched_stops(session, base_data.matched, problem_ctx, duplicate_sloid_map, processed_sloids, processed_osm_node_ids)

    # 2. Import Unmatched Atlas
    no_nearby_osm_sloids = _import_unmatched_atlas(session, base_data.unmatched_atlas, problem_ctx, duplicate_sloid_map, processed_sloids)

    # 3. Import Unmatched OSM
    _import_unmatched_osm(session, base_data.unmatched_osm, problem_ctx, processed_osm_node_ids)

    # 4. Import Routes
    _import_routes(session, all_route_data, processed_sloids)

    _print_problem_summary(session)

    session.close()
    print("Data import complete!")

    return no_nearby_osm_sloids


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
        
        # Calculate total OSM nodes (matched + unmatched)
        matched_osm_ids = {r.osm_node.node_id for r in matched_records if getattr(r, 'osm_node', None) and r.osm_node.node_id}
        total_osm = len(matched_osm_ids) + len(unmatched_osm)
        
        # Calculate OSM route stats
        osm_with_routes_count = 0
        unmatched_with_routes_count = 0
        try:
            routes_path = "data/processed/osm_nodes_with_routes.csv"
            if os.path.exists(routes_path):
                routes_df = pd.read_csv(routes_path)
                if 'node_id' in routes_df.columns:
                    osm_with_routes_count = routes_df['node_id'].nunique()
                else:
                    osm_with_routes_count = len(routes_df)
                
                nodes_with_routes = set(routes_df['node_id'].astype(str).unique())
                unmatched_with_routes_count = sum(
                    1 for node in unmatched_osm 
                    if str(getattr(node, 'node_id', None)) in nodes_with_routes
                )
        except Exception as e:
            print(f"Warning: Could not calculate OSM route stats: {e}")

        # Calculate ATLAS route stats
        atlas_route_stats = {}
        try:
            unified_path = "data/processed/atlas_routes_unified.csv"
            if os.path.exists(unified_path):
                df_unified = pd.read_csv(unified_path, dtype=str)
                gtfs_matches = df_unified[df_unified['source'] == 'gtfs']['sloid'].nunique()
                hrdf_matches = df_unified[df_unified['source'] == 'hrdf']['sloid'].nunique()
                any_route = df_unified['sloid'].nunique()
                
                atlas_route_stats = {
                    'atlas_total': total_atlas if total_atlas else 0, # Passed earlier
                    'atlas_gtfs_matches': gtfs_matches,
                    'atlas_hrdf_matches': hrdf_matches,
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
            total_atlas_platforms=total_atlas,
            total_osm_nodes=total_osm,
            atlas_route_stats=atlas_route_stats,
            osm_route_stats=osm_route_stats
        )
        
        stats['unmatched_analysis']['osm']['with_routes'] = unmatched_with_routes_count
        
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
    
    print("Importing data into the database...")
    no_nearby_sloids = import_to_database(result)

    export_stats_after_import(result, result.duplicate_sloid_map, no_nearby_sloids)
    print("Process completed successfully!")
