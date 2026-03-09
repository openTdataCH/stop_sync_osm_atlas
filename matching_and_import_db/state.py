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
from matching_and_import_db.models import AtlasNode, AtlasEntity
from matching_and_import_db.models import OsmNode, OsmEntity

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

        # Pre-grouping maps (derived directly from duplicate_sloid_map)
        # sibling sloid → representative sloid
        self._dup_group_representative: dict[str, str] = {}
        # representative sloid → [sibling sloids]
        self._dup_group_siblings: dict[str, list[str]] = {}

        # Build grouping immediately — no distance heuristic needed.
        # Same (number, designation) = same group unconditionally.
        self._build_duplicate_groups()
        
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

    def _build_duplicate_groups(self) -> None:
        """Pre-group ATLAS duplicates before matching starts.

        Every entry sharing the same (number, designation) forms a group
        unconditionally — no distance heuristic. The first sorted SLOID
        is the representative; the rest are siblings.
        """
        seen_groups: set[tuple] = set()
        for sloid, group in self.duplicate_sloid_map.items():
            key = tuple(group)
            if key in seen_groups:
                continue
            seen_groups.add(key)

            representative_sloid = group[0]  # already sorted
            siblings = group[1:]
            if siblings:
                self._dup_group_siblings[representative_sloid] = siblings
                for sib_sloid in siblings:
                    self._dup_group_representative[sib_sloid] = representative_sloid

        grouped_count = sum(len(s) for s in self._dup_group_siblings.values())
        logger.info(
            f"ATLAS duplicate grouping: {len(self._dup_group_siblings)} groups, "
            f"{grouped_count} siblings hidden from predicates"
        )

    def get_unmatched_records(self) -> list[AtlasEntity]:
        """Returns unmatched ATLAS entries as entities (groups and singletons).

        Excludes non-representative members of pre-grouped duplicate sets.
        Representatives are returned as AtlasGroupEntity wrapping their siblings.
        """
        unmatched_df = self._df[~self._df['sloid'].isin(self.matched_ids)]
        entities: list[AtlasEntity] = []
        for _, row in unmatched_df.iterrows():
            sloid = str(row['sloid'])
            if sloid in self._dup_group_representative:
                continue  # skip siblings
            node = self._to_atlas_node(row)
            siblings = self._dup_group_siblings.get(sloid)
            if siblings:
                sib_nodes = [n for s in siblings
                             if (n := self.get_by_sloid(s)) is not None
                             and s not in self.matched_ids]
                if sib_nodes:
                    entities.append(AtlasEntity(node, sib_nodes, 'atlas_duplicate'))
                else:
                    entities.append(AtlasEntity(node))
            else:
                entities.append(AtlasEntity(node))
        return entities

    def get_unmatched_nodes(self) -> list[AtlasNode]:
        """Returns unmatched representative AtlasNodes (for PipelineResult)."""
        return [e.representative for e in self.get_unmatched_records()]

    def get_duplicate_siblings(self, sloid: str) -> list[str]:
        """Returns sibling SLOIDs for a representative (empty list if not a representative)."""
        return self._dup_group_siblings.get(sloid, [])

    def get_by_sloid(self, sloid: str) -> Optional[AtlasNode]:
        """Returns a single AtlasNode by SLOID, or None if not found."""
        match = self._df[self._df['sloid'] == sloid]
        if match.empty:
            return None
        return self._to_atlas_node(match.iloc[0])

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
        # representative node_id → (group_type, [sibling OsmNode domain objects])
        self._group_siblings: dict[str, tuple[str, list[OsmNode]]] = {}

        # Spatial indices
        self._cached_tree = None
        self._cached_pts = []
        self._cached_nodes_list = []
        self._cached_include_stations = None

    def build_groups(self, atlas_uic_counts: dict[str, int],
                     atlas_designation_to_uic: dict[str, str] = None,
                     atlas_uic_nearest_osm_distances: dict[str, list[float]] = None) -> None:
        """Pre-group platform ↔ stop_position pairs before any predicate runs.

        Path 1 (osm_group_uic): UIC-scoped reciprocal nearest-neighbour pairing
        within 12m, with ratio test and count-match condition.

        Path 2 (osm_group_name): Name-scoped pairing for nodes sharing a ``name``
        tag where uic_ref values do not diverge (at least one lacks uic_ref).
        Same ratio test and count-match condition (anchored via UIC or uic_name).
        """
        MAX_GROUP_DISTANCE = 12.0  # meters
        RATIO_TEST_FACTOR = 1.5

        atlas_designation_to_uic = atlas_designation_to_uic or {}
        atlas_uic_nearest_osm_distances = atlas_uic_nearest_osm_distances or {}

        # ------------------------------------------------------------------
        # Path 1: UIC-based grouping
        # ------------------------------------------------------------------
        uic_groups = 0
        groups_by_uic: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

        for uic, entries in self._uic_ref_dict.items():
            if len(entries) < 2:
                continue

            platforms = [e for e in entries if e['tags'].get('public_transport') == 'platform']
            stop_positions = [e for e in entries if e['tags'].get('public_transport') == 'stop_position']

            if not platforms or not stop_positions:
                continue

            pairs = self._find_reciprocal_pairs(
                platforms, stop_positions, MAX_GROUP_DISTANCE, RATIO_TEST_FACTOR)
            if pairs:
                groups_by_uic[uic].extend(pairs)

        # Count-match condition and representative selection for UIC path
        for uic, pairs in groups_by_uic.items():
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
                self._register_group(plat, sp, 'osm_group_uic')
                uic_groups += 1

        # ------------------------------------------------------------------
        # Path 2: Name-based grouping
        # ------------------------------------------------------------------
        name_groups = 0
        already_grouped = set(self._group_representative.keys())
        for rep_id, (_, siblings) in self._group_siblings.items():
            already_grouped.add(rep_id)
            for sib in siblings:
                already_grouped.add(sib.node_id)

        groups_by_name_uic: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

        for name, entries in self._name_index.items():
            # Skip nodes already grouped by path 1
            entries = [e for e in entries if e['node_id'] not in already_grouped]
            if len(entries) < 2:
                continue

            platforms = [e for e in entries if e['tags'].get('public_transport') == 'platform']
            stop_positions = [e for e in entries if e['tags'].get('public_transport') == 'stop_position']

            if not platforms or not stop_positions:
                continue

            pairs = self._find_reciprocal_pairs(
                platforms, stop_positions, MAX_GROUP_DISTANCE, RATIO_TEST_FACTOR,
                require_uic_non_divergence=True)

            for plat, sp in pairs:
                # Anchor to a UIC for count-match: use uic_ref from whichever
                # node has it, or resolve via uic_name → ATLAS designationOfficial
                anchor_uic = self._resolve_anchor_uic(plat, sp, atlas_designation_to_uic)
                if anchor_uic:
                    groups_by_name_uic.setdefault(anchor_uic, []).append((plat, sp))

        # Count-match condition for name-based path (anchored by UIC)
        for uic, pairs in groups_by_name_uic.items():
            # Count distinct logical entities for this UIC after all grouping:
            # = ungrouped nodes + path1 groups (each counts as 1) + name-based pairs (each counts as 1)
            all_uic_entries = self._uic_ref_dict.get(uic, [])
            uic_node_ids = {e['node_id'] for e in all_uic_entries}
            name_pair_ids = set()
            for plat, sp in pairs:
                name_pair_ids.add(plat['node_id'])
                name_pair_ids.add(sp['node_id'])

            all_involved_ids = uic_node_ids | name_pair_ids
            grouped_by_path1 = all_involved_ids & already_grouped
            path1_group_count = sum(1 for nid in uic_node_ids if nid in self._group_siblings)
            ungrouped = all_involved_ids - grouped_by_path1 - name_pair_ids
            effective_count = len(ungrouped) + path1_group_count + len(pairs)

            atlas_count = atlas_uic_counts.get(uic, 0)
            if atlas_count != effective_count:
                continue

            for plat, sp in pairs:
                if plat['node_id'] in already_grouped or sp['node_id'] in already_grouped:
                    continue
                self._register_group(plat, sp, 'osm_group_name')
                already_grouped.add(plat['node_id'])
                already_grouped.add(sp['node_id'])
                name_groups += 1

        # ------------------------------------------------------------------
        # Path 3: Tram-based grouping (railway=tram_stop ↔ stop_position)
        # ------------------------------------------------------------------
        tram_groups = 0
        # Refresh already_grouped after path 2
        already_grouped = set(self._group_representative.keys())
        for rep_id, (_, siblings) in self._group_siblings.items():
            already_grouped.add(rep_id)
            for sib in siblings:
                already_grouped.add(sib.node_id)

        groups_by_tram_uic: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

        for uic, entries in self._uic_ref_dict.items():
            # Skip nodes already grouped by path 1/2
            entries = [e for e in entries if e['node_id'] not in already_grouped]
            if len(entries) < 2:
                continue

            tram_stops = [e for e in entries
                          if e['tags'].get('railway') == 'tram_stop']
            stop_positions = [e for e in entries
                              if e['tags'].get('public_transport') == 'stop_position']

            if not tram_stops or not stop_positions:
                continue

            pairs = self._find_reciprocal_pairs(
                tram_stops, stop_positions, MAX_GROUP_DISTANCE, RATIO_TEST_FACTOR)
            if pairs:
                groups_by_tram_uic[uic].extend(pairs)

        # Count-match condition for tram path
        for uic, pairs in groups_by_tram_uic.items():
            all_uic_entries = self._uic_ref_dict.get(uic, [])
            # Exclude nodes already grouped from count
            remaining = [e for e in all_uic_entries if e['node_id'] not in already_grouped]
            grouped_ids = set()
            for tram, sp in pairs:
                grouped_ids.add(tram['node_id'])
                grouped_ids.add(sp['node_id'])
            ungrouped_count = sum(1 for e in remaining if e['node_id'] not in grouped_ids)
            # Count existing path1/path2 groups for this UIC as 1 each
            path12_group_count = sum(1 for nid in {e['node_id'] for e in all_uic_entries}
                                     if nid in self._group_siblings)
            effective_count = ungrouped_count + path12_group_count + len(pairs)

            atlas_count = atlas_uic_counts.get(uic, 0)
            if atlas_count != effective_count and not self._allow_single_atlas_outlier_for_tram(
                uic,
                atlas_count,
                effective_count,
                atlas_uic_nearest_osm_distances,
            ):
                continue

            for tram, sp in pairs:
                if tram['node_id'] in already_grouped or sp['node_id'] in already_grouped:
                    continue
                self._register_group(tram, sp, 'osm_group_tram')
                already_grouped.add(tram['node_id'])
                already_grouped.add(sp['node_id'])
                tram_groups += 1

        logger.info(
            f"OSM grouping: {uic_groups} UIC-based + {name_groups} name-based + "
            f"{tram_groups} tram-based = {uic_groups + name_groups + tram_groups} pairs formed"
        )

    @staticmethod
    def _allow_single_atlas_outlier_for_tram(
        uic: str,
        atlas_count: int,
        effective_count: int,
        atlas_uic_nearest_osm_distances: dict[str, list[float]],
    ) -> bool:
        """Allow one extra unmatched ATLAS stop when it is a clear distance outlier.

        This only relaxes the tram count guard by one logical ATLAS stop.
        The farthest ATLAS row must be both absolutely far from any same-UIC OSM
        node and clearly separated from the second-farthest row.
        """
        if atlas_count != effective_count + 1:
            return False

        distances = sorted(
            (float(distance) for distance in atlas_uic_nearest_osm_distances.get(uic, []) if distance is not None),
            reverse=True,
        )
        if len(distances) < atlas_count or len(distances) < 2:
            return False

        farthest = distances[0]
        second_farthest = distances[1]
        outlier_min_distance = 30.0
        outlier_ratio = 1.8

        return farthest >= outlier_min_distance and farthest / max(second_farthest, 0.001) >= outlier_ratio

    def _register_group(self, plat: dict, sp: dict, group_type: str) -> None:
        """Register a platform ↔ stop_position group (platform = representative)."""
        rep_id = plat['node_id']
        sib_id = sp['node_id']
        self._group_representative[sib_id] = rep_id
        self._group_siblings[rep_id] = (group_type, [self._to_osm_node(sp)])

    @staticmethod
    def _find_reciprocal_pairs(
        platforms: list[dict], stop_positions: list[dict],
        max_distance: float, ratio_factor: float,
        require_uic_non_divergence: bool = False,
    ) -> list[tuple[dict, dict]]:
        """Find reciprocal nearest-neighbour platform ↔ stop_position pairs.

        Returns list of (platform_entry, stop_position_entry) tuples.
        Applies a ratio test: skips pairing when d2/d1 < ratio_factor.
        """
        # For each stop_position find nearest + second-nearest platform
        sp_to_nearest: dict[str, tuple[dict, float]] = {}
        sp_to_second_d: dict[str, float] = {}
        for sp in stop_positions:
            best_plat, best_d = None, max_distance
            second_d = float('inf')
            for plat in platforms:
                if plat['node_id'] == sp['node_id']:
                    continue
                if require_uic_non_divergence:
                    sp_uic = sp['tags'].get('uic_ref')
                    plat_uic = plat['tags'].get('uic_ref')
                    if sp_uic and plat_uic and sp_uic != plat_uic:
                        continue
                d = haversine_distance(sp['lat'], sp['lon'], plat['lat'], plat['lon'])
                if d is None:
                    continue
                if d < best_d:
                    second_d = best_d
                    best_d = d
                    best_plat = plat
                elif d < second_d:
                    second_d = d
            if best_plat is not None:
                sp_to_nearest[sp['node_id']] = (best_plat, best_d)
                sp_to_second_d[sp['node_id']] = second_d

        # For each platform find nearest + second-nearest stop_position
        plat_to_nearest: dict[str, tuple[dict, float]] = {}
        plat_to_second_d: dict[str, float] = {}
        for plat in platforms:
            best_sp, best_d = None, max_distance
            second_d = float('inf')
            for sp in stop_positions:
                if sp['node_id'] == plat['node_id']:
                    continue
                if require_uic_non_divergence:
                    sp_uic = sp['tags'].get('uic_ref')
                    plat_uic = plat['tags'].get('uic_ref')
                    if sp_uic and plat_uic and sp_uic != plat_uic:
                        continue
                d = haversine_distance(plat['lat'], plat['lon'], sp['lat'], sp['lon'])
                if d is None:
                    continue
                if d < best_d:
                    second_d = best_d
                    best_d = d
                    best_sp = sp
                elif d < second_d:
                    second_d = d
            if best_sp is not None:
                plat_to_nearest[plat['node_id']] = (best_sp, best_d)
                plat_to_second_d[plat['node_id']] = second_d

        # Reciprocal check + ratio test
        pairs: list[tuple[dict, dict]] = []
        used_plats: set[str] = set()
        used_sps: set[str] = set()
        for sp in stop_positions:
            if sp['node_id'] in used_sps:
                continue
            match = sp_to_nearest.get(sp['node_id'])
            if match is None:
                continue
            plat, d1_sp = match
            if plat['node_id'] in used_plats:
                continue

            # Reciprocal check
            reverse = plat_to_nearest.get(plat['node_id'])
            if reverse is None:
                continue
            rev_sp, _ = reverse
            if rev_sp['node_id'] != sp['node_id']:
                continue

            # Ratio test on stop_position side
            d2_sp = sp_to_second_d.get(sp['node_id'], float('inf'))
            if d1_sp > 0 and d2_sp / d1_sp < ratio_factor:
                continue

            # Ratio test on platform side
            d1_plat = plat_to_nearest[plat['node_id']][1]
            d2_plat = plat_to_second_d.get(plat['node_id'], float('inf'))
            if d1_plat > 0 and d2_plat / d1_plat < ratio_factor:
                continue

            pairs.append((plat, sp))
            used_plats.add(plat['node_id'])
            used_sps.add(sp['node_id'])

        return pairs

    @staticmethod
    def _resolve_anchor_uic(plat: dict, sp: dict,
                            atlas_designation_to_uic: dict[str, str]) -> Optional[str]:
        """Resolve the UIC anchor for a name-based pair.

        Returns the UIC string if one node has uic_ref, or if a node's uic_name
        maps to an ATLAS designationOfficial. Returns None if no anchor found.
        """
        plat_uic = plat['tags'].get('uic_ref')
        sp_uic = sp['tags'].get('uic_ref')
        if plat_uic:
            return plat_uic
        if sp_uic:
            return sp_uic

        # Try uic_name → ATLAS designationOfficial lookup
        for entry in (plat, sp):
            uic_name = entry['tags'].get('uic_name')
            if uic_name and uic_name in atlas_designation_to_uic:
                return atlas_designation_to_uic[uic_name]
        return None

    def get_siblings(self, node_id: str) -> list[OsmNode]:
        """Returns sibling OsmNodes for a representative node (empty if none)."""
        entry = self._group_siblings.get(node_id)
        if entry is None:
            return []
        return entry[1]

    def get_siblings_with_type(self, node_id: str) -> tuple[str, list[OsmNode]] | None:
        """Returns (group_type, siblings) or None if not a representative."""
        return self._group_siblings.get(node_id)

    def get_node_routes(self, node_id: str) -> list[dict]:
        """Returns route entries for a node: [{'gtfs_route_id', 'direction_id', 'route_name'}, ...]."""
        return self._node_routes.get(node_id, [])

    def _is_sibling(self, node_id: str) -> bool:
        """Returns True if this node is a sibling (hidden from predicates)."""
        return node_id in self._group_representative

    def mark_used(self, node_id: str):
        self.used_ids.add(node_id)

    def is_used(self, node_id: str) -> bool:
        return node_id in self.used_ids

    def get_all_nodes(self) -> list[OsmNode]:
        """Returns ALL OSM nodes (matched, unmatched, siblings, stations — everything)."""
        return [self._to_osm_node(n) for n in self._all_nodes.values()]

    def get_unmatched_nodes(self) -> list[OsmNode]:
        return [
            self._to_osm_node(n) for n in self._all_nodes.values()
            if n['node_id'] not in self.used_ids
            and not self._is_sibling(n['node_id'])
        ]
    
    def _wrap_entity(self, node_dict: dict) -> OsmEntity:
        """Wrap a raw node dict as an OsmEntity, attaching siblings if it's a group representative."""
        node = self._to_osm_node(node_dict)
        entry = self._group_siblings.get(node_dict['node_id'])
        if entry:
            group_type, siblings = entry
            return OsmEntity(node, siblings, group_type)
        return OsmEntity(node)

    def get_by_uic(self, uic: str) -> list[OsmEntity]:
        """Gets unmatched non-station entities for a UIC reference (excludes siblings)."""
        return [
            self._wrap_entity(c) for c in self._uic_ref_dict.get(str(uic), [])
            if c['node_id'] not in self.used_ids
            and not self._is_sibling(c['node_id'])
            and not self._to_osm_node(c).is_station
        ]

    def get_by_name(self, name: str) -> list[OsmEntity]:
        """Gets unmatched non-station entities for a given name (excludes siblings)."""
        return [
            self._wrap_entity(c) for c in self._name_index.get(name, [])
            if c['node_id'] not in self.used_ids
            and not self._is_sibling(c['node_id'])
            and not self._to_osm_node(c).is_station
        ]
        
    def get_all_unmatched_grouped(self, key: str) -> dict[str, list[OsmEntity]]:
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

            result[val].append(self._wrap_entity(node_dict))

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

    def batch_query_radius(self, coords_list: list[tuple[float, float]], max_distance: float, include_stations: bool = False) -> list[list[tuple[OsmEntity, float]]]:
        """Query for matching nodes around a radius for multiple coordinates at once.

        Returns a list (one per coordinate pair) of lists of tuples (OsmEntity, actual_distance_in_meters).
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
                    matches.append((self._wrap_entity(node_dict), d))
            results.append(matches)

        return results
