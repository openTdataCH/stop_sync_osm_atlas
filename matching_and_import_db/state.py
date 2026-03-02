import logging
import os
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Optional

import pandas as pd

from matching_and_import_db.utils.common import haversine_distance
from matching_and_import_db.utils.spatial_index import build_kdtree_from_nodes, batch_to_xyz, meters_to_unit_chord_radius
from matching_and_import_db.utils.org_standardization import standardize_operator
from matching_and_import_db.models import AtlasNode
from matching_and_import_db.models import OsmNode

logger = logging.getLogger(__name__)

class AtlasState:
    """Manages the fully populated ATLAS dataset and provides unmatched records on demand."""
    
    @classmethod
    def from_dataframe(cls, atlas_df: pd.DataFrame,
                       routes_csv_path: str = 'data/processed/atlas_routes_unified.csv') -> 'AtlasState':
        """
        Builds AtlasState directly from a DataFrame, computing duplicate sets automatically.
        Also loads the unified routes CSV if available.
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

        routes_by_sloid = cls._load_routes(routes_csv_path)
        return cls(atlas_df, duplicate_sloid_map, routes_by_sloid)

    @staticmethod
    def _load_routes(path: str) -> dict:
        """Load atlas_routes_unified.csv into a per-sloid dict keyed by source."""
        def _norm_dir(val):
            try:
                if pd.isna(val):
                    return None
                return str(int(float(val)))
            except Exception:
                return None

        by_sloid: dict[str, dict[str, list]] = defaultdict(lambda: {'gtfs': [], 'hrdf': []})
        if not os.path.exists(path):
            logger.warning(f"Routes CSV not found at {path!r}; route matching will be skipped.")
            return {}
        try:
            df = pd.read_csv(path, dtype=str, low_memory=False)
        except Exception as exc:
            logger.warning(f"Error loading routes CSV {path!r}: {exc}")
            return {}
        df = df.where(pd.notna(df), None)
        for row in df.to_dict(orient='records'):
            sloid = str(row['sloid']) if row.get('sloid') is not None else None
            if not sloid:
                continue
            src = str(row.get('source', ''))
            entry = {
                'route_id': row.get('route_id'),
                'route_id_normalized': row.get('route_id_normalized'),
                'line_name': row.get('line_name'),
                'direction_id': _norm_dir(row.get('direction_id')),
                'direction_name': row.get('direction_name'),
                'direction_uic': row.get('direction_uic'),
            }
            if src == 'gtfs':
                by_sloid[sloid]['gtfs'].append(entry)
            elif src == 'hrdf':
                by_sloid[sloid]['hrdf'].append(entry)
        return dict(by_sloid)

    def __init__(self, atlas_df: pd.DataFrame, duplicate_sloid_map: dict,
                 routes_by_sloid: dict = None):
        self._df = atlas_df
        self.duplicate_sloid_map = duplicate_sloid_map
        self._routes_by_sloid: dict[str, dict[str, list]] = routes_by_sloid or {}
        self.matched_ids: set[str] = set()
        
    def add_matched_sloid(self, sloid: str):
        self.matched_ids.add(sloid)

    def get_routes(self, sloid: str) -> dict[str, list]:
        """Returns {'gtfs': [...], 'hrdf': [...]} route entries for the given sloid."""
        return self._routes_by_sloid.get(sloid, {'gtfs': [], 'hrdf': []})

    def _to_atlas_node(self, row: pd.Series) -> AtlasNode:
        """Safely convert a pandas row into our strong Domain Entity."""
        # Pandas tends to return NaNs. Let's make sure we have pure strings or Nones for text.
        def _str(val) -> str:
            if pd.isna(val): return ""
            return str(val).strip()

        # Same for float coordinates (we assume they exist at this level of processing, else they will error)
        try:
            lat = float(row['wgs84North'])
            lon = float(row['wgs84East'])
        except (ValueError, TypeError, KeyError):
            lat = 0.0
            lon = 0.0

        return AtlasNode(
            sloid=str(row['sloid']),
            lat=lat,
            lon=lon,
            uic_ref=_str(row.get('number')),
            designation=_str(row.get('designation')),
            designation_official=_str(row.get('designationOfficial')),
            business_org_abbr=_str(row.get('servicePointBusinessOrganisationAbbreviationEn'))
        )

    def get_unmatched_records(self) -> list[AtlasNode]:
        """Provides strongly typed DOMAIN ENTITIES for unmatched records cleanly."""
        unmatched_df = self._df[~self._df['sloid'].isin(self.matched_ids)]
        return [self._to_atlas_node(row) for _, row in unmatched_df.iterrows()]
        
    def get_all_rows_as_dict(self) -> dict[str, AtlasNode]:
        """Returns all records mapped by sloid natively as domain models."""
        return {str(row['sloid']): self._to_atlas_node(row) for _, row in self._df.iterrows()}


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

        # Extract per-node direction strings and route data from route relations (single pass)
        name_dirs: dict[str, set] = defaultdict(set)
        uic_dirs: dict[str, set] = defaultdict(set)
        node_routes: dict[str, list] = defaultdict(list)

        def _parse_direction_from_ref_trips(val: str):
            """H suffix → '0' (outbound), R suffix → '1' (inbound)."""
            if not val:
                return None
            for tid in val.split(','):
                tid = tid.strip()
                if tid.endswith('.H'):
                    return '0'
                if tid.endswith('.R'):
                    return '1'
            return None

        # Always parse relations from XML to build node_routes.
        # Direction strings are loaded from sidecar CSV if available (perf cache),
        # otherwise also derived from the same relation pass.
        dir_csv_path = "data/processed/osm_directions.csv"
        loaded_dirs_from_csv = False

        if os.path.exists(dir_csv_path):
            try:
                df = pd.read_csv(dir_csv_path, dtype=str)
                df = df.where(pd.notna(df), None)
                for r in df.to_dict(orient='records'):
                    nid = str(r.get('node_id'))
                    ds = str(r.get('direction_string'))
                    dtype = str(r.get('dir_type'))
                    if not ds or ds == 'None' or not nid or nid == 'None':
                        continue
                    if dtype == 'name':
                        name_dirs[nid].add(ds)
                    elif dtype == 'uic':
                        uic_dirs[nid].add(ds)
                loaded_dirs_from_csv = True
            except Exception as e:
                logger.warning(f"Error reading {dir_csv_path}: {e}")

        for relation in root.iter("relation"):
            rel_tags: dict[str, str] = {t.get('k'): t.get('v') for t in relation.findall('./tag')}
            if rel_tags.get('type') != 'route':
                continue

            members = [m.get('ref') for m in relation.findall("./member[@type='node']")]
            if not members:
                continue

            # --- route data (always extracted) ---
            gtfs_route_id = rel_tags.get('gtfs:route_id')
            route_name = rel_tags.get('name')
            direction_id = _parse_direction_from_ref_trips(rel_tags.get('ref_trips', ''))
            # If direction is unknown, create entries for both directions so the
            # predicate can still match on route_id alone (preserves old CSV behaviour).
            direction_ids = [direction_id] if direction_id is not None else ['0', '1']
            for did in direction_ids:
                route_entry = {
                    'gtfs_route_id': gtfs_route_id,
                    'direction_id': did,
                    'route_name': route_name,
                }
                for nid in members:
                    node_routes[nid].append(route_entry)

            # --- direction strings (only if not loaded from CSV) ---
            if not loaded_dirs_from_csv and len(members) >= 2:
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
            f"{len(name_dirs)} nodes with direction strings, "
            f"{len(node_routes)} nodes with route data"
        )
        return cls(all_nodes, uic_ref_dict, name_index, dict(name_dirs), dict(uic_dirs),
                   dict(node_routes))

    def _to_osm_node(self, entry: dict) -> 'OsmNode':
        """Internal helper to convert dictionary entries into our strict entity model."""
        def _str(v):
            return str(v).strip() if v is not None else None
            
        tags = entry.get('tags', {})
        return OsmNode(
            node_id=str(entry['node_id']),
            lat=float(entry['lat']),
            lon=float(entry['lon']),
            local_ref=_str(entry.get('local_ref')),
            name=_str(tags.get('name')),
            uic_name=_str(tags.get('uic_name')),
            uic_ref=_str(tags.get('uic_ref')),
            network=_str(tags.get('network', '')),
            operator=_str(tags.get('operator', '')),
            public_transport=_str(tags.get('public_transport')),
            railway=_str(tags.get('railway')),
            amenity=_str(tags.get('amenity')),
            aerialway=_str(tags.get('aerialway')),
            tags=tags
        )

    def __init__(self, xml_nodes: dict, uic_ref_dict: dict, name_index: dict,
                 name_dirs: dict = None, uic_dirs: dict = None,
                 node_routes: dict = None):
        self._all_nodes = xml_nodes
        self._uic_ref_dict = uic_ref_dict
        self._name_index = name_index
        self.name_dirs: dict[str, set] = name_dirs or {}
        self.uic_dirs: dict[str, set] = uic_dirs or {}
        self._node_routes: dict[str, list] = node_routes or {}

        self.used_ids: set[str] = set()

        # OSM node grouping (platform ↔ stop_position pairs)
        # sibling node_id → representative node_id
        self._group_representative: dict[str, str] = {}
        # representative node_id → list of sibling OsmNode domain objects
        self._group_siblings: dict[str, list[OsmNode]] = {}

        # Spatial indices
        self._cached_tree = None
        self._cached_pts = []
        self._cached_nodes_list = []
        self._cached_include_stations = None

    def build_groups(self, atlas_uic_counts: dict[str, int]) -> None:
        """Pre-group platform ↔ stop_position pairs within each UIC.

        Uses Option B: UIC-scoped reciprocal nearest-neighbour pairing within 12m,
        with a count-match condition (only keep groups for a UIC when
        atlas_count == number of proposed OSM groups for that UIC).
        """
        MAX_GROUP_DISTANCE = 12.0  # meters

        groups_by_uic: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

        for uic, entries in self._uic_ref_dict.items():
            if len(entries) < 2:
                continue

            platforms = [e for e in entries if e['tags'].get('public_transport') == 'platform']
            stop_positions = [e for e in entries if e['tags'].get('public_transport') == 'stop_position']

            if not platforms or not stop_positions:
                continue

            # For each stop_position find nearest platform within 12m
            sp_to_nearest_plat: dict[str, tuple[dict, float]] = {}
            for sp in stop_positions:
                best_plat, best_d = None, MAX_GROUP_DISTANCE
                for plat in platforms:
                    d = haversine_distance(sp['lat'], sp['lon'], plat['lat'], plat['lon'])
                    if d is not None and d < best_d:
                        best_d = d
                        best_plat = plat
                if best_plat is not None:
                    sp_to_nearest_plat[sp['node_id']] = (best_plat, best_d)

            # For each platform find nearest stop_position within 12m
            plat_to_nearest_sp: dict[str, tuple[dict, float]] = {}
            for plat in platforms:
                best_sp, best_d = None, MAX_GROUP_DISTANCE
                for sp in stop_positions:
                    d = haversine_distance(plat['lat'], plat['lon'], sp['lat'], sp['lon'])
                    if d is not None and d < best_d:
                        best_d = d
                        best_sp = sp
                if best_sp is not None:
                    plat_to_nearest_sp[plat['node_id']] = (best_sp, best_d)

            # Reciprocal check: form pair only if both point at each other
            used_plats: set[str] = set()
            used_sps: set[str] = set()
            for sp in stop_positions:
                if sp['node_id'] in used_sps:
                    continue
                match = sp_to_nearest_plat.get(sp['node_id'])
                if match is None:
                    continue
                plat, _ = match
                if plat['node_id'] in used_plats:
                    continue
                reverse = plat_to_nearest_sp.get(plat['node_id'])
                if reverse is None:
                    continue
                rev_sp, _ = reverse
                if rev_sp['node_id'] == sp['node_id']:
                    groups_by_uic[uic].append((plat, sp))
                    used_plats.add(plat['node_id'])
                    used_sps.add(sp['node_id'])

        # Count-match condition and representative selection
        total_groups = 0
        for uic, pairs in groups_by_uic.items():
            # Total OSM nodes for this UIC that would result after grouping:
            # ungrouped nodes + groups (each pair counts as 1)
            all_uic_entries = self._uic_ref_dict[uic]
            grouped_ids = set()
            for plat, sp in pairs:
                grouped_ids.add(plat['node_id'])
                grouped_ids.add(sp['node_id'])
            ungrouped_count = sum(1 for e in all_uic_entries if e['node_id'] not in grouped_ids)
            effective_count = ungrouped_count + len(pairs)

            atlas_count = atlas_uic_counts.get(uic, 0)
            if atlas_count != effective_count:
                continue

            for plat, sp in pairs:
                # Representative selection: prefer node with uic_ref, then prefer platform
                plat_has_uic = 'uic_ref' in plat['tags']
                sp_has_uic = 'uic_ref' in sp['tags']
                if sp_has_uic and not plat_has_uic:
                    representative, sibling = sp, plat
                else:
                    representative, sibling = plat, sp

                rep_id = representative['node_id']
                sib_id = sibling['node_id']
                self._group_representative[sib_id] = rep_id
                self._group_siblings[rep_id] = [self._to_osm_node(sibling)]
                total_groups += 1

        logger.info(f"OSM grouping: {total_groups} platform↔stop_position pairs formed")

    def get_siblings(self, node_id: str) -> list[OsmNode]:
        """Returns sibling OsmNodes for a representative node (empty if none)."""
        return self._group_siblings.get(node_id, [])

    def get_node_routes(self, node_id: str) -> list[dict]:
        """Returns route entries for a node: [{'gtfs_route_id', 'direction_id', 'route_name'}, ...]."""
        return self._node_routes.get(node_id, [])

    def _is_sibling(self, node_id: str) -> bool:
        """Returns True if this node is a sibling (hidden from predicates)."""
        return node_id in self._group_representative

    def mark_used(self, node_id: str):
        self.used_ids.add(node_id)
        # Cascade: also lock siblings
        for sibling in self._group_siblings.get(node_id, []):
            self.used_ids.add(sibling.node_id)

    def is_used(self, node_id: str) -> bool:
        return node_id in self.used_ids

    def get_all_nodes(self) -> list[OsmNode]:
        """Returns ALL OSM nodes (matched, unmatched, siblings, stations — everything)."""
        return [self._to_osm_node(n) for n in self._all_nodes.values()]

    def get_unmatched_nodes(self) -> list[OsmNode]:
        return [
            self._to_osm_node(n) for n in self._all_nodes.values()
            if n['node_id'] not in self.used_ids and not self._is_sibling(n['node_id'])
        ]
    
    def get_by_uic(self, uic: str) -> list[OsmNode]:
        """Gets unmatched non-station nodes for a UIC reference (excludes siblings)."""
        return [
            self._to_osm_node(c) for c in self._uic_ref_dict.get(str(uic), [])
            if c['node_id'] not in self.used_ids
            and not self._is_sibling(c['node_id'])
            and not self._to_osm_node(c).is_station
        ]

    def get_by_name(self, name: str) -> list[OsmNode]:
        """Gets unmatched non-station nodes for a given name (excludes siblings)."""
        return [
            self._to_osm_node(c) for c in self._name_index.get(name, [])
            if c['node_id'] not in self.used_ids
            and not self._is_sibling(c['node_id'])
            and not self._to_osm_node(c).is_station
        ]
        
    def get_all_unmatched_grouped(self, key: str, stop_position_only: bool = False) -> dict[str, list[OsmNode]]:
        """Used heavily by group_proximity to build lookup indexes (excludes siblings)."""
        from collections import defaultdict

        result = defaultdict(list)
        for node_dict in self._all_nodes.values():
            if node_dict['node_id'] in self.used_ids:
                continue
            if self._is_sibling(node_dict['node_id']):
                continue
            if self._to_osm_node(node_dict).is_station:
                continue

            tags = node_dict.get('tags', {})
            val = tags.get(key)
            if not val:
                continue

            if stop_position_only and tags.get('public_transport') != 'stop_position':
                continue

            result[val].append(self._to_osm_node(node_dict))

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
                if include_stations or not self._to_osm_node(n).is_station
            }
            self._cached_tree, self._cached_pts, self._cached_nodes_list = build_kdtree_from_nodes(valid_nodes)
            self._cached_include_stations = include_stations

    def batch_query_radius(self, coords_list: list[tuple[float, float]], max_distance: float, include_stations: bool = False) -> list[list[tuple[OsmNode, float]]]:
        """Query for matching nodes around a radius for multiple coordinates at once.
        
        Returns a list (one per coordinate pair) of lists of tuples (OsmNode, actual_distance_in_meters).
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
                (n_lat, n_lon), node_dict = self._cached_nodes_list[idx]
                if node_dict['node_id'] in self.used_ids:
                    continue
                if self._is_sibling(node_dict['node_id']):
                    continue
                d = haversine_distance(lat, lon, n_lat, n_lon)
                if d is not None and d <= max_distance:
                    matches.append((self._to_osm_node(node_dict), d))
            results.append(matches)
            
        return results
