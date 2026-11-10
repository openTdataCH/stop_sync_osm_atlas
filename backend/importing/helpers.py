import math


def safe_value(val, default=None):
    """Safely handle NaN, None, and other problematic values for DB inserts"""
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    return val


def get_osm_node_type(tags):
    """Classify an OSM stop element from its tags."""
    public_transport = tags.get('public_transport')
    if public_transport == 'stop_position':
        return 'stop_position'
    if public_transport == 'station' or tags.get('railway') == 'station':
        return 'railway_station'
    if tags.get('amenity') == 'ferry_terminal':
        return 'ferry_terminal'
    if tags.get('aerialway'):
        return 'aerialway'
    if public_transport == 'platform':
        return 'platform'
    return None
