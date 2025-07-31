from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json, math
import pandas as pd
import numpy as np
from matching_process.matching_script import final_pipeline
from matching_process.problem_detection import analyze_stop_problems
import os

# Import models
from backend.models import Stop, AtlasStop, OsmNode, RouteAndDirection, Problem, PersistentData

# Database Setup
DATABASE_URI = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

def ensure_schema_updated():
    """
    Ensure the database schema includes the new persistence flags.
    This function adds the missing columns if they don't exist.
    """
    print("Checking and updating database schema...")
    
    try:
        # Check if the new columns exist and add them if they don't
        with engine.connect() as conn:
            # Check problems table for is_persistent column
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.columns 
                WHERE table_schema = DATABASE() 
                AND table_name = 'problems' 
                AND column_name = 'is_persistent'
            """))
            
            if result.fetchone()[0] == 0:
                print("Adding is_persistent column to problems table...")
                conn.execute(text("ALTER TABLE problems ADD COLUMN is_persistent BOOLEAN DEFAULT FALSE"))
                conn.commit()
            
            # Check atlas_stops table for atlas_note_is_persistent column
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.columns 
                WHERE table_schema = DATABASE() 
                AND table_name = 'atlas_stops' 
                AND column_name = 'atlas_note_is_persistent'
            """))
            
            if result.fetchone()[0] == 0:
                print("Adding atlas_note_is_persistent column to atlas_stops table...")
                conn.execute(text("ALTER TABLE atlas_stops ADD COLUMN atlas_note_is_persistent BOOLEAN DEFAULT FALSE"))
                conn.commit()
            
            # Check osm_nodes table for osm_note_is_persistent column
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.columns 
                WHERE table_schema = DATABASE() 
                AND table_name = 'osm_nodes' 
                AND column_name = 'osm_note_is_persistent'
            """))
            
            if result.fetchone()[0] == 0:
                print("Adding osm_note_is_persistent column to osm_nodes table...")
                conn.execute(text("ALTER TABLE osm_nodes ADD COLUMN osm_note_is_persistent BOOLEAN DEFAULT FALSE"))
                conn.commit()
                
        print("Database schema is up to date.")
        
    except Exception as e:
        print(f"Error updating database schema: {e}")
        raise

def sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, float):
        return None if math.isnan(obj) else obj
    else:
        return obj

def safe_value(val, default=None):
    """Safely handle NaN, None, and other problematic values for MySQL"""
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    if pd.isna(val):
        return default
    return val

def get_osm_node_type(rec, is_osm_unmatched=False):
    """Determine the osm_node_type based on OSM tags."""
    if is_osm_unmatched:
        # For unmatched OSM nodes, tags are in a 'tags' dict
        tags = rec.get('tags', {})
        if not tags: tags = {}
        osm_public_transport = tags.get('public_transport')
        osm_railway = tags.get('railway')
        osm_amenity = tags.get('amenity')
        osm_aerialway = tags.get('aerialway')
    else:
        # For matched stops, tags are top-level keys
        osm_public_transport = rec.get('osm_public_transport')
        osm_railway = rec.get('osm_railway')
        osm_amenity = rec.get('osm_amenity')
        osm_aerialway = rec.get('osm_aerialway')

    if osm_public_transport == 'station' and osm_railway == 'station':
        return 'railway_station'
    if osm_amenity == 'ferry_terminal':
        return 'ferry_terminal'
    if osm_aerialway and osm_aerialway != '':
        return 'aerialway'
    if osm_public_transport == 'platform':
        return 'platform'
    if osm_public_transport == 'stop_position':
        return 'stop_position'
    return None

def validate_coordinates(rec, lat_key, lon_key, id_key, id_value, record_type):
    """
    Validate and extract coordinates from a record.
    
    Args:
        rec: Record dictionary
        lat_key: Key for latitude in the record
        lon_key: Key for longitude in the record
        id_key: Key for ID field (for error reporting)
        id_value: Value of ID field (for error reporting)
        record_type: Type of record (for error reporting)
    
    Returns:
        tuple: (lat, lon) or (None, None) if invalid
    """
    try:
        lat = safe_value(rec.get(lat_key))
        lon = safe_value(rec.get(lon_key))
        
        if lat is None or lon is None:
            print(f"Warning: Missing coordinates for {record_type} {id_key}={id_value}")
            return None, None
        
        lat_float = float(lat)
        lon_float = float(lon)
        
        # Check for NaN or infinite values
        if math.isnan(lat_float) or math.isinf(lat_float) or math.isnan(lon_float) or math.isinf(lon_float):
            print(f"Warning: Invalid coordinates (NaN/Inf) for {record_type} {id_key}={id_value}")
            return None, None
        
        # Basic coordinate range validation
        if not (-90 <= lat_float <= 90) or not (-180 <= lon_float <= 180):
            print(f"Warning: Coordinates out of range for {record_type} {id_key}={id_value}: lat={lat_float}, lon={lon_float}")
            return None, None
        
        return lat_float, lon_float
        
    except (ValueError, TypeError) as e:
        print(f"Warning: Error parsing coordinates for {record_type} {id_key}={id_value}: {e}")
        return None, None

def get_from_tags(rec, tag_key, default=None):
    """
    Extract a value from OSM tags dictionary.
    
    Args:
        rec: Record dictionary
        tag_key: Key to look for in tags
        default: Default value if not found
    
    Returns:
        Value from tags or default
    """
    # First try direct key access
    if tag_key in rec:
        return safe_value(rec[tag_key], default)
    
    # Then try from tags dictionary
    tags = rec.get('tags', {})
    if isinstance(tags, dict) and tag_key in tags:
        return safe_value(tags[tag_key], default)
    
    return default

def load_route_data():
    """Load route data from CSV files and create mappings for stops to routes"""
    # Load ATLAS routes
    atlas_routes_mapping = {}
    try:
        print("Loading ATLAS GTFS routes...")
        atlas_routes_df = pd.read_csv("data/processed/atlas_routes_gtfs.csv")
        
        # Use groupby for more efficient processing
        for sloid, group in atlas_routes_df.groupby('sloid'):
            if pd.notna(sloid):
                atlas_routes_mapping[sloid] = []
                for _, row in group.iterrows():
                    route_info = {
                        'route_id': row['route_id'],
                        'direction_id': str(row['direction_id']),
                        'route_short_name': row['route_short_name'] if pd.notna(row['route_short_name']) else None,
                        'route_long_name': row['route_long_name'] if pd.notna(row['route_long_name']) else None
                    }
                    atlas_routes_mapping[sloid].append(route_info)
        print(f"Loaded route information for {len(atlas_routes_mapping)} ATLAS stops")
    except FileNotFoundError:
        print("INFO: GTFS routes file (atlas_routes_gtfs.csv) not found, skipping ATLAS-GTFS route loading.")
    except Exception as e:
        print(f"Error loading ATLAS routes: {e}")
        
    # Load HRDF routes for ATLAS
    atlas_hrdf_routes_mapping = {}
    try:
        print("Loading ATLAS HRDF routes...")
        hrdf_routes_df = pd.read_csv("data/processed/atlas_routes_hrdf.csv")
        
        # Use groupby for more efficient processing
        for sloid, group in hrdf_routes_df.groupby('sloid'):
            sloid_str = str(sloid)
            atlas_hrdf_routes_mapping[sloid_str] = []
            for _, row in group.iterrows():
                route_info = {
                    'line_name': row['line_name'] if pd.notna(row['line_name']) else None,
                    'direction_name': row['direction_name'] if pd.notna(row['direction_name']) else None,
                    'direction_uic': row['direction_uic'] if pd.notna(row['direction_uic']) else None,
                }
                atlas_hrdf_routes_mapping[sloid_str].append(route_info)
        print(f"Loaded HRDF route information for {len(atlas_hrdf_routes_mapping)} ATLAS stops")
    except Exception as e:
        print(f"Error loading HRDF routes: {e}")
        
    # Load OSM routes
    osm_routes_mapping = {}
    try:
        print("Loading OSM routes...")
        osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
        
        # Filter out invalid rows early
        valid_routes = osm_routes_df[
            pd.notna(osm_routes_df['node_id']) & 
            (pd.notna(osm_routes_df['gtfs_route_id']) | pd.notna(osm_routes_df['route_name']))
        ].copy()
        
        # Use groupby for more efficient processing
        for node_id, group in valid_routes.groupby('node_id'):
            node_id_str = str(node_id)
            osm_routes_mapping[node_id_str] = []
            for _, row in group.iterrows():
                route_info = {
                    'route_id': row['gtfs_route_id'] if pd.notna(row['gtfs_route_id']) else None,
                    'direction_id': str(int(float(row['direction_id']))) if pd.notna(row['direction_id']) else None,
                    'route_name': row['route_name'] if pd.notna(row['route_name']) else None
                }
                osm_routes_mapping[node_id_str].append(route_info)
        print(f"Loaded route information for {len(osm_routes_mapping)} OSM nodes")
    except Exception as e:
        print(f"Error loading OSM routes: {e}")
        
    return atlas_routes_mapping, atlas_hrdf_routes_mapping, osm_routes_mapping

def _normalize_route_id_for_matching(route_id):
    """Remove year codes (j24, j25, etc.) from route IDs for fuzzy matching."""
    if not route_id:
        return None
    import re
    # Replace j24, j25, j22, etc. with a generic jXX for comparison
    normalized = re.sub(r'-j\d+', '-jXX', str(route_id))
    return normalized

def build_route_direction_mapping():
    """Build mappings for routes and directions"""
    # Maps for route+direction to nodes
    osm_route_dir_to_nodes = {}
    atlas_route_dir_to_sloids = {}
    
    try:
        # --- Build fallback mapping from GTFS route names to route_id ---
        gtfs_routes_path = None
        gtfs_root = "data/raw"
        if os.path.isdir(gtfs_root):
            for fname in os.listdir(gtfs_root):
                if fname.startswith("gtfs_") and os.path.isdir(os.path.join(gtfs_root, fname)):
                    candidate = os.path.join(gtfs_root, fname, "routes.txt")
                    if os.path.exists(candidate):
                        gtfs_routes_path = candidate
                        break

        route_name_to_id = {}
        if gtfs_routes_path:
            try:
                gtfs_routes_df = pd.read_csv(gtfs_routes_path, dtype=str, usecols=['route_id', 'route_short_name', 'route_long_name'])
                for _, r in gtfs_routes_df.iterrows():
                    if pd.notna(r.get('route_short_name')):
                        route_name_to_id[str(r['route_short_name']).strip()] = str(r['route_id']).strip()
                    if pd.notna(r.get('route_long_name')):
                        route_name_to_id[str(r['route_long_name']).strip()] = str(r['route_id']).strip()
            except Exception as e:
                print(f"Warning: Failed to build GTFS route name mapping for import: {e}")

        # Process OSM routes
        osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
        for _, row in osm_routes_df.iterrows():
            direction_id_raw = safe_value(row.get('direction_id'))
            if pd.isna(row.get('gtfs_route_id')) and pd.isna(row.get('route_name')):
                continue # Cannot determine route, skip

            # Determine route_id using fallback
            route_id = None
            if pd.notna(row.get('gtfs_route_id')) and str(row['gtfs_route_id']).strip():
                route_id = str(row['gtfs_route_id']).strip()
            else:
                rname = str(row.get('route_name') or '').strip()
                if rname in route_name_to_id:
                    route_id = route_name_to_id[rname]
            
            if not route_id:
                continue # Still no route_id, skip

            # Handle direction
            directions_to_add = []
            if pd.notna(direction_id_raw):
                try:
                    directions_to_add.append(str(int(float(direction_id_raw))))
                except (ValueError, TypeError):
                    continue # Invalid direction format
            else:
                # If direction is missing, assume it applies to both
                directions_to_add = ['0', '1']

            node_id = str(row['node_id'])
            for direction_id in directions_to_add:
                key = (route_id, direction_id)
                if key not in osm_route_dir_to_nodes:
                    osm_route_dir_to_nodes[key] = {
                        'nodes': [],
                        'route_name': row['route_name'] if pd.notna(row['route_name']) else None
                    }
                osm_route_dir_to_nodes[key]['nodes'].append(node_id)
        
        # Process ATLAS routes
        try:
            atlas_routes_df = pd.read_csv("data/processed/atlas_routes_gtfs.csv")
            for _, row in atlas_routes_df.iterrows():
                if pd.notna(row['route_id']) and pd.notna(row['direction_id']) and pd.notna(row['sloid']):
                    route_id = row['route_id']
                    direction_id = str(int(float(row['direction_id']))) # Normalize direction
                    sloid = row['sloid']
                    
                    key = (route_id, direction_id)
                    if key not in atlas_route_dir_to_sloids:
                        atlas_route_dir_to_sloids[key] = {
                            'sloids': [],
                            'route_short_name': row['route_short_name'] if pd.notna(row['route_short_name']) else None,
                            'route_long_name': row['route_long_name'] if pd.notna(row['route_long_name']) else None
                        }
                    atlas_route_dir_to_sloids[key]['sloids'].append(sloid)
        except FileNotFoundError:
            print("INFO: GTFS routes file (atlas_routes_gtfs.csv) not found, skipping ATLAS-GTFS route/direction mapping.")
        
        print(f"Built route+direction to nodes mapping for {len(osm_route_dir_to_nodes)} OSM routes")
        print(f"Built route+direction to sloids mapping for {len(atlas_route_dir_to_sloids)} ATLAS routes")
    except Exception as e:
        print(f"Error building route-direction mappings: {e}")
        
    return osm_route_dir_to_nodes, atlas_route_dir_to_sloids

# --------------------------
# Data Import Function
# --------------------------
def import_to_database(base_data, duplicate_sloid_map, no_nearby_osm_sloids):
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
    
    print("Deleting existing data from database...")
    # Delete from tables, respecting foreign key relations by deleting problems first
    session.query(Problem).delete()
    session.query(Stop).delete()
    session.query(AtlasStop).delete()
    session.query(OsmNode).delete()
    session.query(RouteAndDirection).delete()
    session.commit()
    print("Existing data deleted. Starting new import.")
    
    # Load route information
    atlas_routes_mapping, atlas_hrdf_routes_mapping, osm_routes_mapping = load_route_data()
    
    # Build route+direction to nodes/sloids mappings for routes_and_directions table
    osm_route_dir_to_nodes, atlas_route_dir_to_sloids = build_route_direction_mapping()
    
    # Keep track of processed detail records to avoid duplicates
    processed_sloids = set()
    processed_osm_node_ids = set()
    
    # Pre-check for duplicate sloids in source data
    all_sloids = []
    for rec in base_data.get('matched', []):
        sloid = safe_value(rec.get('sloid'))
        if sloid:
            all_sloids.append(sloid)
    for rec in base_data.get('unmatched_atlas', []):
        sloid = safe_value(rec.get('sloid'))
        if sloid:
            all_sloids.append(sloid)
    
    duplicate_sloids = set([x for x in all_sloids if all_sloids.count(x) > 1])
    if duplicate_sloids:
        print(f"{len(duplicate_sloids)} sloids are matched to more than one OSM node")
        print(f"Examples: {list(duplicate_sloids)[:5]}")

    # --- Insert Matched Records ---
    matched_records = base_data.get('matched', [])
    
    for rec in matched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'csv_lat', 'csv_lon', 'sloid', rec.get('sloid'), 'matched'
        )
        if atlas_lat is None:
            continue
        
        try:
            osm_lat = float(safe_value(rec.get('osm_lat'))) if safe_value(rec.get('osm_lat')) is not None else None
            osm_lon = float(safe_value(rec.get('osm_lon'))) if safe_value(rec.get('osm_lon')) is not None else None
            if osm_lat is not None and math.isnan(osm_lat): osm_lat = None
            if osm_lon is not None and math.isnan(osm_lon): osm_lon = None
        except Exception:
            osm_lat, osm_lon = None, None
        
        sloid = safe_value(rec.get('sloid'))
        osm_node_id = safe_value(rec.get('osm_node_id'))
        distance_m = safe_value(rec.get('distance_m'))
        
        rec['stop_type'] = 'matched'
        problems = analyze_stop_problems(rec)
        
        stop_record = Stop(
            sloid=sloid,
            stop_type='matched',
            match_type=safe_value(rec.get('match_type')),
            atlas_lat=atlas_lat,
            atlas_lon=atlas_lon,
            atlas_duplicate_sloid=duplicate_sloid_map.get(sloid),
            uic_ref=safe_value(rec.get('number'), ""),
            osm_node_id=osm_node_id,
            osm_lat=osm_lat,
            osm_lon=osm_lon,
            distance_m=distance_m,
            osm_node_type=get_osm_node_type(rec)
        )
        
        # Create problems with additional metadata for better sorting
        if problems.get('distance_problem'):
            # For distance problems, store the distance for efficient sorting
            distance_problem = Problem(
                problem_type='distance',
                solution=None,  # Will be set by persistent solutions if available
                is_persistent=False
            )
            stop_record.problems.append(distance_problem)
            
        if problems.get('attributes_problem'):
            attributes_problem = Problem(
                problem_type='attributes',
                solution=None,
                is_persistent=False
            )
            stop_record.problems.append(attributes_problem)

        session.add(stop_record)
        
        routes_atlas_data = atlas_routes_mapping.get(sloid, []) if sloid else []
        routes_hrdf_data = atlas_hrdf_routes_mapping.get(sloid, []) if sloid else []
        if sloid and sloid not in processed_sloids:
            designation_official = safe_value(rec.get('csv_designation_official')) or safe_value(rec.get('designationOfficial')) or safe_value(rec.get('csv_designation')) or ""
            atlas_record = AtlasStop(
                sloid=sloid,
                atlas_designation=safe_value(rec.get('csv_designation'), ""),
                atlas_designation_official=designation_official,
                atlas_business_org_abbr=safe_value(rec.get('csv_business_org_abbr', '')),
                routes_atlas=routes_atlas_data if routes_atlas_data else None,
                routes_hrdf=routes_hrdf_data if routes_hrdf_data else None,
                atlas_note=None,
                atlas_note_is_persistent=False
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)
            
        routes_osm_data = osm_routes_mapping.get(osm_node_id, []) if osm_node_id else []
        if osm_node_id and osm_node_id not in processed_osm_node_ids:
            osm_record = OsmNode(
                osm_node_id=osm_node_id,
                osm_local_ref=safe_value(rec.get('osm_local_ref')),
                osm_name=safe_value(rec.get('osm_name')) or get_from_tags(rec, 'name'),
                osm_uic_name=safe_value(rec.get('osm_uic_name')) or get_from_tags(rec, 'uic_name'),
                osm_network=safe_value(rec.get('osm_network', '')),
                osm_operator=safe_value(rec.get('osm_operator', '')),

                osm_public_transport=safe_value(rec.get('osm_public_transport')),
                osm_railway=safe_value(rec.get('osm_railway')),
                osm_amenity=safe_value(rec.get('osm_amenity')),
                osm_aerialway=safe_value(rec.get('osm_aerialway')),
                routes_osm=routes_osm_data if routes_osm_data else None,
                osm_note=None,
                osm_note_is_persistent=False
            )
            session.add(osm_record)
            processed_osm_node_ids.add(osm_node_id)

    # Commit all matched records at once
    session.commit()
    print(f"Imported {len(matched_records)} matched records")

    # --- Insert Unmatched ATLAS Records ---
    unmatched_records = base_data.get('unmatched_atlas', [])
    for rec in unmatched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'wgs84North', 'wgs84East', 'sloid', rec.get('sloid'), 'unmatched ATLAS'
        )
        if atlas_lat is None: continue

        sloid = safe_value(rec.get('sloid'))
        match_type_for_unmatched = 'no_osm_within_50m' if sloid in no_nearby_osm_sloids else None

        problems = analyze_stop_problems({
            'stop_type': 'unmatched',
            'match_type': match_type_for_unmatched,
            'sloid': sloid
        })

        stop_record = Stop(
            sloid=sloid,
            stop_type='unmatched',
            match_type=match_type_for_unmatched,
            atlas_lat=atlas_lat,
            atlas_lon=atlas_lon,
            atlas_duplicate_sloid=duplicate_sloid_map.get(sloid),
            uic_ref=safe_value(rec.get('number'), "")
        )
        
        if problems.get('isolated_problem'):
            isolated_problem = Problem(
                problem_type='isolated',
                solution=None,
                is_persistent=False
            )
            stop_record.problems.append(isolated_problem)

        session.add(stop_record)
        
        if sloid and sloid not in processed_sloids:
            routes_atlas_data = atlas_routes_mapping.get(sloid, [])
            routes_hrdf_data = atlas_hrdf_routes_mapping.get(sloid, [])
            designation_official = safe_value(rec.get('designationOfficial')) or safe_value(rec.get('designation')) or ""
            atlas_record = AtlasStop(
                sloid=sloid,
                atlas_designation=safe_value(rec.get('designation'), ""),
                atlas_designation_official=designation_official,
                atlas_business_org_abbr=safe_value(rec.get('servicePointBusinessOrganisationAbbreviationEn', '')),
                routes_atlas=routes_atlas_data if routes_atlas_data else None,
                routes_hrdf=routes_hrdf_data if routes_hrdf_data else None,
                atlas_note=None,
                atlas_note_is_persistent=False
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
        
        problems = analyze_stop_problems({
            'stop_type': 'osm',
            'osm_node_id': osm_node_id,
            'is_isolated': rec.get('is_isolated', False)
        })
        
        stop_record = Stop(
            stop_type='osm',
            uic_ref=get_from_tags(rec, 'uic_ref', ''),
            osm_node_id=osm_node_id,
            osm_lat=osm_lat,
            osm_lon=osm_lon,
            osm_node_type=get_osm_node_type(rec, is_osm_unmatched=True)
        )

        if problems.get('isolated_problem'):
            isolated_problem = Problem(
                problem_type='isolated',
                solution=None,
                is_persistent=False
            )
            stop_record.problems.append(isolated_problem)

        session.add(stop_record)

        if osm_node_id and osm_node_id not in processed_osm_node_ids:
            routes_osm_data = osm_routes_mapping.get(osm_node_id, [])
            osm_record = OsmNode(
                osm_node_id=osm_node_id,
                osm_local_ref=get_from_tags(rec, 'local_ref') or safe_value(rec.get('local_ref')),
                osm_name=safe_value(rec.get('name')) or get_from_tags(rec, 'name'),
                osm_uic_name=get_from_tags(rec, 'uic_name'),
                osm_network=get_from_tags(rec, 'network', ''),
                osm_operator=get_from_tags(rec, 'operator', ''),

                osm_public_transport=get_from_tags(rec, 'public_transport', ''),
                osm_railway=get_from_tags(rec, 'railway', ''),
                osm_amenity=get_from_tags(rec, 'amenity', ''),
                osm_aerialway=get_from_tags(rec, 'aerialway', ''),
                routes_osm=routes_osm_data if routes_osm_data else None,
                osm_note=None,
                osm_note_is_persistent=False
            )
            session.add(osm_record)
            processed_osm_node_ids.add(osm_node_id)
            
    session.commit()

    # --- Insert Route and Direction Records ---
    matched_routes = 0
    osm_only_routes = 0
    atlas_only_routes = 0
    
    for (osm_route_id, direction_id), osm_data in osm_route_dir_to_nodes.items():
        atlas_data = atlas_route_dir_to_sloids.get((osm_route_id, direction_id))
        
        if not atlas_data:
            osm_route_normalized = _normalize_route_id_for_matching(osm_route_id)
            if osm_route_normalized:
                for (atlas_route_id, atlas_direction_id), atlas_info in atlas_route_dir_to_sloids.items():
                    if (atlas_direction_id == direction_id and 
                        _normalize_route_id_for_matching(atlas_route_id) == osm_route_normalized):
                        atlas_data = atlas_info
                        break
        
        if atlas_data:
            route_record = RouteAndDirection(
                direction_id=direction_id,
                osm_route_id=osm_route_id,
                osm_nodes_json=osm_data['nodes'],
                atlas_route_id=osm_route_id,
                atlas_sloids_json=atlas_data['sloids'],
                route_name=osm_data['route_name'],
                route_short_name=atlas_data['route_short_name'],
                route_long_name=atlas_data['route_long_name'],
                route_type=None,
                match_type='matched'
            )
            matched_routes += 1
        else:
            route_record = RouteAndDirection(
                direction_id=direction_id,
                osm_route_id=osm_route_id,
                osm_nodes_json=osm_data['nodes'],
                atlas_route_id=None,
                atlas_sloids_json=None,
                route_name=osm_data['route_name'],
                route_short_name=None,
                route_long_name=None,
                route_type=None,
                match_type='osm_only'
            )
            osm_only_routes += 1
            
        session.add(route_record)
    
    processed_keys = set(osm_route_dir_to_nodes.keys())
    for (atlas_route_id, direction_id), atlas_data in atlas_route_dir_to_sloids.items():
        if (atlas_route_id, direction_id) in processed_keys:
            continue
            
        route_record = RouteAndDirection(
            direction_id=direction_id,
            osm_route_id=None,
            osm_nodes_json=None,
            atlas_route_id=atlas_route_id,
            atlas_sloids_json=atlas_data['sloids'],
            route_name=None,
            route_short_name=atlas_data['route_short_name'],
            route_long_name=atlas_data['route_long_name'],
            route_type=None,
            match_type='atlas_only'
        )
        atlas_only_routes += 1
        session.add(route_record)
    
    session.commit()
    print(f"Route statistics: {matched_routes} matched, {osm_only_routes} OSM-only, {atlas_only_routes} ATLAS-only")
    
    # Apply persistent solutions to newly created problems
    apply_persistent_solutions()
    
    # Count problems in the database
    from sqlalchemy import func
    total_stops = session.query(Stop).count()
    distance_problems = session.query(Problem).filter(Problem.problem_type == 'distance').count()
    isolated_problems = session.query(Problem).filter(Problem.problem_type == 'isolated').count()
    attributes_problems = session.query(Problem).filter(Problem.problem_type == 'attributes').count()
    
    multiple_problems = session.query(Problem.stop_id).group_by(Problem.stop_id).having(func.count(Problem.stop_id) > 1).count()
    
    stops_with_problems = session.query(func.count(func.distinct(Problem.stop_id))).scalar()
    clean_entries = total_stops - stops_with_problems

    print("\n==== PROBLEM DETECTION SUMMARY ====")
    print(f"Total stops imported: {total_stops}")
    print(f"Distance problems: {distance_problems}")
    print(f"Isolated problems: {isolated_problems}")
    print(f"Attributes problems: {attributes_problems}")
    print(f"Entries with multiple problems: {multiple_problems}")
    print(f"Clean entries (no problems): {clean_entries}")
    
    session.close()
    print("Data import complete!")

def apply_persistent_solutions():
    """
    Apply previously saved persistent solutions to newly created problems.
    This function is called after all data is imported and problems are detected.
    
    The function works by:
    1. Getting all persistent solutions and notes
    2. For each solution, finding stops that match by sloid or osm_node_id
    3. For each matching stop, finding problems of the same type
    4. Applying the persistent solution to those problems and setting is_persistent=True
    
    It also applies persistent notes to ATLAS and OSM stops and sets their persistence flags.
    """
    print("Applying persistent solutions from previous imports...")
    
    # Get all persistent solutions for problems
    persistent_solutions = session.query(PersistentData).filter(
        PersistentData.note_type.is_(None)
    ).all()
    applied_count = 0
    skipped_count = 0
    
    for ps in persistent_solutions:
        # Find matching stops in the new data
        matching_stops = session.query(Stop).filter(
            (Stop.sloid == ps.sloid) | (Stop.osm_node_id == ps.osm_node_id)
        ).all()
        
        if not matching_stops:
            # The stop no longer exists in the data
            print(f"  - No matching stop found for persistent solution: sloid={ps.sloid}, osm_node_id={ps.osm_node_id}")
            skipped_count += 1
            continue
            
        for stop in matching_stops:
            # Find problems of the same type for this stop
            problem = session.query(Problem).filter(
                Problem.stop_id == stop.id,
                Problem.problem_type == ps.problem_type
            ).first()
            
            if problem:
                # If the problem still exists, apply the solution and mark as persistent
                problem.solution = ps.solution
                problem.is_persistent = True
                applied_count += 1
            else:
                # The stop exists but doesn't have this type of problem anymore
                print(f"  - Stop exists but problem type '{ps.problem_type}' no longer detected for: sloid={stop.sloid}, osm_node_id={stop.osm_node_id}")
                skipped_count += 1
    
    # Apply persistent ATLAS notes
    print("Applying persistent ATLAS notes...")
    atlas_notes = session.query(PersistentData).filter(
        PersistentData.note_type == 'atlas',
        PersistentData.sloid.isnot(None)
    ).all()
    
    atlas_notes_applied = 0
    atlas_notes_skipped = 0
    
    for note_record in atlas_notes:
        # Find the ATLAS stop in the new data
        atlas_stop = session.query(AtlasStop).filter(
            AtlasStop.sloid == note_record.sloid
        ).first()
        
        if atlas_stop:
            # Apply the note and mark as persistent
            atlas_stop.atlas_note = note_record.note
            atlas_stop.atlas_note_is_persistent = True
            atlas_notes_applied += 1
        else:
            print(f"  - ATLAS stop not found for sloid={note_record.sloid}, skipping note application")
            atlas_notes_skipped += 1
    
    # Apply persistent OSM notes
    print("Applying persistent OSM notes...")
    osm_notes = session.query(PersistentData).filter(
        PersistentData.note_type == 'osm',
        PersistentData.osm_node_id.isnot(None)
    ).all()
    
    osm_notes_applied = 0
    osm_notes_skipped = 0
    
    for note_record in osm_notes:
        # Find the OSM node in the new data
        osm_node = session.query(OsmNode).filter(
            OsmNode.osm_node_id == note_record.osm_node_id
        ).first()
        
        if osm_node:
            # Apply the note and mark as persistent
            osm_node.osm_note = note_record.note
            osm_node.osm_note_is_persistent = True
            osm_notes_applied += 1
        else:
            print(f"  - OSM node not found for osm_node_id={note_record.osm_node_id}, skipping note application")
            osm_notes_skipped += 1
    
    session.commit()
    print(f"Applied {applied_count} persistent solutions from previous imports")
    print(f"Skipped {skipped_count} persistent solutions (stops or problems no longer exist)")
    print(f"Applied {atlas_notes_applied} persistent ATLAS notes, skipped {atlas_notes_skipped}")
    print(f"Applied {osm_notes_applied} persistent OSM notes, skipped {osm_notes_skipped}")

if __name__ == "__main__":
    # Run the final pipeline to obtain base_data in-memory
    print("Running the final pipeline to obtain base data...")
    # Unpack the three return values
    base_data, duplicate_sloid_map_result, no_nearby_sloids = final_pipeline()
    # Directly import the in-memory base_data into the database
    print("Importing data into the database...")
    # Pass the new set of sloids to the import function
    import_to_database(base_data, duplicate_sloid_map_result, no_nearby_sloids)
    print("Process completed successfully!")