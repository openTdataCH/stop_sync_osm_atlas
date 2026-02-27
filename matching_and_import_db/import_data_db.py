from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
import math
import pandas as pd
from matching_and_import_db.orchestrator import run_matching
from matching_and_import_db.problem_detection import ProblemContext, run_problem_pipeline, STOP_PROBLEM_PIPELINE
from matching_and_import_db.problem_detection.result import ProblemResult
import os
import time

# Import models
from backend.models import Stop, AtlasStop, OsmNode, RouteAndDirection, Problem
from backend.services.import_persistence import apply_persistent_solutions as apply_persistent_solutions_service
from backend.services.stats_export import export_pipeline_stats, save_stats_to_file

from utils.timing import timed_phase, format_progress

# Database Setup
DATABASE_URI = os.getenv('DATABASE_URI', 'postgresql+psycopg://stops_user:1234@localhost:5432/import_db')
USER_INPUT_DATABASE_URI = os.getenv('USER_INPUT_DATABASE_URI', 'postgresql+psycopg://stops_user:1234@localhost:5432/user_input_db')

engine = create_engine(DATABASE_URI)
user_input_engine = create_engine(USER_INPUT_DATABASE_URI)

# Bind the session to the reproducible DB (the default) but we might need cross-talk later.
# For import, we primarily write to the reproducible db.
Session = sessionmaker(bind=engine)
session = Session()

user_input_Session = sessionmaker(bind=user_input_engine)
user_input_session = user_input_Session()

def make_point_geom(lat, lon):
    """Create a PostGIS POINT geometry (SRID 4326) from lat/lon, or None if missing."""
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    return func.ST_SetSRID(func.ST_MakePoint(lon_f, lat_f), 4326)


def safe_value(val, default=None):
    """Safely handle NaN, None, and other problematic values for DB inserts"""
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

def ensure_schema_updated():
    """Run Alembic migrations to ensure the DB schema is up to date."""
    try:
        # Import here to avoid hard dependency during pure data-processing runs
        from flask_migrate import upgrade
        from backend.app import app

        with app.app_context():
            # Runs migrations in the default "migrations" directory to HEAD
            upgrade()
        print("Database schema migrated to latest revision.")
    except Exception as e:
        print(f"Error running migrations: {e}")
        raise

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

def apply_problem_results(stop_record, results: list):
    """Convert ProblemResult objects into ORM Problem records on a Stop."""
    for r in results:
        stop_record.problems.append(Problem(
            problem_type=r.problem_type,
            priority=r.priority,
            solution=None,
            is_persistent=False,
        ))
        if r.has_atlas_duplicate:
            stop_record.has_atlas_duplicate = True
        if r.has_osm_duplicate:
            stop_record.has_osm_duplicate = True


from utils.route_id import normalize_route_id


def _safe_direction_id(val):
    """Convert direction_id to a clean string ('0' or '1'), or None."""
    try:
        if pd.isna(val):
            return None
        return str(int(float(val)))
    except (ValueError, TypeError):
        return None


def _nan_to_none(val):
    """Convert pandas NaN/NaT to None."""
    if pd.isna(val):
        return None
    return val


def _load_unified_routes_df():
    """Read atlas_routes_unified.csv once and return the DataFrame (or empty)."""
    unified_path = "data/processed/atlas_routes_unified.csv"
    try:
        return pd.read_csv(unified_path, low_memory=False, dtype=str)
    except FileNotFoundError:
        print("INFO: Unified routes file (atlas_routes_unified.csv) not found.")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error loading unified routes: {e}")
        return pd.DataFrame()


def _build_unified_mapping(unified_df: pd.DataFrame) -> dict:
    """Build sloid -> list[route_entry] mapping from the unified DataFrame (vectorized)."""
    if unified_df.empty:
        return {}
    df = unified_df.dropna(subset=['sloid']).copy()
    # Replace NaN with None for clean dict output
    df = df.where(df.notna(), None)
    # Normalize direction_id in bulk
    df['direction_id'] = df['direction_id'].apply(_safe_direction_id)
    records = df.to_dict(orient='records')
    mapping = {}
    for rec in records:
        sloid = str(rec['sloid'])
        mapping.setdefault(sloid, []).append(rec)
    return mapping


def _build_osm_routes_mapping(osm_routes_df: pd.DataFrame) -> dict:
    """Build node_id -> list[route_info] mapping from OSM routes (vectorized)."""
    if osm_routes_df is None or osm_routes_df.empty:
        return {}
    df = osm_routes_df.copy()
    valid = df[df['node_id'].notna() & (df['gtfs_route_id'].notna() | df['route_name'].notna())].copy()
    valid['direction_id_clean'] = valid['direction_id'].apply(_safe_direction_id)
    valid['route_id_clean'] = valid['gtfs_route_id'].where(valid['gtfs_route_id'].notna(), None)
    valid['route_name_clean'] = valid['route_name'].where(valid['route_name'].notna(), None)
    mapping = {}
    for node_id, group in valid.groupby('node_id', sort=False):
        mapping[str(node_id)] = [
            {'route_id': r.route_id_clean, 'direction_id': r.direction_id_clean, 'route_name': r.route_name_clean}
            for r in group.itertuples(index=False)
        ]
    return mapping


def _find_gtfs_routes_txt():
    """Locate the GTFS routes.txt file in data/raw/gtfs*/."""
    gtfs_root = "data/raw"
    if not os.path.isdir(gtfs_root):
        return None
    for fname in os.listdir(gtfs_root):
        if fname.startswith("gtfs") and os.path.isdir(os.path.join(gtfs_root, fname)):
            candidate = os.path.join(gtfs_root, fname, "routes.txt")
            if os.path.exists(candidate):
                return candidate
    return None


def _build_route_name_to_id() -> dict:
    """Build fallback mapping from GTFS route names to route_id."""
    path = _find_gtfs_routes_txt()
    if not path:
        return {}
    try:
        gdf = pd.read_csv(path, dtype=str, usecols=['route_id', 'route_short_name', 'route_long_name'])
        mapping = {}
        for col in ('route_short_name', 'route_long_name'):
            mask = gdf[col].notna()
            for name, rid in zip(gdf.loc[mask, col].str.strip(), gdf.loc[mask, 'route_id'].str.strip()):
                mapping[name] = rid
        return mapping
    except Exception as e:
        print(f"Warning: Failed to build GTFS route name mapping: {e}")
        return {}


def _build_osm_route_dir_to_nodes(osm_routes_df: pd.DataFrame, route_name_to_id: dict) -> dict:
    """Build (route_id, direction_id) -> {nodes, route_name} from OSM routes (vectorized)."""
    if osm_routes_df is None or osm_routes_df.empty:
        return {}
    df = osm_routes_df.copy()
    df = df[df['node_id'].notna() & (df['gtfs_route_id'].notna() | df['route_name'].notna())].copy()
    # Resolve route_id with fallback
    df['resolved_route_id'] = df['gtfs_route_id'].where(
        df['gtfs_route_id'].notna() & (df['gtfs_route_id'].astype(str).str.strip() != ''),
        df['route_name'].map(route_name_to_id)
    )
    df = df[df['resolved_route_id'].notna()].copy()
    df['resolved_route_id'] = df['resolved_route_id'].astype(str).str.strip()
    df['dir_clean'] = df['direction_id'].apply(_safe_direction_id)
    # Expand rows without direction to both 0 and 1
    has_dir = df[df['dir_clean'].notna()].copy()
    no_dir = df[df['dir_clean'].isna()].copy()
    expanded = []
    if not has_dir.empty:
        expanded.append(has_dir[['node_id', 'resolved_route_id', 'dir_clean', 'route_name']].copy())
    if not no_dir.empty:
        for d in ['0', '1']:
            part = no_dir[['node_id', 'resolved_route_id', 'route_name']].copy()
            part['dir_clean'] = d
            expanded.append(part)
    if not expanded:
        return {}
    all_rows = pd.concat(expanded, ignore_index=True)
    result = {}
    for (route_id, direction_id), grp in all_rows.groupby(['resolved_route_id', 'dir_clean'], sort=False):
        result[(route_id, direction_id)] = {
            'nodes': grp['node_id'].astype(str).tolist(),
            'route_name': _nan_to_none(grp['route_name'].iloc[0]) if grp['route_name'].notna().any() else None,
        }
    return result


def _build_atlas_route_dir_mappings(unified_df: pd.DataFrame):
    """Build GTFS and HRDF route-direction groupings from unified DataFrame.

    Returns (atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids).
    """
    atlas_route_dir_to_sloids = {}
    atlas_line_diruic_to_sloids = {}
    if unified_df.empty:
        return atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids

    df = unified_df.dropna(subset=['sloid']).copy()
    df['direction_id_clean'] = df['direction_id'].apply(_safe_direction_id)

    # GTFS routes
    gtfs = df[(df['source'] == 'gtfs') & df['route_id'].notna() & df['direction_id_clean'].notna()]
    for (route_id, direction_id), grp in gtfs.groupby(['route_id', 'direction_id_clean'], sort=False):
        first = grp.iloc[0]
        atlas_route_dir_to_sloids[(str(route_id), str(direction_id))] = {
            'sloids': grp['sloid'].astype(str).tolist(),
            'route_short_name': _nan_to_none(first.get('route_name_short')),
            'route_long_name': _nan_to_none(first.get('route_name_long')),
            'route_id_normalized': _nan_to_none(first.get('route_id_normalized')),
        }

    # HRDF routes
    hrdf = df[(df['source'] == 'hrdf') & df['line_name'].notna() & df['direction_uic'].notna()]
    for (line_name, direction_uic), grp in hrdf.groupby(['line_name', 'direction_uic'], sort=False):
        first = grp.iloc[0]
        atlas_line_diruic_to_sloids[(str(line_name), str(direction_uic))] = {
            'sloids': grp['sloid'].astype(str).tolist(),
            'direction_name': _nan_to_none(first.get('direction_name')),
        }

    return atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids


def load_all_route_data(osm_routes_df: pd.DataFrame = None):
    """Load all route data in a single pass over each CSV.

    Returns a dict with all route mappings needed for the import:
      - atlas_routes_mapping_unified: sloid -> list[route_entry] (for JSONB on AtlasStop)
      - osm_routes_mapping: node_id -> list[route_info] (for JSONB on OsmNode)
      - osm_route_dir_to_nodes: (route_id, dir) -> {nodes, route_name}
      - atlas_route_dir_to_sloids: (route_id, dir) -> {sloids, ...}
      - atlas_line_diruic_to_sloids: (line_name, dir_uic) -> {sloids, ...}
    """
    # 1. Read atlas_routes_unified.csv ONCE
    unified_df = _load_unified_routes_df()
    atlas_routes_mapping_unified = _build_unified_mapping(unified_df)
    atlas_route_dir_to_sloids, atlas_line_diruic_to_sloids = _build_atlas_route_dir_mappings(unified_df)
    print(f"Loaded unified route information for {len(atlas_routes_mapping_unified)} ATLAS stops")
    print(f"Built GTFS route+direction to sloids mapping for {len(atlas_route_dir_to_sloids)} ATLAS routes")
    print(f"Built HRDF line+direction_uic to sloids mapping for {len(atlas_line_diruic_to_sloids)} ATLAS routes")

    # 2. Read osm_nodes_with_routes.csv ONCE
    if osm_routes_df is None:
        try:
            osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
        except Exception:
            osm_routes_df = pd.DataFrame()

    osm_routes_mapping = _build_osm_routes_mapping(osm_routes_df)
    route_name_to_id = _build_route_name_to_id()
    osm_route_dir_to_nodes = _build_osm_route_dir_to_nodes(osm_routes_df, route_name_to_id)
    print(f"Loaded route information for {len(osm_routes_mapping)} OSM nodes")
    print(f"Built route+direction to nodes mapping for {len(osm_route_dir_to_nodes)} OSM routes")

    return {
        'atlas_routes_mapping_unified': atlas_routes_mapping_unified,
        'osm_routes_mapping': osm_routes_mapping,
        'osm_route_dir_to_nodes': osm_route_dir_to_nodes,
        'atlas_route_dir_to_sloids': atlas_route_dir_to_sloids,
        'atlas_line_diruic_to_sloids': atlas_line_diruic_to_sloids,
    }

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
    with timed_phase("DB: migrations"):
        ensure_schema_updated()
    
    with timed_phase("DB: truncate existing data"):
        print("Truncating existing data from database...")
        # Because import_db is fully rebuilt each run, TRUNCATE is safe and fast.
        # CASCADE handles the problems → stops FK automatically.
        from sqlalchemy import text
        session.execute(text("TRUNCATE TABLE problems, stops, atlas_stops, osm_nodes, routes_and_directions CASCADE"))
        session.commit()
        print("Existing data truncated. Starting new import.")
    
    with timed_phase("DB: load route mappings"):
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

    # --- Build problem detection context (KDTrees, UIC counts, duplicate maps) ---
    with timed_phase("DB: build problem context"):
        problem_ctx = ProblemContext.build(base_data, duplicate_sloid_map)

    # --- Insert Matched Records ---
    matched_records = base_data.get('matched', [])

    print("\nDetecting problems and importing matched records...")
    print("  Checks: distance, attributes, duplicates")

    BATCH_SIZE = int(os.getenv('DB_IMPORT_BATCH_SIZE', '5000'))
    _t0 = time.time()
    inserted = 0

    with timed_phase("DB: insert matched records"):
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

            stop_record = Stop(
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

            if sloid and sloid not in processed_sloids:
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
                print(f"  Committed batch: {format_progress(inserted, len(matched_records), start_time=_t0)}")

        # Final commit for any remainder
        session.commit()
        session.expunge_all()
        print(f"Imported {len(matched_records)} matched records")

    # --- Insert Unmatched ATLAS Records ---
    unmatched_records = base_data.get('unmatched_atlas', [])
    for rec in unmatched_records:
        atlas_lat, atlas_lon = validate_coordinates(
            rec, 'wgs84North', 'wgs84East', 'sloid', rec.get('sloid'), 'unmatched ATLAS'
        )
        if atlas_lat is None: continue

        sloid = safe_value(rec.get('sloid'))
        match_type_for_unmatched = 'no_nearby_counterpart' if sloid in no_nearby_osm_sloids else None
        rec['stop_type'] = 'atlas_unmatched'

        stop_record = Stop(
            sloid=sloid,
            stop_type='atlas_unmatched',
            match_type=match_type_for_unmatched,
            atlas_lat=atlas_lat,
            atlas_lon=atlas_lon,
            geom=make_point_geom(atlas_lat, atlas_lon),
        )

        apply_problem_results(stop_record, run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, rec))

        session.add(stop_record)

        if sloid and sloid not in processed_sloids:
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

        stop_record = Stop(
            stop_type='osm_unmatched',
            osm_node_id=osm_node_id,
            osm_lat=osm_lat,
            osm_lon=osm_lon,
            geom=make_point_geom(osm_lat, osm_lon),
        )

        apply_problem_results(stop_record, run_problem_pipeline(STOP_PROBLEM_PIPELINE, problem_ctx, rec))

        session.add(stop_record)

        if osm_node_id and osm_node_id not in processed_osm_node_ids:
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
    osm_only_routes = 0
    atlas_only_routes = 0
    
    routes_to_insert = []
    
    # Pre-build normalized index for ATLAS routes
    atlas_normalized_to_original = {}
    for (atlas_route_id, atlas_direction_id), atlas_info in atlas_route_dir_to_sloids.items():
        norm_id = normalize_route_id(atlas_route_id)
        if norm_id:
            atlas_normalized_to_original.setdefault((norm_id, atlas_direction_id), []).append(
                (atlas_route_id, atlas_info)
            )

    for (osm_route_id, direction_id), osm_data in osm_route_dir_to_nodes.items():
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
            
        routes_to_insert.append(route_record)
    
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
        routes_to_insert.append(route_record)

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
        routes_to_insert.append(route_record)
    
    session.bulk_save_objects(routes_to_insert)
    session.commit()
    print(f"Route statistics: {matched_routes} matched, {osm_only_routes} OSM-only, {atlas_only_routes} ATLAS-only")
    
    # Apply persistent solutions to newly created problems
    apply_persistent_solutions_service(session, user_input_session)
    
    # Count problems in the database
    total_stops = session.query(Stop).count()
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
    # Run the final pipeline to obtain base_data in-memory
    print("Running the final pipeline to obtain base data...")
    # Unpack the three return values
    base_data, duplicate_sloid_map_result, no_nearby_sloids = run_matching()
    # Directly import the in-memory base_data into the database
    print("Importing data into the database...")
    # Pass the new set of sloids to the import function
    import_to_database(base_data, duplicate_sloid_map_result, no_nearby_sloids)
    
    # Export statistics to data/stats.json
    export_stats_after_import(base_data, duplicate_sloid_map_result, no_nearby_sloids)
    
    print("Process completed successfully!")