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

GROUP_MAX_DISTANCE_M = 12.0
GROUP_PERFECT_COUNT_MAX_DISTANCE_M = 15.0
ATLAS_NEARBY_OSM_MAX_DISTANCE_M = 30.0
GROUP_RATIO_TEST_FACTOR_STRICT = 1.5
GROUP_RATIO_TEST_FACTOR_RELAXED = 2.0

OSM_PAIR_UIC = 'osm_pair_uic'
OSM_PAIR_NAME = 'osm_pair_name'
OSM_PAIR_TRAM = 'osm_pair_tram'

OSM_PAIR_UIC_EQUAL_15M = 'osm_pair_uic_equal_15m'
OSM_PAIR_NAME_EQUAL_15M = 'osm_pair_name_equal_15m'
OSM_PAIR_TRAM_EQUAL_15M = 'osm_pair_tram_equal_15m'

class AtlasState:
    """Manages the fully populated ATLAS dataset and provides unmatched records on demand."""
    
    @classmethod
    def from_dataframe(cls, atlas_df: pd.DataFrame,
                       routes_csv_path: str = 'data/processed/atlas_routes_gtfs.csv') -> 'AtlasState':
        """
        Builds AtlasState directly from a DataFrame, computing duplicate sets automatically.
        Also loads the GTFS routes CSV if available.
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
        """Load atlas_routes_gtfs.csv into a per-sloid GTFS route mapping."""
        def _norm_dir(val):
            try:
                if pd.isna(val):
                    return None
                return str(int(float(val)))
            except Exception:
                return None

        by_sloid: dict[str, dict[str, list]] = defaultdict(lambda: {'gtfs': []})
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
            entry = {
                'route_id': row.get('route_id'),
                'route_id_normalized': row.get('route_id_normalized'),
                'route_name_short': row.get('route_name_short'),
                'route_name_long': row.get('route_name_long'),
                'direction_id': _norm_dir(row.get('direction_id')),
                'direction_name': row.get('direction_name'),
            }
            by_sloid[sloid]['gtfs'].append(entry)
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
        """Returns {'gtfs': [...]} route entries for the given sloid."""
        return self._routes_by_sloid.get(sloid, {'gtfs': []})

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
        """Returns unmatched AtlasNodes, including siblings (for PipelineResult)."""
        nodes = []
        for e in self.get_unmatched_records():
            nodes.extend(e.get_members())
        return nodes

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

        # Collect element names/UICs for relation direction extraction
        element_id_to_name: dict[str, str] = {}
        element_id_to_uic: dict[str, str] = {}
        # Needed for selective way inclusion (issue #37)
        node_uic_refs: set[str] = set()
        node_coord_by_id: dict[str, tuple[float, float]] = {}

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

            node_coord_by_id[node_id] = (lat, lon)

            if "uic_ref" in tags:
                uic_ref_dict[tags["uic_ref"]].append(entry)
                element_id_to_uic[node_id] = tags["uic_ref"]
                node_uic_refs.add(tags["uic_ref"])

            if "name" in tags:
                element_id_to_name[node_id] = tags["name"]

            for key in ('name', 'uic_name', 'gtfs:name'):
                if key in tags:
                    name_index[tags[key]].append(entry)

        # Parse ways and keep only requested categories:
        # 1) aerialway=station + public_transport=station
        # 2) ways with uic_ref where no node has the same uic_ref
        selected_way_count = 0
        for way in root.iter("way"):
            way_id = way.get("id")
            if not way_id:
                continue

            tags: dict[str, str] = {}
            local_ref = None
            for tag in way.findall("tag"):
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

            is_aerialway_station = (
                tags.get("aerialway") == "station" and
                tags.get("public_transport") == "station"
            )
            way_uic_ref = tags.get("uic_ref")
            is_uic_without_node = bool(way_uic_ref) and way_uic_ref not in node_uic_refs
            if not (is_aerialway_station or is_uic_without_node):
                continue

            center = way.find("center")
            lat = lon = None
            if center is not None:
                try:
                    lat = float(center.get("lat"))
                    lon = float(center.get("lon"))
                except (ValueError, TypeError):
                    lat = lon = None

            member_node_ids = [n.get("ref") for n in way.findall("nd") if n.get("ref")]
            if lat is None or lon is None:
                coords = [node_coord_by_id[nid] for nid in member_node_ids if nid in node_coord_by_id]
                if not coords:
                    continue
                lat = sum(c[0] for c in coords) / len(coords)
                lon = sum(c[1] for c in coords) / len(coords)

            virtual_id = f"way_{way_id}"
            entry = {
                'node_id': virtual_id,
                'lat': lat,
                'lon': lon,
                'local_ref': local_ref,
                'tags': tags,
            }

            all_nodes[(lat, lon)] = entry
            selected_way_count += 1

            if way_uic_ref:
                uic_ref_dict[way_uic_ref].append(entry)
                element_id_to_uic[virtual_id] = way_uic_ref

            if "name" in tags:
                element_id_to_name[virtual_id] = tags["name"]

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

            members: list[str] = []
            for member in relation.findall("./member"):
                member_ref = member.get('ref')
                if not member_ref:
                    continue
                member_type = member.get('type')
                if member_type == 'node':
                    members.append(member_ref)
                elif member_type == 'way':
                    members.append(f"way_{member_ref}")
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
                    'relation_id': relation.get('id'),
                    'gtfs_route_id': gtfs_route_id,
                    'direction_id': did,
                    'route_name': route_name,
                }
                for nid in members:
                    node_routes[nid].append(route_entry)

            # --- direction strings (only if not loaded from CSV) ---
            if not loaded_dirs_from_csv and len(members) >= 2:
                first, last = members[0], members[-1]
                fn = element_id_to_name.get(first)
                ln = element_id_to_name.get(last)
                if fn and ln:
                    ds = f"{fn} → {ln}"
                    for nid in members:
                        name_dirs[nid].add(ds)
                fu = element_id_to_uic.get(first)
                lu = element_id_to_uic.get(last)
                if fu and lu:
                    ds = f"{fu} → {lu}"
                    for nid in members:
                        uic_dirs[nid].add(ds)

        logger.info(
            f"Parsed OSM XML: {len(all_nodes)} stop elements "
            f"({selected_way_count} selected ways), "
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

        # OSM node grouping (pairs and trios)
        # sibling node_id → representative node_id
        self._group_representative: dict[str, str] = {}
        # representative node_id → (group_type, [sibling OsmNode domain objects])
        self._group_siblings: dict[str, tuple[str, list[OsmNode]]] = {}
        # representative node_id → middle node_id for trios
        self._trio_middle_by_rep: dict[str, str] = {}
        # representative node_id → side node ids for trios (rep included)
        self._trio_sides_by_rep: dict[str, tuple[str, str]] = {}

        # Spatial indices
        self._cached_tree = None
        self._cached_pts = []
        self._cached_nodes_list = []
        self._cached_include_stations = None

    def build_groups(self, atlas_uic_counts: dict[str, int],
                     atlas_designation_to_uic: dict[str, str] = None,
                     atlas_uic_nearest_osm_distances: dict[str, list[float]] = None) -> None:
        """Pre-group OSM pairs and trios before any predicate runs.

        Trio path (osm_trio): UIC-scoped fixed-cardinality grouping with exactly
        three OSM nodes (one stop_position + two side nodes) and exactly two
        ATLAS rows for the same UIC.

        Path 1 (osm_pair_uic): UIC-scoped reciprocal nearest-neighbour pairing
        within 12m, with ratio test and count-match condition.

        Path 1a (osm_pair_*_equal_15m): Perfect-count branch for UIC/name/tram
        anchors where left_count == right_count == atlas_count. Uses reciprocal
        nearest-neighbour pairing within 15m and bypasses ratio checks.

        For perfect-count eligibility only, atlas_count is filtered to keep
        ATLAS rows whose nearest same-UIC OSM node is within 30m. The strict/
        relaxed fallback paths continue using the original unfiltered atlas_count.

        Path 2 (osm_pair_name): Name-scoped pairing for nodes sharing a ``name``
        tag where uic_ref values do not diverge (at least one lacks uic_ref).
        Same ratio test and count-match condition (anchored via UIC or uic_name).
        """
        atlas_designation_to_uic = atlas_designation_to_uic or {}
        atlas_uic_nearest_osm_distances = atlas_uic_nearest_osm_distances or {}

        perfect_atlas_uic_counts = self._build_perfect_atlas_uic_counts(
            atlas_uic_counts,
            atlas_uic_nearest_osm_distances,
        )

        # ------------------------------------------------------------------
        # Trio path: detect and reserve nodes before pair grouping
        # ------------------------------------------------------------------
        trio_groups = 0
        trio_node_ids: set[str] = set()
        for uic, entries in self._uic_ref_dict.items():
            entries = [e for e in entries if not str(e['node_id']).startswith('way_')]
            if len(entries) != 3:
                continue
            if atlas_uic_counts.get(uic, 0) != 2:
                continue

            stop_positions = [e for e in entries if e['tags'].get('public_transport') == 'stop_position']
            if len(stop_positions) != 1:
                continue

            side_nodes = [e for e in entries if e['node_id'] != stop_positions[0]['node_id']]
            if len(side_nodes) != 2:
                continue

            sorted_sides = sorted(side_nodes, key=lambda n: str(n['node_id']))
            representative = sorted_sides[0]
            side_partner = sorted_sides[1]
            middle = stop_positions[0]
            self._register_trio(representative, side_partner, middle)
            trio_node_ids.update({
                str(representative['node_id']),
                str(side_partner['node_id']),
                str(middle['node_id']),
            })
            trio_groups += 1

        # ------------------------------------------------------------------
        # Path 1: UIC-based pair grouping
        # ------------------------------------------------------------------
        uic_groups = 0
        uic_equal_groups = 0
        groups_by_uic: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)

        for uic, entries in self._uic_ref_dict.items():
            if len(entries) < 2:
                continue

            filtered_entries = [
                e for e in entries
                if not str(e['node_id']).startswith('way_') and str(e['node_id']) not in trio_node_ids
            ]
            platforms = [e for e in filtered_entries if e['tags'].get('public_transport') == 'platform']
            stop_positions = [e for e in filtered_entries if e['tags'].get('public_transport') == 'stop_position']

            if not platforms or not stop_positions:
                continue

            groups_by_uic[uic].extend(self._select_pairs_with_policy(
                entries=filtered_entries,
                left_nodes=platforms,
                right_nodes=stop_positions,
                atlas_count=atlas_uic_counts.get(uic, 0),
                perfect_atlas_count=perfect_atlas_uic_counts.get(uic, atlas_uic_counts.get(uic, 0)),
                perfect_group_type=OSM_PAIR_UIC_EQUAL_15M,
                fallback_group_type=OSM_PAIR_UIC,
            ))

        # Representative selection for UIC path
        uic_counts = self._register_selected_groups(groups_by_uic)
        uic_groups = uic_counts.get(OSM_PAIR_UIC, 0)
        uic_equal_groups = uic_counts.get(OSM_PAIR_UIC_EQUAL_15M, 0)

        # ------------------------------------------------------------------
        # Path 2: Name-based pair grouping
        # ------------------------------------------------------------------
        name_groups = 0
        name_equal_groups = 0
        already_grouped = self._get_grouped_node_ids()

        groups_by_name_uic: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)

        for name, entries in self._name_index.items():
            # Skip nodes already grouped by path 1
            entries = [
                e for e in entries
                if not str(e['node_id']).startswith('way_')
                and e['node_id'] not in already_grouped
                and str(e['node_id']) not in trio_node_ids
            ]
            if len(entries) < 2:
                continue

            platforms = [e for e in entries if e['tags'].get('public_transport') == 'platform']
            stop_positions = [e for e in entries if e['tags'].get('public_transport') == 'stop_position']

            if not platforms or not stop_positions:
                continue

            # Perfect-count branch per anchored UIC, bypassing ratio checks.
            by_anchor = self._build_name_anchor_buckets(entries, atlas_designation_to_uic)

            handled_anchors: set[str] = set()
            for anchor_uic, anchor_nodes in by_anchor.items():
                perfect_pairs = self._select_perfect_count_pairs(
                    left_nodes=anchor_nodes['platform'],
                    right_nodes=anchor_nodes['stop_position'],
                    atlas_count=perfect_atlas_uic_counts.get(anchor_uic, atlas_uic_counts.get(anchor_uic, 0)),
                    require_uic_non_divergence=True,
                )
                if perfect_pairs:
                    groups_by_name_uic[anchor_uic].extend(
                        (plat, sp, OSM_PAIR_NAME_EQUAL_15M)
                        for plat, sp in perfect_pairs
                    )
                    handled_anchors.add(anchor_uic)

            strict_pairs = self._find_reciprocal_pairs(
                platforms,
                stop_positions,
                GROUP_MAX_DISTANCE_M,
                GROUP_RATIO_TEST_FACTOR_STRICT,
                require_uic_non_divergence=True,
            )
            relaxed_pairs = self._find_reciprocal_pairs(
                platforms,
                stop_positions,
                GROUP_MAX_DISTANCE_M,
                GROUP_RATIO_TEST_FACTOR_RELAXED,
                require_uic_non_divergence=True,
            )

            strict_pairs_by_uic = self._bucket_pairs_by_anchor(strict_pairs, atlas_designation_to_uic)
            relaxed_pairs_by_uic = self._bucket_pairs_by_anchor(relaxed_pairs, atlas_designation_to_uic)

            for anchor_uic in set(strict_pairs_by_uic) | set(relaxed_pairs_by_uic):
                if anchor_uic in handled_anchors:
                    continue
                strict_anchor_pairs = strict_pairs_by_uic.get(anchor_uic, [])
                relaxed_anchor_pairs = relaxed_pairs_by_uic.get(anchor_uic, [])
                groups_by_name_uic[anchor_uic].extend(
                    self._select_name_fallback_pairs_for_anchor(
                        anchor_uic=anchor_uic,
                        strict_anchor_pairs=strict_anchor_pairs,
                        relaxed_anchor_pairs=relaxed_anchor_pairs,
                        already_grouped=already_grouped,
                        atlas_uic_counts=atlas_uic_counts,
                    )
                )

        # Representative selection for name-based path (anchored by UIC)
        name_counts = self._register_selected_groups(groups_by_name_uic, already_grouped)
        name_groups = name_counts.get(OSM_PAIR_NAME, 0)
        name_equal_groups = name_counts.get(OSM_PAIR_NAME_EQUAL_15M, 0)

        # ------------------------------------------------------------------
        # Path 3: Tram-based pair grouping (railway=tram_stop ↔ stop_position)
        # ------------------------------------------------------------------
        tram_groups = 0
        tram_equal_groups = 0
        # Refresh already_grouped after path 2
        already_grouped = self._get_grouped_node_ids()

        groups_by_tram_uic: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)

        for uic, entries in self._uic_ref_dict.items():
            # Skip nodes already grouped by path 1/2
            entries = [
                e for e in entries
                if not str(e['node_id']).startswith('way_')
                and e['node_id'] not in already_grouped
                and str(e['node_id']) not in trio_node_ids
            ]
            if len(entries) < 2:
                continue

            tram_stops = [e for e in entries
                          if e['tags'].get('railway') == 'tram_stop']
            stop_positions = [e for e in entries
                              if e['tags'].get('public_transport') == 'stop_position']

            if not tram_stops or not stop_positions:
                continue

            groups_by_tram_uic[uic].extend(self._select_pairs_with_policy(
                entries=entries,
                left_nodes=tram_stops,
                right_nodes=stop_positions,
                atlas_count=atlas_uic_counts.get(uic, 0),
                perfect_atlas_count=perfect_atlas_uic_counts.get(uic, atlas_uic_counts.get(uic, 0)),
                perfect_group_type=OSM_PAIR_TRAM_EQUAL_15M,
                fallback_group_type=OSM_PAIR_TRAM,
            ))

        # Representative selection for tram path
        tram_counts = self._register_selected_groups(groups_by_tram_uic, already_grouped)
        tram_groups = tram_counts.get(OSM_PAIR_TRAM, 0)
        tram_equal_groups = tram_counts.get(OSM_PAIR_TRAM_EQUAL_15M, 0)

        logger.info(
            f"OSM grouping: {trio_groups} trios + "
            f"{uic_groups} UIC-based pairs + {uic_equal_groups} UIC perfect-count pairs + "
            f"{name_groups} name-based pairs + {name_equal_groups} name perfect-count pairs + "
            f"{tram_groups} tram-based pairs + {tram_equal_groups} tram perfect-count pairs"
        )

    @staticmethod
    def _is_perfect_count_grouping(
        atlas_count: int,
        left_count: int,
        right_count: int,
    ) -> bool:
        """Return True when left/right/ATLAS counts are perfectly equal and non-zero."""
        return atlas_count > 0 and left_count == right_count == atlas_count

    def _select_perfect_count_pairs(
        self,
        left_nodes: list[dict],
        right_nodes: list[dict],
        atlas_count: int,
        require_uic_non_divergence: bool = False,
    ) -> list[tuple[dict, dict]]:
        """Select reciprocal conflict-free pairs for perfect-count anchors within 15m.

        This branch bypasses ratio checks and is only accepted when it yields
        a full 1:1 pairing for all left/right nodes.
        """
        if not self._is_perfect_count_grouping(
            atlas_count=atlas_count,
            left_count=len(left_nodes),
            right_count=len(right_nodes),
        ):
            return []

        pairs = self._find_reciprocal_pairs(
            left_nodes,
            right_nodes,
            GROUP_PERFECT_COUNT_MAX_DISTANCE_M,
            0.0,
            require_uic_non_divergence=require_uic_non_divergence,
        )
        if len(pairs) != atlas_count:
            return []
        return pairs

    def _select_pairs_with_policy(
        self,
        entries: list[dict],
        left_nodes: list[dict],
        right_nodes: list[dict],
        atlas_count: int,
        perfect_atlas_count: int,
        perfect_group_type: str,
        fallback_group_type: str,
        require_uic_non_divergence: bool = False,
    ) -> list[tuple[dict, dict, str]]:
        """Select pairs using perfect-count first, then strict/relaxed fallback."""
        perfect_pairs = self._select_perfect_count_pairs(
            left_nodes=left_nodes,
            right_nodes=right_nodes,
            atlas_count=perfect_atlas_count,
            require_uic_non_divergence=require_uic_non_divergence,
        )
        if perfect_pairs:
            return [(left, right, perfect_group_type) for left, right in perfect_pairs]

        fallback_pairs = self._select_group_pairs(
            entries=entries,
            left_nodes=left_nodes,
            right_nodes=right_nodes,
            atlas_count=atlas_count,
            require_uic_non_divergence=require_uic_non_divergence,
        )
        return [(left, right, fallback_group_type) for left, right in fallback_pairs]

    def _build_perfect_atlas_uic_counts(
        self,
        atlas_uic_counts: dict[str, int],
        atlas_uic_nearest_osm_distances: dict[str, list[float]],
    ) -> dict[str, int]:
        """Build per-UIC ATLAS counts used only by the perfect-count branch.

        If nearest-distance evidence is available for a UIC, only ATLAS rows
        with nearest same-UIC OSM distance <= ATLAS_NEARBY_OSM_MAX_DISTANCE_M are
        counted. If evidence is missing, fall back to the original atlas count.
        """
        perfect_counts: dict[str, int] = {}
        for uic, atlas_count in atlas_uic_counts.items():
            distances = atlas_uic_nearest_osm_distances.get(uic)
            if not distances:
                perfect_counts[uic] = atlas_count
                continue
            perfect_counts[uic] = sum(1 for d in distances if d <= ATLAS_NEARBY_OSM_MAX_DISTANCE_M)
        return perfect_counts

    def _get_grouped_node_ids(self) -> set[str]:
        """Return all OSM node IDs that are already part of a registered group."""
        grouped = set(self._group_representative.keys())
        for rep_id, (_, siblings) in self._group_siblings.items():
            grouped.add(rep_id)
            for sibling in siblings:
                grouped.add(sibling.node_id)
        return grouped

    def _build_name_anchor_buckets(
        self,
        entries: list[dict],
        atlas_designation_to_uic: dict[str, str],
    ) -> dict[str, dict[str, list[dict]]]:
        """Bucket name-index entries by anchor UIC and side (platform/stop_position)."""
        by_anchor: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {'platform': [], 'stop_position': []})
        for entry in entries:
            anchor_uic = self._resolve_entry_anchor_uic(entry, atlas_designation_to_uic)
            if not anchor_uic:
                continue
            public_transport = entry['tags'].get('public_transport')
            if public_transport == 'platform':
                by_anchor[anchor_uic]['platform'].append(entry)
            elif public_transport == 'stop_position':
                by_anchor[anchor_uic]['stop_position'].append(entry)
        return by_anchor

    def _register_selected_groups(
        self,
        groups_by_anchor: dict[str, list[tuple[dict, dict, str]]],
        already_grouped: set[str] | None = None,
    ) -> dict[str, int]:
        """Register selected pairs and return per-group_type counts.

        If already_grouped is provided, nodes already present in that set are
        skipped and newly registered node IDs are added to the same set.
        """
        counts: dict[str, int] = defaultdict(int)
        for pairs in groups_by_anchor.values():
            for left_node, right_node, group_type in pairs:
                left_id = left_node['node_id']
                right_id = right_node['node_id']
                if already_grouped is not None and (left_id in already_grouped or right_id in already_grouped):
                    continue
                self._register_group(left_node, right_node, group_type)
                counts[group_type] += 1
                if already_grouped is not None:
                    already_grouped.add(left_id)
                    already_grouped.add(right_id)
        return counts

    def _bucket_pairs_by_anchor(
        self,
        pairs: list[tuple[dict, dict]],
        atlas_designation_to_uic: dict[str, str],
    ) -> dict[str, list[tuple[dict, dict]]]:
        """Bucket pair tuples by anchor UIC, dropping pairs without an anchor."""
        by_anchor: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
        for left_node, right_node in pairs:
            anchor_uic = self._resolve_anchor_uic(left_node, right_node, atlas_designation_to_uic)
            if anchor_uic:
                by_anchor[anchor_uic].append((left_node, right_node))
        return by_anchor

    def _select_name_fallback_pairs_for_anchor(
        self,
        anchor_uic: str,
        strict_anchor_pairs: list[tuple[dict, dict]],
        relaxed_anchor_pairs: list[tuple[dict, dict]],
        already_grouped: set[str],
        atlas_uic_counts: dict[str, int],
    ) -> list[tuple[dict, dict, str]]:
        """Apply strict-complete then relaxed fallback for one name anchor UIC."""
        if strict_anchor_pairs:
            uic_node_ids = {entry['node_id'] for entry in self._uic_ref_dict.get(anchor_uic, [])}
            strict_pair_ids = {node['node_id'] for pair in strict_anchor_pairs for node in pair}
            strict_all_involved_ids = uic_node_ids | strict_pair_ids
            strict_grouped_ids = strict_all_involved_ids & already_grouped
            path1_group_count = sum(1 for node_id in uic_node_ids if node_id in self._group_siblings)
            strict_ungrouped_count = len(strict_all_involved_ids - strict_grouped_ids - strict_pair_ids)

            if self._is_complete_grouping(
                atlas_count=atlas_uic_counts.get(anchor_uic, 0),
                logical_osm_count=path1_group_count + len(strict_anchor_pairs),
                ungrouped_count=strict_ungrouped_count,
            ):
                return [(plat, sp, OSM_PAIR_NAME) for plat, sp in strict_anchor_pairs]

        if relaxed_anchor_pairs and atlas_uic_counts.get(anchor_uic, 0) > 0:
            return [(plat, sp, OSM_PAIR_NAME) for plat, sp in relaxed_anchor_pairs]

        return []

    @staticmethod
    def _is_complete_grouping(
        atlas_count: int,
        logical_osm_count: int,
        ungrouped_count: int,
    ) -> bool:
        """Return True when grouped + ungrouped OSM entities exactly match ATLAS."""
        effective_count = logical_osm_count + ungrouped_count
        return atlas_count > 0 and atlas_count == effective_count

    def _select_group_pairs(
        self,
        entries: list[dict],
        left_nodes: list[dict],
        right_nodes: list[dict],
        atlas_count: int,
        require_uic_non_divergence: bool = False,
    ) -> list[tuple[dict, dict]]:
        """Use 1.5 ratio for exact complete groups, else 2.0 for incomplete reciprocal pairs."""
        strict_pairs = self._find_reciprocal_pairs(
            left_nodes,
            right_nodes,
            GROUP_MAX_DISTANCE_M,
            GROUP_RATIO_TEST_FACTOR_STRICT,
            require_uic_non_divergence=require_uic_non_divergence,
        )
        if strict_pairs:
            strict_grouped_ids = {node['node_id'] for pair in strict_pairs for node in pair}
            strict_ungrouped_count = sum(1 for entry in entries if entry['node_id'] not in strict_grouped_ids)
            if self._is_complete_grouping(
                atlas_count=atlas_count,
                logical_osm_count=len(strict_pairs),
                ungrouped_count=strict_ungrouped_count,
            ):
                return strict_pairs

        relaxed_pairs = self._find_reciprocal_pairs(
            left_nodes,
            right_nodes,
            GROUP_MAX_DISTANCE_M,
            GROUP_RATIO_TEST_FACTOR_RELAXED,
            require_uic_non_divergence=require_uic_non_divergence,
        )
        if not relaxed_pairs:
            return []
        if atlas_count > 0:
            return relaxed_pairs

        return []

    def _register_group(self, plat: dict, sp: dict, group_type: str) -> None:
        """Register a platform ↔ stop_position group (platform = representative)."""
        rep_id = plat['node_id']
        sib_id = sp['node_id']
        self._group_representative[sib_id] = rep_id
        self._group_siblings[rep_id] = (group_type, [self._to_osm_node(sp)])

    def _register_trio(self, representative: dict, side_partner: dict, middle: dict) -> None:
        """Register a trio with one representative side node, one side sibling, and one middle node."""
        rep_id = str(representative['node_id'])
        side_partner_id = str(side_partner['node_id'])
        middle_id = str(middle['node_id'])
        side_partner_node = self._to_osm_node(side_partner)
        middle_node = self._to_osm_node(middle)

        self._group_representative[side_partner_id] = rep_id
        self._group_representative[middle_id] = rep_id
        self._group_siblings[rep_id] = ('osm_trio', [side_partner_node, middle_node])
        self._trio_middle_by_rep[rep_id] = middle_id
        self._trio_sides_by_rep[rep_id] = (rep_id, side_partner_id)

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
        sp_to_second_d: dict[str, float | None] = {}
        for sp in stop_positions:
            best_plat, best_d = None, None
            second_d = None
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
                if best_d is None or d < best_d:
                    second_d = best_d
                    best_d = d
                    best_plat = plat
                elif second_d is None or d < second_d:
                    second_d = d
            if best_plat is not None and best_d is not None and best_d <= max_distance:
                sp_to_nearest[sp['node_id']] = (best_plat, best_d)
                sp_to_second_d[sp['node_id']] = second_d

        # For each platform find nearest + second-nearest stop_position
        plat_to_nearest: dict[str, tuple[dict, float]] = {}
        plat_to_second_d: dict[str, float | None] = {}
        for plat in platforms:
            best_sp, best_d = None, None
            second_d = None
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
                if best_d is None or d < best_d:
                    second_d = best_d
                    best_d = d
                    best_sp = sp
                elif second_d is None or d < second_d:
                    second_d = d
            if best_sp is not None and best_d is not None and best_d <= max_distance:
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
            d2_sp = sp_to_second_d.get(sp['node_id'])
            if d2_sp is not None and d1_sp > 0 and d2_sp / d1_sp < ratio_factor:
                continue

            # Ratio test on platform side
            d1_plat = plat_to_nearest[plat['node_id']][1]
            d2_plat = plat_to_second_d.get(plat['node_id'])
            if d2_plat is not None and d1_plat > 0 and d2_plat / d1_plat < ratio_factor:
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

    @staticmethod
    def _resolve_entry_anchor_uic(entry: dict, atlas_designation_to_uic: dict[str, str]) -> Optional[str]:
        """Resolve a single entry to an anchor UIC via uic_ref or uic_name."""
        entry_uic = entry['tags'].get('uic_ref')
        if entry_uic:
            return entry_uic
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

    def get_trio_representatives(self) -> list[str]:
        """Return representative node IDs for all detected trios."""
        return list(self._trio_middle_by_rep.keys())

    def get_trio_for_representative(self, rep_id: str) -> tuple[str, str, str] | None:
        """Return (middle_node_id, side_node_id_1, side_node_id_2) for a trio representative."""
        if rep_id not in self._trio_middle_by_rep or rep_id not in self._trio_sides_by_rep:
            return None
        side_1, side_2 = self._trio_sides_by_rep[rep_id]
        return (self._trio_middle_by_rep[rep_id], side_1, side_2)

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

    def get_by_node_id(self, node_id: str) -> OsmEntity | None:
        """Return a node by id as OsmEntity, including siblings if representative."""
        for node_dict in self._all_nodes.values():
            if str(node_dict['node_id']) == str(node_id):
                return self._wrap_entity(node_dict)
        return None
        
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

            # Index representatives under their own key values and sibling key values,
            # so grouping keeps anchor visibility even when representative tags differ.
            values: set[str] = set()
            tags = node_dict.get('tags', {}) or {}
            own_val = tags.get(key)
            if own_val:
                values.add(str(own_val))

            sibling_entry = self._group_siblings.get(node_dict['node_id'])
            if sibling_entry is not None:
                _, siblings = sibling_entry
                for sibling in siblings:
                    sib_val = (sibling.tags or {}).get(key)
                    if sib_val:
                        values.add(str(sib_val))

            if not values:
                continue

            entity = self._wrap_entity(node_dict)
            for val in values:
                result[val].append(entity)

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
