"""
ProblemContext — precomputed shared state for all problem predicates.

Built once from pipeline output, then passed to every predicate so that
expensive operations (KDTree construction, UIC counting) happen only once.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

from scipy.spatial import KDTree

from matching_and_import_db.utils.spatial_index import to_xyz, batch_to_xyz, meters_to_unit_chord_radius

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Distance thresholds for priority classification (meters)
DISTANCE_THRESHOLD_P1 = 80
DISTANCE_THRESHOLD_P2 = 25
DISTANCE_THRESHOLD_P3 = 15

# Attribute check toggles
ENABLE_OPERATOR_MISMATCH_CHECK = True
ENABLE_NAME_MISMATCH_CHECK = True
ENABLE_UIC_MISMATCH_CHECK = True
ENABLE_LOCAL_REF_MISMATCH_CHECK = True

# Isolation radius (meters)
ISOLATION_CHECK_RADIUS_M = 50


def _safe(val):
    """Return None for NaN / Inf / pandas-NA, else the value itself."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    # Handle numpy/pandas NA types without importing pandas on every call
    try:
        if val != val:  # NaN != NaN is True
            return None
    except (TypeError, ValueError):
        pass
    return val


def _is_platform_like(pt: Optional[str]) -> bool:
    return pt in ('platform', 'stop_position')


# ---------------------------------------------------------------------------
# ProblemContext
# ---------------------------------------------------------------------------

@dataclass
class ProblemContext:
    """Precomputed indexes shared across all problem predicates."""

    # Spatial indexes for unmatched priority computation
    osm_kdtree: Optional[KDTree] = None
    osm_points: list = field(default_factory=list)
    atlas_kdtree: Optional[KDTree] = None
    atlas_points: list = field(default_factory=list)

    # UIC population counts (for unmatched priority)
    atlas_count_by_uic: dict = field(default_factory=dict)
    osm_count_by_uic: dict = field(default_factory=dict)
    osm_platform_count_by_uic: dict = field(default_factory=dict)

    # Duplicate maps
    duplicate_sloid_map: dict = field(default_factory=dict)       # {sloid: [group]}
    duplicate_osm_group_map: dict = field(default_factory=dict)   # {node_id: [group]}
    duplicate_osm_node_ids: set = field(default_factory=set)      # set of node_ids

    @classmethod
    def build(cls, output: 'MatchingOutput') -> "ProblemContext":
        """One-time construction of every shared index from pipeline output."""
        # Using output.duplicate_sloid_map 
        ctx = cls(duplicate_sloid_map=output.duplicate_sloid_map)

        matched = output.matched
        unmatched_atlas = output.unmatched_atlas
        unmatched_osm = output.unmatched_osm

        # -- Spatial indexes --------------------------------------------------
        ctx._build_spatial_indexes(matched, unmatched_atlas, unmatched_osm)

        # -- UIC counts -------------------------------------------------------
        ctx._build_uic_counts(matched, unmatched_atlas, unmatched_osm)

        # -- OSM duplicate groups ---------------------------------------------
        ctx._build_osm_duplicate_map(matched, unmatched_osm)

        return ctx

    # ------------------------------------------------------------------
    # Public helpers used by predicates
    # ------------------------------------------------------------------

    def nearest_osm_distance(self, lat: float, lon: float) -> Optional[float]:
        """Great-circle distance (m) to the closest OSM point, or None."""
        return self._nearest_distance(self.osm_kdtree, self.osm_points, lat, lon)

    def nearest_atlas_distance(self, lat: float, lon: float) -> Optional[float]:
        """Great-circle distance (m) to the closest ATLAS point, or None."""
        return self._nearest_distance(self.atlas_kdtree, self.atlas_points, lat, lon)

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    def _build_spatial_indexes(self, matched: list['MatchRecord'], unmatched_atlas: list['AtlasNode'], unmatched_osm: list['OsmNode']):
        # OSM point cloud (matched osm + unmatched osm)
        osm_coords = []
        for rec in matched:
            osm_coords.append((rec.osm_node.lat, rec.osm_node.lon))
        for node in unmatched_osm:
            osm_coords.append((node.lat, node.lon))

        if osm_coords:
            self.osm_points = batch_to_xyz(osm_coords).tolist()
            self.osm_kdtree = KDTree(self.osm_points)

        # ATLAS point cloud (matched atlas + unmatched atlas)
        atlas_coords = []
        for rec in matched:
            atlas_coords.append((rec.atlas_node.lat, rec.atlas_node.lon))
        for node in unmatched_atlas:
            atlas_coords.append((node.lat, node.lon))

        if atlas_coords:
            self.atlas_points = batch_to_xyz(atlas_coords).tolist()
            self.atlas_kdtree = KDTree(self.atlas_points)

    def _build_uic_counts(self, matched: list['MatchRecord'], unmatched_atlas: list['AtlasNode'], unmatched_osm: list['OsmNode']):
        # ATLAS UIC counts
        for rec in matched:
            if rec.atlas_node.uic_ref:
                key = str(rec.atlas_node.uic_ref)
                self.atlas_count_by_uic[key] = self.atlas_count_by_uic.get(key, 0) + 1
        for node in unmatched_atlas:
            if node.uic_ref:
                key = str(node.uic_ref)
                self.atlas_count_by_uic[key] = self.atlas_count_by_uic.get(key, 0) + 1

        # OSM UIC counts (+ platform sub-count)
        for rec in matched:
            if rec.osm_node.uic_ref:
                key = str(rec.osm_node.uic_ref)
                self.osm_count_by_uic[key] = self.osm_count_by_uic.get(key, 0) + 1
                if rec.osm_node.is_station is False and _is_platform_like(rec.osm_node.public_transport):
                    self.osm_platform_count_by_uic[key] = self.osm_platform_count_by_uic.get(key, 0) + 1
                    
        for node in unmatched_osm:
            if node.uic_ref:
                key = str(node.uic_ref)
                self.osm_count_by_uic[key] = self.osm_count_by_uic.get(key, 0) + 1
                if node.is_station is False and _is_platform_like(node.public_transport):
                    self.osm_platform_count_by_uic[key] = self.osm_platform_count_by_uic.get(key, 0) + 1

    def _build_osm_duplicate_map(self, matched: list['MatchRecord'], unmatched_osm: list['OsmNode']):
        """Build OSM duplicate groups by (uic_ref, local_ref) for platform-like nodes."""
        by_key: dict[tuple, set] = {}

        def _add(uic, local_ref, node_id, pt):
            if not uic or not local_ref or not _is_platform_like(pt):
                return
            key = (str(uic).strip(), str(local_ref).strip().lower())
            by_key.setdefault(key, set()).add(str(node_id))

        for rec in matched:
            _add(
                rec.osm_node.uic_ref,
                rec.osm_node.local_ref,
                rec.osm_node.node_id,
                rec.osm_node.public_transport,
            )
        for node in unmatched_osm:
            _add(
                node.uic_ref,
                node.local_ref,
                node.node_id,
                node.public_transport,
            )

        for node_ids in by_key.values():
            if len(node_ids) >= 2:
                self.duplicate_osm_node_ids.update(node_ids)
                group = sorted(node_ids)
                for nid in node_ids:
                    self.duplicate_osm_group_map[nid] = group

    # ------------------------------------------------------------------
    # Shared nearest-distance helper
    # ------------------------------------------------------------------

    @staticmethod
    def _nearest_distance(tree: Optional[KDTree], points: list,
                          lat: float, lon: float) -> Optional[float]:
        if tree is None or not points:
            return None
        try:
            xyz = to_xyz(lat, lon)
            dist, idx = tree.query(xyz, k=1)
            # Convert chord distance on unit sphere to great-circle meters
            cos_theta = max(-1.0, min(1.0, 1 - (dist * dist) / 2.0))
            return 6371000.0 * math.acos(cos_theta)
        except Exception:
            return None
