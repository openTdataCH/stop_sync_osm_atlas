from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import json, math
import pandas as pd
import numpy as np
from scipy.spatial import KDTree
from matching_process.matching_script import final_pipeline
from matching_process.problem_detection import analyze_stop_problems, compute_distance_priority, compute_attributes_priority
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
    Deprecated: Schema changes are now handled via Alembic migrations.
    This function is retained as a no-op for backward compatibility.
    """
    print("Schema management now handled by migrations. Skipping ensure_schema_updated().")

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

def load_route_data(osm_routes_df: pd.DataFrame = None):
    """Load route data from unified routes file and create mappings for stops to routes.

    If osm_routes_df is provided, reuse it to avoid duplicated IO.
    """
    # Load unified route mapping
    atlas_routes_mapping_unified = {}
    unified_path = "data/processed/atlas_routes_unified.csv"
    if os.path.exists(unified_path):
        try:
            unified_df = pd.read_csv(unified_path)
            for sloid, group in unified_df.groupby('sloid'):
                if pd.isna(sloid):
                    continue
                entries = []
                for _, row in group.iterrows():
                    entries.append({
                        'source': row.get('source'),
                        'route_id': row.get('route_id') if pd.notna(row.get('route_id')) else None,
                        'route_id_normalized': row.get('route_id_normalized') if pd.notna(row.get('route_id_normalized')) else None,
                        'route_name_short': row.get('route_name_short') if pd.notna(row.get('route_name_short')) else None,
                        'route_name_long': row.get('route_name_long') if pd.notna(row.get('route_name_long')) else None,
                        'line_name': row.get('line_name') if pd.notna(row.get('line_name')) else None,
                        'direction_id': str(int(float(row.get('direction_id')))) if pd.notna(row.get('direction_id')) else None,
                        'direction_name': row.get('direction_name') if pd.notna(row.get('direction_name')) else None,
                        'direction_uic': row.get('direction_uic') if pd.notna(row.get('direction_uic')) else None,
                        'evidence': row.get('evidence') if pd.notna(row.get('evidence')) else None,
                        'as_of': row.get('as_of') if pd.notna(row.get('as_of')) else None,
                    })
                atlas_routes_mapping_unified[str(sloid)] = entries
            print(f"Loaded unified route information for {len(atlas_routes_mapping_unified)} ATLAS stops")
        except Exception as e:
            print(f"Error loading unified routes: {e}")
            atlas_routes_mapping_unified = {}
    else:
        print(f"Warning: Unified routes file not found at {unified_path}")
        atlas_routes_mapping_unified = {}

    # Extract GTFS routes from unified data
    atlas_routes_mapping = {}
    for sloid, entries in atlas_routes_mapping_unified.items():
        gtfs_entries = [e for e in entries if e.get('source') == 'gtfs']
        if gtfs_entries:
            atlas_routes_mapping[sloid] = [
                {
                    'route_id': e.get('route_id'),
                    'direction_id': e.get('direction_id'),
                    'route_short_name': e.get('route_name_short'),
                    'route_long_name': e.get('route_name_long'),
                }
                for e in gtfs_entries
            ]
    print(f"Extracted GTFS route information for {len(atlas_routes_mapping)} ATLAS stops")
        
    # Extract HRDF routes from unified data
    atlas_hrdf_routes_mapping = {}
    for sloid, entries in atlas_routes_mapping_unified.items():
        hrdf_entries = [e for e in entries if e.get('source') == 'hrdf']
        if hrdf_entries:
            atlas_hrdf_routes_mapping[str(sloid)] = [
                {
                    'line_name': e.get('line_name'),
                    'direction_name': e.get('direction_name'),
                    'direction_uic': e.get('direction_uic'),
                }
                for e in hrdf_entries
            ]
    print(f"Extracted HRDF route information for {len(atlas_hrdf_routes_mapping)} ATLAS stops")
        
    # Load OSM routes
    osm_routes_mapping = {}
    try:
        print("Loading OSM routes...")
        if osm_routes_df is None:
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

def load_unified_route_data() -> dict:
    """Load unified routes as a single mapping sloid -> list[route_entry]."""
    unified_path = "data/processed/atlas_routes_unified.csv"
    mapping = {}
    try:
        df = pd.read_csv(unified_path)
        for sloid, group in df.groupby('sloid'):
            if pd.isna(sloid):
                continue
            entries = []
            for _, row in group.iterrows():
                entries.append({
                    'source': row.get('source'),
                    'route_id': row.get('route_id') if pd.notna(row.get('route_id')) else None,
                    'route_id_normalized': row.get('route_id_normalized') if pd.notna(row.get('route_id_normalized')) else None,
                    'route_name_short': row.get('route_name_short') if pd.notna(row.get('route_name_short')) else None,
                    'route_name_long': row.get('route_name_long') if pd.notna(row.get('route_name_long')) else None,
                    'line_name': row.get('line_name') if pd.notna(row.get('line_name')) else None,
                    'direction_id': str(int(float(row.get('direction_id')))) if pd.notna(row.get('direction_id')) else None,
                    'direction_name': row.get('direction_name') if pd.notna(row.get('direction_name')) else None,
                    'direction_uic': row.get('direction_uic') if pd.notna(row.get('direction_uic')) else None,
                    'evidence': row.get('evidence') if pd.notna(row.get('evidence')) else None,
                    'as_of': row.get('as_of') if pd.notna(row.get('as_of')) else None,
                })
            mapping[str(sloid)] = entries
    except FileNotFoundError:
        print("INFO: Unified routes file (atlas_routes_unified.csv) not found.")
    except Exception as e:
        print(f"Error loading unified routes: {e}")
    return mapping

def _normalize_route_id_for_matching(route_id):
    """Remove year codes (j24, j25, etc.) from route IDs for fuzzy matching."""
    if not route_id:
        return None
    import re
    # Replace j24, j25, j22, etc. with a generic jXX for comparison
    normalized = re.sub(r'-j\d+', '-jXX', str(route_id))
    return normalized

def build_route_direction_mapping(osm_routes_df: pd.DataFrame = None):
    """Build mappings for routes and directions using unified Atlas data.

    If osm_routes_df is provided, reuse it instead of re-reading the CSV to avoid duplicated IO.
    """
    # Maps for route+direction to nodes
    osm_route_dir_to_nodes = {}
    atlas_route_dir_to_sloids = {}
    atlas_line_diruic_to_sloids = {}
    
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
        if osm_routes_df is None:
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
        
        # Process ATLAS unified routes
        try:
            unified_df = pd.read_csv("data/processed/atlas_routes_unified.csv")
            for _, row in unified_df.iterrows():
                sloid = row.get('sloid')
                if pd.isna(sloid):
                    continue
                source = row.get('source')
                if source == 'gtfs':
                    if pd.notna(row.get('route_id')) and pd.notna(row.get('direction_id')):
                        route_id = str(row.get('route_id'))
                        direction_id = str(int(float(row.get('direction_id'))))
                        key = (route_id, direction_id)
                        if key not in atlas_route_dir_to_sloids:
                            atlas_route_dir_to_sloids[key] = {
                                'sloids': [],
                                'route_short_name': row.get('route_name_short') if pd.notna(row.get('route_name_short')) else None,
                                'route_long_name': row.get('route_name_long') if pd.notna(row.get('route_name_long')) else None,
                                'route_id_normalized': row.get('route_id_normalized') if pd.notna(row.get('route_id_normalized')) else None,
                            }
                        atlas_route_dir_to_sloids[key]['sloids'].append(str(sloid))
                elif source == 'hrdf':
                    if pd.notna(row.get('line_name')) and pd.notna(row.get('direction_uic')):
                        line_name = str(row.get('line_name'))
                        direction_uic = str(row.get('direction_uic'))
                        key = (line_name, direction_uic)
                        if key not in atlas_line_diruic_to_sloids:
                            atlas_line_diruic_to_sloids[key] = {
                                'sloids': [],
                                'direction_name': row.get('direction_name') if pd.notna(row.get('direction_name')) else None
                            }
                        atlas_line_diruic_to_sloids[key]['sloids'].append(str(sloid))
        except FileNotFoundError:
            print("INFO: Unified routes file (atlas_routes_unified.csv) not found, skipping Atlas unified route/direction mapping.")
        
        print(f"Built route+direction to nodes mapping for {len(osm_route_dir_to_nodes)} OSM routes")
        print(f"Built GTFS route+direction to sloids mapping for {len(atlas_route_dir_to_sloids)} ATLAS routes")
        print(f"Built HRDF line+direction_uic to sloids mapping for {len(atlas_line_diruic_to_sloids)} ATLAS routes")
    except Exception as e:
        print(f"Error building route-direction mappings: {e}")
        
    return osm_route_dir_to_nodes, atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids

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
    # Avoid re-reading the same CSV twice by preloading and passing to both loaders
    try:
        _preloaded_osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
    except Exception:
        _preloaded_osm_routes_df = None
    atlas_routes_mapping, atlas_hrdf_routes_mapping, osm_routes_mapping = load_route_data(osm_routes_df=_preloaded_osm_routes_df)
    atlas_routes_mapping_unified = load_unified_route_data()
    
    # Build route+direction to nodes/sloids mappings for routes_and_directions table
    osm_route_dir_to_nodes, atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids = build_route_direction_mapping(osm_routes_df=_preloaded_osm_routes_df)
    
    # Keep track of processed detail records to avoid duplicates
    processed_sloids = set()
    processed_osm_node_ids = set()
    
    # Pre-check for duplicate sloids in source data (use Counter to avoid O(n^2))
    from collections import Counter
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

    # --- Precompute OSM duplicate nodes by (uic_ref, local_ref) BEFORE inserting matched ---
    def _is_platform_like(pt):
        return pt in ('platform', 'stop_position')
    osm_nodes_by_uic_local_ref = {}
    def _add_osm_dup_candidate(uic_val, local_ref_val, node_id_val, pt_val):
        try:
            if not uic_val or not local_ref_val:
                return
            if not _is_platform_like(pt_val):
                return
            key = (
                str(uic_val).strip(),
                str(local_ref_val).strip().lower()
            )
            if key not in osm_nodes_by_uic_local_ref:
                osm_nodes_by_uic_local_ref[key] = set()
            osm_nodes_by_uic_local_ref[key].add(str(node_id_val))
        except Exception:
            pass
    # From matched
    for rec in base_data.get('matched', []):
        uic = safe_value(rec.get('osm_uic_ref'))
        if uic:
            _add_osm_dup_candidate(uic, safe_value(rec.get('osm_local_ref')), safe_value(rec.get('osm_node_id')), safe_value(rec.get('osm_public_transport')))
    # From unmatched_osm
    for rec in base_data.get('unmatched_osm', []):
        tags = rec.get('tags', {}) if isinstance(rec.get('tags', {}), dict) else {}
        uic = safe_value(tags.get('uic_ref'))
        if uic:
            _add_osm_dup_candidate(uic, tags.get('local_ref'), rec.get('node_id'), tags.get('public_transport'))
    duplicate_osm_node_ids = set()
    for _key, node_ids in osm_nodes_by_uic_local_ref.items():
        if len(node_ids) >= 2:
            duplicate_osm_node_ids.update(node_ids)

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
        # If this record was manually matched in a previous run and persisted, carry the flag
        if safe_value(rec.get('match_type')) == 'manual':
            # conservative: mark as persistent if we have a persistent entry
            stop_record.manual_is_persistent = True
        
        # Create problems with additional metadata for better sorting
        if problems.get('distance_problem'):
            # For distance problems, store the distance for efficient sorting
            distance_priority = compute_distance_priority(rec)
            distance_problem = Problem(
                problem_type='distance',
                solution=None,  # Will be set by persistent solutions if available
                is_persistent=False,
                priority=distance_priority
            )
            stop_record.problems.append(distance_problem)
            
        if problems.get('attributes_problem'):
            attributes_priority = compute_attributes_priority(rec)
            attributes_problem = Problem(
                problem_type='attributes',
                solution=None,
                is_persistent=False,
                priority=attributes_priority
            )
            stop_record.problems.append(attributes_problem)

        # Duplicates: ATLAS duplicates (priority 2) and OSM duplicates (priority 1)
        if sloid and str(sloid) in duplicate_sloid_map:
            stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=2))
        if osm_node_id and str(osm_node_id) in duplicate_osm_node_ids:
            stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=1))

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
                routes_unified=atlas_routes_mapping_unified.get(sloid, None) if atlas_routes_mapping_unified else None,
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

    # Precompute structures for unmatched priority classification
    # Build OSM coordinate set from matched and unmatched data
    osm_points = []  # list of (x,y,z)
    osm_coords_source = []  # list of (lat, lon)
    def _to_xyz(lat, lon):
        lat_rad = math.radians(float(lat))
        lon_rad = math.radians(float(lon))
        return (
            math.cos(lat_rad) * math.cos(lon_rad),
            math.cos(lat_rad) * math.sin(lon_rad),
            math.sin(lat_rad)
        )
    # OSM from matched records
    for rec in base_data.get('matched', []):
        lat = safe_value(rec.get('osm_lat'))
        lon = safe_value(rec.get('osm_lon'))
        if lat is not None and lon is not None:
            osm_points.append(_to_xyz(lat, lon))
            osm_coords_source.append((float(lat), float(lon)))
    # OSM from unmatched_osm
    for rec in base_data.get('unmatched_osm', []):
        lat = safe_value(rec.get('lat'))
        lon = safe_value(rec.get('lon'))
        if lat is not None and lon is not None:
            osm_points.append(_to_xyz(lat, lon))
            osm_coords_source.append((float(lat), float(lon)))
    osm_kdtree = KDTree(osm_points) if osm_points else None

    # Build ATLAS coordinate set from matched and unmatched
    atlas_points = []
    atlas_coords_source = []
    for rec in base_data.get('matched', []):
        lat = safe_value(rec.get('csv_lat'))
        lon = safe_value(rec.get('csv_lon'))
        if lat is not None and lon is not None:
            atlas_points.append(_to_xyz(lat, lon))
            atlas_coords_source.append((float(lat), float(lon)))
    for rec in base_data.get('unmatched_atlas', []):
        lat = safe_value(rec.get('wgs84North'))
        lon = safe_value(rec.get('wgs84East'))
        if lat is not None and lon is not None:
            atlas_points.append(_to_xyz(lat, lon))
            atlas_coords_source.append((float(lat), float(lon)))
    atlas_kdtree = KDTree(atlas_points) if atlas_points else None

    # Build counts by UIC
    atlas_count_by_uic = {}
    for rec in base_data.get('matched', []):
        uic = safe_value(rec.get('number'))
        if uic is None: continue
        key = str(uic)
        atlas_count_by_uic[key] = atlas_count_by_uic.get(key, 0) + 1
    for rec in base_data.get('unmatched_atlas', []):
        uic = safe_value(rec.get('number'))
        if uic is None: continue
        key = str(uic)
        atlas_count_by_uic[key] = atlas_count_by_uic.get(key, 0) + 1

    osm_count_by_uic = {}
    osm_platform_count_by_uic = {}
    # From matched
    for rec in base_data.get('matched', []):
        uic = safe_value(rec.get('osm_uic_ref'))
        if uic:
            key = str(uic)
            osm_count_by_uic[key] = osm_count_by_uic.get(key, 0) + 1
            if _is_platform_like(safe_value(rec.get('osm_public_transport'))):
                osm_platform_count_by_uic[key] = osm_platform_count_by_uic.get(key, 0) + 1
    # From unmatched_osm
    for rec in base_data.get('unmatched_osm', []):
        uic = None
        tags = rec.get('tags', {}) if isinstance(rec.get('tags', {}), dict) else {}
        if 'uic_ref' in tags:
            uic = safe_value(tags.get('uic_ref'))
        if uic:
            key = str(uic)
            osm_count_by_uic[key] = osm_count_by_uic.get(key, 0) + 1
            pt = tags.get('public_transport')
            if _is_platform_like(pt):
                osm_platform_count_by_uic[key] = osm_platform_count_by_uic.get(key, 0) + 1

    def _nearest_distance_to(points_tree, points_list, target_lat, target_lon):
        if points_tree is None or not points_list:
            return None
        x, y, z = _to_xyz(target_lat, target_lon)
        # KDTree was built on chord distances in 3D; we need haversine distance
        # Compute nearest index by querying Euclidean distance in 3D space
        dist, idx = points_tree.query((x, y, z), k=1)
        # Convert back to haversine distance using great-circle angle from dot product
        # Recompute angle between unit vectors to avoid precision loss
        try:
            # Clip dot product to [-1,1]
            ux, uy, uz = x, y, z
            vx, vy, vz = points_list[idx]
            # Recover lat/lon from stored xyz is not available here; we stored xyz only in points_tree
            # Instead compute angle from Euclidean distance of unit vectors: ||u - v|| = sqrt(2 - 2 cos(theta))
            # => cos(theta) = 1 - (||u - v||^2)/2
            euclid = dist
            cos_theta = 1 - (euclid * euclid) / 2.0
            cos_theta = max(-1.0, min(1.0, cos_theta))
            theta = math.acos(cos_theta)
            meters = 6371000.0 * theta
            return meters
        except Exception:
            return None

    def compute_unmatched_priority_for_atlas(rec):
        # Inputs
        uic = safe_value(rec.get('number'))
        nearest = _nearest_distance_to(osm_kdtree, osm_points, safe_value(rec.get('wgs84North')), safe_value(rec.get('wgs84East')))
        # P1 conditions
        if uic is not None:
            if osm_count_by_uic.get(str(uic), 0) == 0:
                return 1
        if nearest is None:
            # Treat no OSM available as worse than 80m
            return 1
        if nearest > 80:
            return 1
        # P2 conditions
        if nearest > 50:
            return 2
        if uic is not None:
            key = str(uic)
            if osm_platform_count_by_uic.get(key, 0) != atlas_count_by_uic.get(key, 0):
                return 2
        # P3
        return 3

    def compute_unmatched_priority_for_osm(rec):
        tags = rec.get('tags', {}) if isinstance(rec.get('tags', {}), dict) else {}
        uic = safe_value(tags.get('uic_ref'))
        nearest = _nearest_distance_to(atlas_kdtree, atlas_points, safe_value(rec.get('lat')), safe_value(rec.get('lon')))
        # P1: zero opposite UIC
        if uic is not None:
            if atlas_count_by_uic.get(str(uic), 0) == 0:
                return 1
        # P2: radius or platform mismatch
        if nearest is None or nearest > 50:
            return 2
        if uic is not None:
            key = str(uic)
            if osm_platform_count_by_uic.get(key, 0) != atlas_count_by_uic.get(key, 0):
                return 2
        # P3
        return 3

    # --- Insert Unmatched ATLAS Records ---
    unmatched_records = base_data.get('unmatched_atlas', [])
    for rec in unmatched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'wgs84North', 'wgs84East', 'sloid', rec.get('sloid'), 'unmatched ATLAS'
        )
        if atlas_lat is None: continue

        sloid = safe_value(rec.get('sloid'))
        match_type_for_unmatched = 'no_nearby_counterpart' if sloid in no_nearby_osm_sloids else None

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
        
        if problems.get('unmatched_problem'):
            unmatched_priority = compute_unmatched_priority_for_atlas(rec)
            unmatched_problem = Problem(
                problem_type='unmatched',
                solution=None,
                is_persistent=False,
                priority=unmatched_priority
            )
            stop_record.problems.append(unmatched_problem)

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
                routes_unified=atlas_routes_mapping_unified.get(sloid, None) if atlas_routes_mapping_unified else None,
                atlas_note=None,
                atlas_note_is_persistent=False
            )
            session.add(atlas_record)
            processed_sloids.add(sloid)

        # Duplicates: ATLAS duplicates (priority 2)
        if sloid and str(sloid) in duplicate_sloid_map:
            stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=2))

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

        if problems.get('unmatched_problem'):
            unmatched_priority = compute_unmatched_priority_for_osm(rec)
            unmatched_problem = Problem(
                problem_type='unmatched',
                solution=None,
                is_persistent=False,
                priority=unmatched_priority
            )
            stop_record.problems.append(unmatched_problem)

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
        
        # Duplicates: OSM duplicates (priority 1)
        if osm_node_id and str(osm_node_id) in duplicate_osm_node_ids:
            stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=1))
            
    session.commit()

    # --- Insert Route and Direction Records ---
    matched_routes = 0
    osm_only_routes = 0
    atlas_only_routes = 0
    
    for (osm_route_id, direction_id), osm_data in osm_route_dir_to_nodes.items():
        atlas_data = atlas_route_dir_to_sloids.get((osm_route_id, direction_id))
        atlas_matched_route_id = None

        if atlas_data:
            atlas_matched_route_id = osm_route_id
        else:
            osm_route_normalized = _normalize_route_id_for_matching(osm_route_id)
            if osm_route_normalized:
                for (atlas_route_id, atlas_direction_id), atlas_info in atlas_route_dir_to_sloids.items():
                    if (
                        atlas_direction_id == direction_id
                        and _normalize_route_id_for_matching(atlas_route_id) == osm_route_normalized
                    ):
                        atlas_data = atlas_info
                        atlas_matched_route_id = atlas_route_id
                        break

        if atlas_data and atlas_matched_route_id:
            route_record = RouteAndDirection(
                direction_id=direction_id,
                osm_route_id=osm_route_id,
                osm_nodes_json=osm_data['nodes'],
                atlas_route_id=atlas_matched_route_id,
                atlas_sloids_json=atlas_data['sloids'],
                route_name=osm_data['route_name'],
                route_short_name=atlas_data['route_short_name'],
                route_long_name=atlas_data['route_long_name'],
                route_type=None,
                match_type='matched',
                source='gtfs',
                route_id_normalized=atlas_data.get('route_id_normalized') if isinstance(atlas_data, dict) else None,
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
                match_type='osm_only',
                source='gtfs'
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
            match_type='atlas_only',
            source='gtfs',
            route_id_normalized=atlas_data.get('route_id_normalized') if isinstance(atlas_data, dict) else None,
        )
        atlas_only_routes += 1
        session.add(route_record)

    # Add HRDF-only consolidated rows
    for (line_name, direction_uic), atlas_data in atlas_line_diruic_to_sloids.items():
        route_record = RouteAndDirection(
            direction_id=None,
            osm_route_id=None,
            osm_nodes_json=None,
            atlas_route_id=None,
            atlas_sloids_json=atlas_data['sloids'],
            route_name=None,
            route_short_name=None,
            route_long_name=None,
            route_type=None,
            match_type='atlas_only',
            source='hrdf',
            atlas_line_name=line_name,
            direction_uic=direction_uic,
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
    isolated_problems = session.query(Problem).filter(Problem.problem_type == 'unmatched').count()
    attributes_problems = session.query(Problem).filter(Problem.problem_type == 'attributes').count()
    
    multiple_problems = session.query(Problem.stop_id).group_by(Problem.stop_id).having(func.count(Problem.stop_id) > 1).count()
    
    stops_with_problems = session.query(func.count(func.distinct(Problem.stop_id))).scalar()
    clean_entries = total_stops - stops_with_problems

    print("\n==== PROBLEM DETECTION SUMMARY ====")
    print(f"Total stops imported: {total_stops}")
    print(f"Distance problems: {distance_problems}")
    print(f"Unmatched problems: {isolated_problems}")
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