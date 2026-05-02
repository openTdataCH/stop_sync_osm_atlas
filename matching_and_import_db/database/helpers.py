import math
import pandas as pd
from sqlalchemy import func
from backend.models import Problem

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
    """Determine the osm_node_type based on OSM tags or ORM-like dict fields."""
    if not isinstance(rec, dict):
        return None

    # Accept both shapes:
    # 1) {'tags': {...}} (nested)
    # 2) {...} where keys are already OSM tag names (flat)
    tags = rec.get('tags') if isinstance(rec.get('tags'), dict) else rec

    if is_osm_unmatched:
        osm_public_transport = tags.get('public_transport')
        osm_railway = tags.get('railway')
        osm_amenity = tags.get('amenity')
        osm_aerialway = tags.get('aerialway')
    else:
        osm_public_transport = rec.get('osm_public_transport')
        osm_railway = rec.get('osm_railway')
        osm_amenity = rec.get('osm_amenity')
        osm_aerialway = rec.get('osm_aerialway')

    if osm_public_transport == 'stop_position':
        return 'stop_position'
    if (osm_public_transport == 'station' or osm_railway == 'station') and osm_public_transport != 'stop_position':
        return 'railway_station'
    if osm_amenity == 'ferry_terminal':
        return 'ferry_terminal'
    if osm_aerialway and osm_aerialway != '':
        return 'aerialway'
    if osm_public_transport == 'platform':
        return 'platform'
    return None

def validate_coordinates(rec, lat_key, lon_key, id_key, id_value, record_type):
    """Validate and extract coordinates from a record."""
    try:
        lat = safe_value(rec.get(lat_key))
        lon = safe_value(rec.get(lon_key))
        
        if lat is None or lon is None:
            print(f"Warning: Missing coordinates for {record_type} {id_key}={id_value}")
            return None, None
        
        lat_float = float(lat)
        lon_float = float(lon)
        
        if math.isnan(lat_float) or math.isinf(lat_float) or math.isnan(lon_float) or math.isinf(lon_float):
            print(f"Warning: Invalid coordinates (NaN/Inf) for {record_type} {id_key}={id_value}")
            return None, None
        
        if not (-90 <= lat_float <= 90) or not (-180 <= lon_float <= 180):
            print(f"Warning: Coordinates out of range for {record_type} {id_key}={id_value}: lat={lat_float}, lon={lon_float}")
            return None, None
        
        return lat_float, lon_float
    except (ValueError, TypeError) as e:
        print(f"Warning: Error parsing coordinates for {record_type} {id_key}={id_value}: {e}")
        return None, None

def get_from_tags(rec, tag_key, default=None):
    """Extract a value from OSM tags dictionary."""
    if tag_key in rec:
        return safe_value(rec[tag_key], default)
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
        ))
