import math
from math import radians, cos, sin
from scipy.spatial import KDTree
import numpy as np

def to_xyz(lat, lon):
    """Convert lat/lon in degrees to 3D unit-sphere coordinates."""
    lat_rad = math.radians(float(lat))
    lon_rad = math.radians(float(lon))
    return (
        math.cos(lat_rad) * math.cos(lon_rad),
        math.cos(lat_rad) * math.sin(lon_rad),
        math.sin(lat_rad)
    )

def meters_to_unit_chord_radius(distance_meters):
    """Convert meters to unit-sphere chord radius used by KDTree on unit vectors."""
    theta = float(distance_meters) / 6371000.0
    return math.sqrt(max(0.0, 2.0 - 2.0 * math.cos(theta)))

def build_kdtree_from_nodes(xml_nodes):
    """Build KDTree and supporting lists from xml_nodes dict keyed by (lat, lon).

    Returns: (kd_tree_or_None, points_list, nodes_list)
    where nodes_list is a list of ((lat, lon), node_dict)
    """
    points = []
    nodes_list = []
    for (lat, lon), node in xml_nodes.items():
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            continue
        x, y, z = to_xyz(lat_f, lon_f)
        points.append((x, y, z))
        nodes_list.append(((lat_f, lon_f), node))

    if points:
        tree = KDTree(np.array(points))
        return tree, points, nodes_list
    return None, [], []


