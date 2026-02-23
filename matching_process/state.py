import logging
from typing import Optional
import pandas as pd

from matching_process.utils import is_osm_station, haversine_distance
from matching_process.spatial_index import build_kdtree_from_nodes, lat_lon_to_xyz_list, batch_to_xyz, meters_to_unit_chord_radius

logger = logging.getLogger(__name__)

class AtlasState:
    """Manages the fully populated ATLAS dataset and provides unmatched records on demand."""
    
    def __init__(self, atlas_df: pd.DataFrame, duplicate_sloid_map: dict):
        self._df = atlas_df
        self.duplicate_sloid_map = duplicate_sloid_map
        self.matched_ids: set[str] = set()
        
    def add_matched_sloid(self, sloid: str):
        self.matched_ids.add(sloid)
        
    def get_unmatched_records(self) -> list[dict]:
        """Provides raw dicts for unmatched ATLAS records cleanly without Pandas handling required by predicates."""
        unmatched_df = self._df[~self._df['sloid'].isin(self.matched_ids)]
        return unmatched_df.to_dict(orient="records")
        
    def get_all_rows_as_dict(self) -> dict[str, dict]:
        """Returns all records mapped by sloid for lookups."""
        return {str(row['sloid']): row.to_dict() for _, row in self._df.iterrows()}


class OsmIndex:
    """Manages OSM indexing, queries (spatial and attribute), and matching exclusion capabilities."""
    
    def __init__(self, xml_nodes: dict, uic_ref_dict: dict, name_index: dict,
                 name_dirs: dict = None, uic_dirs: dict = None):
        self._all_nodes = xml_nodes
        self._uic_ref_dict = uic_ref_dict
        self._name_index = name_index
        self.name_dirs: dict[str, set] = name_dirs or {}
        self.uic_dirs: dict[str, set] = uic_dirs or {}
        
        self.used_ids: set[str] = set()
        
        # Spatial indices
        self._cached_tree = None
        self._cached_pts = []
        self._cached_nodes_list = []
        self._cached_include_stations = None
        self._spatial_index_valid = False
        
    def mark_used(self, node_id: str):
        self.used_ids.add(node_id)
        self._spatial_index_valid = False  # Mark spatial index dirty
        
    def is_used(self, node_id: str) -> bool:
        return node_id in self.used_ids
        
    def get_unmatched_nodes(self) -> list[dict]:
        return [n for n in self._all_nodes.values() if n['node_id'] not in self.used_ids]
    
    def get_by_uic(self, uic: str) -> list[dict]:
        """Gets unmatched non-station nodes for a UIC reference."""
        return [
            c for c in self._uic_ref_dict.get(str(uic), [])
            if c['node_id'] not in self.used_ids and not is_osm_station(c)
        ]
        
    def get_by_name(self, name: str) -> list[dict]:
        """Gets unmatched non-station nodes for a given name."""
        return [
            c for c in self._name_index.get(name, [])
            if c['node_id'] not in self.used_ids and not is_osm_station(c)
        ]
        
    def get_all_unmatched_grouped(self, key: str, stop_position_only: bool = False) -> dict[str, list[dict]]:
        """Used heavily by group_proximity to build lookup indexes."""
        from collections import defaultdict
        
        result = defaultdict(list)
        for node in self.get_unmatched_nodes():
            if is_osm_station(node):
                continue
            
            tags = node.get('tags', {})
            val = tags.get(key)
            if not val:
                continue
                
            if stop_position_only and tags.get('public_transport') != 'stop_position':
                continue
                
            result[val].append(node)
            
        return dict(result)

    def _ensure_spatial_index(self, include_stations: bool = False):
        """Builds KDTree on demand."""
        # Only rebuild if the cached tree is missing or the station filter flipped.
        if (self._cached_tree is None or
            self._cached_include_stations != include_stations):
            
            # Build the tree with ALL nodes (except optionally stations).
            # We filter out `used_ids` AT QUERY TIME instead of rebuilding the tree.
            valid_nodes = {
                coord: n for coord, n in self._all_nodes.items()
                if include_stations or not is_osm_station(n)
            }
            self._cached_tree, self._cached_pts, self._cached_nodes_list = build_kdtree_from_nodes(valid_nodes)
            self._cached_include_stations = include_stations
            self._spatial_index_valid = True

    def query_radius(self, lat: float, lon: float, max_distance: float, include_stations: bool = False) -> list[tuple[dict, float]]:
        """Query for matching nodes around a radius.
        
        Returns a list of tuples (node, actual_distance_in_meters).
        Excludes used_osm_ids automatically.
        """
        self._ensure_spatial_index(include_stations)
        
        if self._cached_tree is None:
            return []
            
        matches = []
        kd_radius = meters_to_unit_chord_radius(max_distance)
        q = lat_lon_to_xyz_list(lat, lon)
        
        for idx in self._cached_tree.query_ball_point(q, r=kd_radius):
            (n_lat, n_lon), node = self._cached_nodes_list[idx]
            
            # Skip nodes that have already been used
            if node['node_id'] in self.used_ids:
                continue
                
            d = haversine_distance(lat, lon, n_lat, n_lon)
            if d is not None and d <= max_distance:
                matches.append((node, d))
                
        return matches

    def batch_query_radius(self, coords_list: list[tuple[float, float]], max_distance: float, include_stations: bool = False) -> list[list[tuple[dict, float]]]:
        """Query for matching nodes around a radius for multiple coordinates at once.
        
        Returns a list (one per coordinate pair) of lists of tuples (node, actual_distance_in_meters).
        Excludes used_osm_ids automatically.
        """
        self._ensure_spatial_index(include_stations)
        
        if self._cached_tree is None or not coords_list:
            return [[] for _ in coords_list]
            
        kd_radius = meters_to_unit_chord_radius(max_distance)
        points = batch_to_xyz(coords_list)
        
        # Query all points at once using KDTree natively
        indices_list = self._cached_tree.query_ball_point(points, r=kd_radius, workers=-1)
        
        results = []
        for i, (lat, lon) in enumerate(coords_list):
            matches = []
            for idx in indices_list[i]:
                (n_lat, n_lon), node = self._cached_nodes_list[idx]
                if node['node_id'] in self.used_ids:
                    continue
                d = haversine_distance(lat, lon, n_lat, n_lon)
                if d is not None and d <= max_distance:
                    matches.append((node, d))
            results.append(matches)
            
        return results
