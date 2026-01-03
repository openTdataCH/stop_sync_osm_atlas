import math
from math import radians, cos, sin
from typing import List, Tuple, Union
from scipy.spatial import KDTree
import numpy as np

def to_xyz(lat, lon) -> Tuple[float, float, float]:
    """Convert lat/lon in degrees to 3D unit-sphere coordinates.
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        
    Returns:
        Tuple of (x, y, z) Cartesian coordinates on the unit sphere
    """
    lat_rad = math.radians(float(lat))
    lon_rad = math.radians(float(lon))
    return (
        math.cos(lat_rad) * math.cos(lon_rad),
        math.cos(lat_rad) * math.sin(lon_rad),
        math.sin(lat_rad)
    )


def lat_lon_to_xyz_list(lat: float, lon: float) -> List[float]:
    """Convert lat/lon to 3D Cartesian as a list [x, y, z] for KDTree compatibility.
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        
    Returns:
        List of [x, y, z] Cartesian coordinates on the unit sphere
    """
    x, y, z = to_xyz(lat, lon)
    return [x, y, z]


def batch_to_xyz(coords: List[Tuple[float, float]]) -> np.ndarray:
    """Vectorized conversion of multiple lat/lon pairs to 3D Cartesian.
    
    This is more efficient than calling to_xyz() in a loop for large datasets.
    
    Args:
        coords: List of (lat, lon) tuples in degrees
        
    Returns:
        np.ndarray of shape (N, 3) with [x, y, z] coordinates for each input point
    """
    if not coords:
        return np.array([]).reshape(0, 3)
    arr = np.array(coords, dtype=np.float64)
    lat_rad = np.radians(arr[:, 0])
    lon_rad = np.radians(arr[:, 1])
    x = np.cos(lat_rad) * np.cos(lon_rad)
    y = np.cos(lat_rad) * np.sin(lon_rad)
    z = np.sin(lat_rad)
    return np.column_stack([x, y, z])

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


