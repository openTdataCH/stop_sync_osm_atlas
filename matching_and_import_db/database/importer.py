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
from matching_and_import_db.problem_detection import (
    ProblemContext,
    run_problem_pipeline,
    STOP_PROBLEM_PIPELINE,
)
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
from backend.models import StopsMatched, AtlasStop, OsmNode, RouteAtlasStops, RouteOsmStops, RoutesMatched, Problem
from backend.services.import_persistence import (
    apply_persistent_solutions as apply_persistent_solutions_service,
)
from backend.services.stats_export import export_pipeline_stats, save_stats_to_file


# --------------------------
# Data Import Function
# --------------------------
def import_to_database(base_data, duplicate_sloid_map, run_phase1=True, run_phase2=True, run_phase3=True):
    """
    Fully refresh the database, inserting data into the new normalized schema:
      - Core data into `stops`
      - Detailed ATLAS data into `atlas_stops`
      - Detailed OSM data into `osm_nodes`
      - Route and direction information into `routes_and_directions`
      - Automatic problem detection and flagging
    """
    # Ensure database schema is updated before importing
    ensure_schema_updated()

    if run_phase1:
        print("Truncating Phase 1 data...")
        session.execute(text("TRUNCATE TABLE atlas_stops, osm_nodes, route_atlas_stops, route_osm_stops CASCADE"))
    if run_phase2:
        print("Truncating Phase 2 data...")
        session.execute(text("TRUNCATE TABLE routes_matched CASCADE"))
    if run_phase3:
        print("Truncating Phase 3 data...")
        session.execute(text("TRUNCATE TABLE problems, stops_matched CASCADE"))
    session.commit()

    # Because import_db is fully rebuilt each run, TRUNCATE is safe and fast.
    # CASCADE handles the problems → stops FK automatically.
    
    
    # Load route information
    # Avoid re-reading the same CSV twice by preloading and passing to both loaders
    try:
        _preloaded_osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
    except Exception:
        _preloaded_osm_routes_df = None

    all_route_data = load_all_route_data(osm_routes_df=_preloaded_osm_routes_df)
    atlas_routes_mapping_unified = all_route_data['atlas_routes_mapping_unified']
    osm_routes_mapping = all_route_data['osm_routes_mapping']
    osm_route_dir_to_nodes = all_route_data['osm_route_dir_to_nodes']
    atlas_route_dir_to_sloids = all_route_data['atlas_route_dir_to_sloids']
    atlas_line_diruic_to_sloids = all_route_data['atlas_line_diruic_to_sloids']
    
    # Keep track of processed detail records to avoid duplicates
    processed_sloids = set()
    processed_osm_node_ids = set()
    
    # Pre-check for duplicate sloids in source data (use Counter to avoid O(n^2))
    all_sloids = []
    for rec in base_data.get('matched', []):
        sloid = safe_value(rec.get('sloid'))
        if sloid:
            all_sloids.append(sloid)
    for rec in base_data.get('unmatched_atlas', []):
        sloid = safe_value(rec.get('sloid'))
        if sloid:
            all_sloids.append(sloid)
    counts = Counter(all_sloids)
    duplicate_sloids = {s for s, c in counts.items() if c > 1}
    if duplicate_sloids:
        print(f"{len(duplicate_sloids)} sloids are matched to more than one OSM node")
        print(f"Examples: {list(duplicate_sloids)[:5]}")

    # --- Build problem detection context (KDTrees, UIC counts, duplicate maps) ---
    problem_ctx = ProblemContext.build(base_data, duplicate_sloid_map)

    # --- Insert Matched Records ---
    matched_records = base_data.get('matched', [])

    print("\nDetecting problems and importing matched records...")
    print("  Checks: distance, attributes, duplicates")

    BATCH_SIZE = int(os.getenv('DB_IMPORT_BATCH_SIZE', '5000'))
    _t0 = time.time()
    inserted = 0

    for rec in matched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'csv_lat', 'csv_lon', 'sloid', rec.get('sloid'), 'matched'
        )
        if atlas_lat is None:
            continue

        try:
            osm_lat = float(safe_value(rec.get('osm_lat'))) if safe_value(rec.get('osm_lat')) is not None else None
            osm_lon = float(safe_value(rec.get('osm_lon'))) if safe_value(rec.get('osm_lon')) is not None else None
            if osm_lat is not None and math.isnan(osm_lat):
                osm_lat = None
            if osm_lon is not None and math.isnan(osm_lon):
                osm_lon = None
        except Exception:
            osm_lat, osm_lon = None, None

        sloid = safe_value(rec.get('sloid'))
        osm_node_id = safe_value(rec.get('osm_node_id'))
        distance_m = safe_value(rec.get('distance_m'))

        rec['stop_type'] = 'matched'

        if run_phase3:
            stop_record = StopsMatched(
                sloid=sloid,
                stop_type='matched',
                match_type=safe_value(rec.get('match_type')),
                atlas_lat=atlas_lat,
                atlas_lon=atlas_lon,
                osm_node_id=osm_node_id,
                osm_lat=osm_lat,
                osm_lon=osm_lon,
                distance_m=distance_m,
                geom=make_point_geom(atlas_lat, atlas_lon) if atlas_lat is not None and atlas_lon is not None else make_point_geom(osm_lat, osm_lon),
            )
            if safe_value(rec.get('match_type')) == 'manual':
                stop_record.manual_is_persistent = True

            apply_problem_results(stop_record, run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, rec))
            session.add(stop_record)

        if run_phase1 and sloid and sloid not in processed_sloids:
            designation_official = safe_value(rec.get('csv_designation_official')) or safe_value(rec.get('designationOfficial')) or safe_value(rec.get('csv_designation')) or ""
            atlas_record = AtlasStop(
                sloid=sloid,
                uic_ref=safe_value(rec.get('number'), ""),
                atlas_designation=safe_value(rec.get('csv_designation'), ""),
                atlas_designation_official=designation_official,
                atlas_business_org_abbr=safe_value(rec.get('csv_business_org_abbr', '')),
                routes_unified=atlas_routes_mapping_unified.get(sloid, None) if atlas_routes_mapping_unified else None,
                duplicate_group_sloids=duplicate_sloid_map.get(str(sloid)) if str(sloid) in duplicate_sloid_map else None,
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)

        if run_phase1:
            routes_osm_data = osm_routes_mapping.get(osm_node_id, []) if osm_node_id else []
            if osm_node_id and osm_node_id not in processed_osm_node_ids:
                osm_record = OsmNode(
                    osm_node_id=osm_node_id,
                    osm_local_ref=safe_value(rec.get('osm_local_ref')),
                    osm_name=safe_value(rec.get('osm_name')) or get_from_tags(rec, 'name'),
                    osm_uic_name=safe_value(rec.get('osm_uic_name')) or get_from_tags(rec, 'uic_name'),
                    osm_uic_ref=safe_value(rec.get('osm_uic_ref')) or get_from_tags(rec, 'uic_ref'),
                    osm_network=safe_value(rec.get('osm_network', '')),
                    osm_operator=safe_value(rec.get('osm_operator', '')),

                    osm_public_transport=safe_value(rec.get('osm_public_transport')),
                    osm_railway=safe_value(rec.get('osm_railway')),
                    osm_amenity=safe_value(rec.get('osm_amenity')),
                    osm_aerialway=safe_value(rec.get('osm_aerialway')),
                    osm_node_type=get_osm_node_type(rec),
                    routes_osm=routes_osm_data if routes_osm_data else None,
                    duplicate_group_node_ids=problem_ctx.duplicate_osm_group_map.get(str(osm_node_id)),
                )
                session.add(osm_record)
                processed_osm_node_ids.add(osm_node_id)

        inserted += 1
        if BATCH_SIZE > 0 and (inserted % BATCH_SIZE) == 0:
            session.commit()
            session.expunge_all()
            elapsed = max(0.001, time.time() - _t0)
            rate = inserted / elapsed
            pct = (inserted / len(matched_records)) * 100.0
            eta_s = int((len(matched_records) - inserted) / max(rate, 1e-9))
            print(f"  Committed batch: {inserted:,}/{len(matched_records):,} ({pct:.1f}%) | {rate:.1f}/s | ETA {eta_s}s")

    # Final commit for any remainder
    session.commit()
    session.expunge_all()
    print(f"Imported {len(matched_records)} matched records")

    # --- Insert Unmatched ATLAS Records ---
    no_nearby_osm_sloids = set()
    unmatched_records = base_data.get('unmatched_atlas', [])
    for rec in unmatched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'wgs84North', 'wgs84East', 'sloid', rec.get('sloid'), 'unmatched ATLAS'
        )
        if atlas_lat is None: continue

        sloid = safe_value(rec.get('sloid'))
        
        nearest_d = problem_ctx.nearest_osm_distance(atlas_lat, atlas_lon)
        is_isolated = True if nearest_d is None or nearest_d > 50 else False
        if is_isolated and sloid:
            no_nearby_osm_sloids.add(sloid)
            
        match_type_for_unmatched = 'no_nearby_counterpart' if is_isolated else None
        rec['stop_type'] = 'atlas_unmatched'

        if run_phase3:
            stop_record = StopsMatched(
                sloid=sloid,
                stop_type='atlas_unmatched',
                match_type=match_type_for_unmatched,
                atlas_lat=atlas_lat,
                atlas_lon=atlas_lon,
                geom=make_point_geom(atlas_lat, atlas_lon),
            )

            apply_problem_results(stop_record, run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, rec))

            session.add(stop_record)

        if run_phase1 and sloid and sloid not in processed_sloids:
            designation_official = safe_value(rec.get('designationOfficial')) or safe_value(rec.get('designation')) or ""
            atlas_record = AtlasStop(
                sloid=sloid,
                uic_ref=safe_value(rec.get('number'), ""),
                atlas_designation=safe_value(rec.get('designation'), ""),
                atlas_designation_official=designation_official,
                atlas_business_org_abbr=safe_value(rec.get('servicePointBusinessOrganisationAbbreviationEn', '')),
                routes_unified=atlas_routes_mapping_unified.get(sloid, None) if atlas_routes_mapping_unified else None,
                duplicate_group_sloids=duplicate_sloid_map.get(str(sloid)) if str(sloid) in duplicate_sloid_map else None,
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)

    session.commit()

    # --- Insert Unmatched OSM Records ---
    unmatched_osm_records = base_data.get('unmatched_osm', [])
    for rec in unmatched_osm_records:
        osm_lat, osm_lon = validate_coordinates(
            rec, 'lat', 'lon', 'node_id', rec.get('node_id'), 'unmatched OSM'
        )
        if osm_lat is None: continue

        osm_node_id = str(safe_value(rec.get('node_id')))
        rec['stop_type'] = 'osm_unmatched'

        if run_phase3:
            stop_record = StopsMatched(
                stop_type='osm_unmatched',
                osm_node_id=osm_node_id,
                osm_lat=osm_lat,
                osm_lon=osm_lon,
                geom=make_point_geom(osm_lat, osm_lon),
            )

            apply_problem_results(stop_record, run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, rec))

            session.add(stop_record)

        if run_phase1 and osm_node_id and osm_node_id not in processed_osm_node_ids:
            routes_osm_data = osm_routes_mapping.get(osm_node_id, [])
            osm_record = OsmNode(
                osm_node_id=osm_node_id,
                osm_local_ref=get_from_tags(rec, 'local_ref') or safe_value(rec.get('local_ref')),
                osm_name=safe_value(rec.get('name')) or get_from_tags(rec, 'name'),
                osm_uic_name=get_from_tags(rec, 'uic_name'),
                osm_uic_ref=get_from_tags(rec, 'uic_ref'),
                osm_network=get_from_tags(rec, 'network', ''),
                osm_operator=get_from_tags(rec, 'operator', ''),

                osm_public_transport=get_from_tags(rec, 'public_transport', ''),
                osm_railway=get_from_tags(rec, 'railway', ''),
                osm_amenity=get_from_tags(rec, 'amenity', ''),
                osm_aerialway=get_from_tags(rec, 'aerialway', ''),
                osm_node_type=get_osm_node_type(rec, is_osm_unmatched=True),
                routes_osm=routes_osm_data if routes_osm_data else None,
                duplicate_group_node_ids=problem_ctx.duplicate_osm_group_map.get(str(osm_node_id)),
            )
            session.add(osm_record)
            processed_osm_node_ids.add(osm_node_id)

    session.commit()

    # --- Insert Route and Direction Records ---
    matched_routes = 0
    routes_to_insert = []
    
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
        if run_phase1:
            # Insert OSM Stop sequence
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

        if run_phase2 and atlas_matched_route_id and (atlas_matched_route_id, osm_route_id) not in seen_route_matches:
            seen_route_matches.add((atlas_matched_route_id, osm_route_id))
            routes_to_insert.append(RoutesMatched(
                atlas_route_id=atlas_matched_route_id,
                osm_route_id=osm_route_id,
                match_type='matched'
            ))
            matched_routes += 1
            
    if run_phase1:
        for (atlas_route_id, direction_id), atlas_data in atlas_route_dir_to_sloids.items():
            for i, слоid in enumerate(atlas_data['sloids']):
                routes_to_insert.append(RouteAtlasStops(
                    atlas_route_id=atlas_route_id, direction_id=direction_id, sloid=слоid, stop_sequence=i
                ))

        # Add HRDF-only consolidated rows
        for (line_name, direction_uic), atlas_data in atlas_line_diruic_to_sloids.items():
            for i, слоid in enumerate(atlas_data['sloids']):
                routes_to_insert.append(RouteAtlasStops(
                    atlas_route_id=line_name, direction_id=direction_uic, sloid=слоid, stop_sequence=i
                ))
    
    session.bulk_save_objects(routes_to_insert)
    session.commit()
    print(f"Route matching completed: {matched_routes} routes matched")
    
    # Apply persistent solutions to newly created problems
    apply_persistent_solutions_service(session, user_input_session)
    
    # Count problems in the database
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
    
    session.close()
    print("Data import complete!")
    
    return no_nearby_osm_sloids


def export_stats_after_import(base_data, duplicate_sloid_map, no_nearby_sloids):
    """
    Export pipeline statistics to data/stats.json after import completes.
    
    Args:
        base_data: Dictionary with matched, unmatched_atlas, unmatched_osm
        duplicate_sloid_map: Map of duplicate ATLAS sloids
        no_nearby_sloids: Set of ATLAS sloids with no OSM within 50m
    """
    try:
        matched_records = base_data.get('matched', [])
        unmatched_atlas = base_data.get('unmatched_atlas', [])
        unmatched_osm = base_data.get('unmatched_osm', [])
        
        # Calculate total ATLAS platforms from records
        matched_sloids = {r.get('sloid') for r in matched_records if r.get('sloid')}
        unmatched_sloids = {r.get('sloid') for r in unmatched_atlas if r.get('sloid')}
        total_atlas = len(matched_sloids | unmatched_sloids)
        
        # Calculate total OSM nodes (matched + unmatched)
        matched_osm_ids = {r.get('osm_node_id') for r in matched_records if r.get('osm_node_id')}
        total_osm = len(matched_osm_ids) + len(unmatched_osm)
        
        # Calculate OSM route stats
        osm_with_routes_count = 0
        unmatched_with_routes_count = 0
        try:
            routes_path = "data/processed/osm_nodes_with_routes.csv"
            if os.path.exists(routes_path):
                # We only need checking existence for unmatched, but for stats we need total unique nodes
                routes_df = pd.read_csv(routes_path)
                
                # Stats: Total OSM nodes with routes
                if 'node_id' in routes_df.columns:
                    osm_with_routes_count = routes_df['node_id'].nunique()
                else:
                    osm_with_routes_count = len(routes_df)
                
                # Unmatched analysis
                nodes_with_routes = set(routes_df['node_id'].astype(str).unique())
                unmatched_with_routes_count = sum(
                    1 for node in unmatched_osm 
                    if str(node.get('node_id')) in nodes_with_routes
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
        
        # Add routes count for unmatched OSM (already in stats['unmatched_analysis']['osm'])
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
    parser.add_argument("--skip-phase1", action="store_true", help="Skip inserting raw atlas and osm nodes")
    parser.add_argument("--skip-phase2", action="store_true", help="Skip route matching insertion")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip stop matching insertion")
    args = parser.parse_args()

    # Run the final pipeline to obtain base_data in-memory
    print("Running the final pipeline to obtain base data...")
    # Unpack the three return values
    base_data, duplicate_sloid_map_result = run_matching()
    
    # Directly import the in-memory base_data into the database
    print("Importing data into the database...")
    # Pass the new set of sloids to the import function
    no_nearby_sloids = import_to_database(
        base_data, 
        duplicate_sloid_map_result, 
        run_phase1=not args.skip_phase1,
        run_phase2=not args.skip_phase2,
        run_phase3=not args.skip_phase3
    )
    
    # Export statistics to data/stats.json
    export_stats_after_import(base_data, duplicate_sloid_map_result, no_nearby_sloids)
    
    print("Process completed successfully!")