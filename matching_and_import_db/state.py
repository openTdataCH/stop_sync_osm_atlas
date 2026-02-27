import logging
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

import pandas as pd

from matching_and_import_db.utils.common import is_osm_station, haversine_distance
from matching_and_import_db.utils.spatial_index import build_kdtree_from_nodes, batch_to_xyz, meters_to_unit_chord_radius
from matching_and_import_db.utils.org_standardization import standardize_operator

logger = logging.getLogger(__name__)

class AtlasState:
    """Manages the fully populated ATLAS dataset and provides unmatched records on demand."""
    
    @classmethod
    def from_dataframe(cls, atlas_df: pd.DataFrame) -> 'AtlasState':
        """
        Builds AtlasState directly from a DataFrame, computing duplicate sets automatically.
        """
        dup_mask = atlas_df.duplicated(subset=['number', 'designation'], keep=False)
        non_empty = atlas_df['designation'].notna() & (atlas_df['designation'].astype(str).str.strip() != '')
        dup_mask = dup_mask & non_empty

        duplicate_sloid_map: dict[str, list[str]] = {}
        for _, group_df in atlas_df[dup_mask].groupby(['number', 'designation'], sort=False):
            if len(group_df) <= 1:
                continue
            sloids = sorted(group_df['sloid'].astype(str).tolist())
            for s in sloids:
                duplicate_sloid_map[s] = sloids

        return cls(atlas_df, duplicate_sloid_map)

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


class OsmState:
    """Manages OSM indexing, queries (spatial and attribute), and matching exclusion capabilities."""
    
    @classmethod
    def from_xml_file(cls, xml_file: str) -> 'OsmState':
        """
        Parse OSM XML and initialize OsmState.

        * all_nodes:    {(lat, lon): node_entry}
        * uic_ref_dict: {uic_ref_str: [node_entry, …]}
        * name_index:   {name_str: [node_entry, …]}
        * name_dirs:    {node_id: set of "FirstName → LastName" direction strings}
        * uic_dirs:     {node_id: set of "FirstUIC → LastUIC" direction strings}
        """
        tree = ET.parse(xml_file)
        root = tree.getroot()

        all_nodes: dict[tuple, dict] = {}
        uic_ref_dict: dict[str, list] = defaultdict(list)
        name_index: dict[str, list] = defaultdict(list)

        # Also collect per-node name/UIC for direction extraction from relations
        node_id_to_name: dict[str, str] = {}
        node_id_to_uic: dict[str, str] = {}

        for node in root.iter("node"):
            node_id = node.get("id")
            try:
                lat = float(node.get("lat"))
                lon = float(node.get("lon"))
            except (ValueError, TypeError):
                continue

            local_ref = None
            tags: dict[str, str] = {}

            for tag in node.findall("tag"):
                k, v = tag.get("k"), tag.get("v")
                if k == "operator":
                    original = v
                    v, changed = standardize_operator(v)
                    if changed:
                        tags['original_operator'] = original
                tags[k] = v
                if k == "local_ref":
                    local_ref = v
                elif k == "ref" and not local_ref:
                    local_ref = v

            entry = {
                'node_id': node_id,
                'lat': lat,
                'lon': lon,
                'local_ref': local_ref,
                'tags': tags,
            }
            all_nodes[(lat, lon)] = entry

            if "uic_ref" in tags:
                uic_ref_dict[tags["uic_ref"]].append(entry)
                node_id_to_uic[node_id] = tags["uic_ref"]

            if "name" in tags:
                node_id_to_name[node_id] = tags["name"]

            for key in ('name', 'uic_name', 'gtfs:name'):
                if key in tags:
                    name_index[tags[key]].append(entry)

        # Extract per-node direction strings from route relations (single pass)
        name_dirs: dict[str, set] = defaultdict(set)
        uic_dirs: dict[str, set] = defaultdict(set)

        # Use sidecar CSV for directions instead of re-parsing relations from the XML
        dir_csv_path = "data/processed/osm_directions.csv"
        loaded_from_csv = False
        
        if os.path.exists(dir_csv_path):
            try:
                df = pd.read_csv(dir_csv_path, dtype=str)
                df = df.where(pd.notna(df), None)
                for r in df.to_dict(orient='records'):
                    nid = str(r.get('node_id'))
                    ds = str(r.get('direction_string'))
                    dtype = str(r.get('dir_type'))
                    if not ds or ds == 'None' or not nid or nid == 'None': continue
                    if dtype == 'name':
                        name_dirs[nid].add(ds)
                    elif dtype == 'uic':
                        uic_dirs[nid].add(ds)
                loaded_from_csv = True
            except Exception as e:
                logger.warning(f"Error reading {dir_csv_path}: {e}")
                
        if not loaded_from_csv:
            for relation in root.iter("relation"):
                is_route = any(
                    t.get('k') == 'type' and t.get('v') == 'route'
                    for t in relation.findall('./tag')
                )
                if not is_route:
                    continue
                members = [m.get('ref') for m in relation.findall("./member[@type='node']")]
                if len(members) < 2:
                    continue
                first, last = members[0], members[-1]
                fn = node_id_to_name.get(first)
                ln = node_id_to_name.get(last)
                if fn and ln:
                    ds = f"{fn} → {ln}"
                    for nid in members:
                        name_dirs[nid].add(ds)
                fu = node_id_to_uic.get(first)
                lu = node_id_to_uic.get(last)
                if fu and lu:
                    ds = f"{fu} → {lu}"
                    for nid in members:
                        uic_dirs[nid].add(ds)

        logger.info(
            f"Parsed OSM XML: {len(all_nodes)} nodes, "
            f"{len(uic_ref_dict)} uic_ref entries, "
            f"{len(name_dirs)} nodes with direction strings"
        )
        return cls(all_nodes, uic_ref_dict, name_index, dict(name_dirs), dict(uic_dirs))

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
        
    def mark_used(self, node_id: str):
        self.used_ids.add(node_id)
        
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
