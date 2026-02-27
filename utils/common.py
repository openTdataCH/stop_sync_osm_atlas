def is_osm_station(osm_node):
    """Return True if an OSM node represents a station (railway or public_transport),
    excluding aerialway stations which are handled separately.
    """
    tags = osm_node.get('tags', {})
    # If it's an aerialway station, do not mark as station here
    if tags.get('aerialway') == 'station':
        return False
    # Otherwise treat railway/public_transport station as a station
    if tags.get('railway') == 'station' or tags.get('public_transport') == 'station':
        return True
    return False

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the Haversine distance (in meters) between two points.
    Returns None on invalid input rather than throwing.
    """
    from math import radians, sin, cos, sqrt, atan2
    try:
        R = 6371000.0  # meters
        lat1_f, lon1_f, lat2_f, lon2_f = float(lat1), float(lon1), float(lat2), float(lon2)
        rad_lat1, rad_lon1, rad_lat2, rad_lon2 = map(radians, [lat1_f, lon1_f, lat2_f, lon2_f])
        dlat = rad_lat2 - rad_lat1
        dlon = rad_lon2 - rad_lon1
        a = sin(dlat/2)**2 + cos(rad_lat1)*cos(rad_lat2)*sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c
    except Exception:
        return None


