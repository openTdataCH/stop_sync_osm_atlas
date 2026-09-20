"""
ProblemContext — precomputed shared state for all problem predicates.

Built once from pipeline output, then passed to every predicate so that
expensive operations (KDTree construction, UIC counting) happen only once.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

from typing import TYPE_CHECKING

from scipy.spatial import KDTree
from transport_matcher.profiles import MatchingProfile
from transport_matcher.core.route_state import RouteState

from transport_matcher.core.utils.spatial_index import to_xyz, batch_to_xyz, meters_to_unit_chord_radius

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from transport_matcher.core.models import MatchingOutput, MatchRecord, SourceStop, OsmNode

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

    profile: MatchingProfile = field(default_factory=MatchingProfile)
    route_state: RouteState = field(default_factory=RouteState)

    # Spatial indexes for unmatched priority computation
    osm_kdtree: Optional[KDTree] = None
    osm_points: list = field(default_factory=list)
    source_kdtree: Optional[KDTree] = None
    source_points: list = field(default_factory=list)

    # UIC population counts (for unmatched priority)
    source_count_by_uic: dict = field(default_factory=dict)
    osm_count_by_uic: dict = field(default_factory=dict)
    osm_platform_count_by_uic: dict = field(default_factory=dict)

    # Route evidence lookups for matched-pair diagnostics
    source_route_evidence_by_key: dict[str, dict[str, list]] = field(default_factory=dict)
    osm_node_routes: dict[str, list[dict]] = field(default_factory=dict)
    osm_name_dirs: dict[str, set[str]] = field(default_factory=dict)

    # Duplicate maps
    duplicate_key_map: dict = field(default_factory=dict)       # {key: [group]}
    duplicate_osm_group_map: dict = field(default_factory=dict)   # {node_id: [group]}
    duplicate_osm_node_ids: set = field(default_factory=set)      # set of node_ids
    handled_duplicate_keys: set = field(default_factory=set)    # source keys already handled by duplicate_propagation

    @classmethod
    def build(cls, output: 'MatchingOutput') -> "ProblemContext":
        """One-time construction of every shared index from pipeline output."""
        # Using output.duplicate_key_map
        ctx = cls(
            duplicate_key_map=output.duplicate_key_map,
            source_route_evidence_by_key=getattr(output, 'source_route_evidence_by_key', {}) or {},
            osm_node_routes=getattr(output, 'osm_node_routes', {}) or {},
            osm_name_dirs=getattr(output, 'osm_name_dirs', {}) or {},
        )

        matched = output.matched
        unmatched_source = output.unmatched_source
        unmatched_osm = output.unmatched_osm

        # -- Spatial indexes --------------------------------------------------
        ctx._build_spatial_indexes(matched, unmatched_source, unmatched_osm)

        # -- UIC counts -------------------------------------------------------
        ctx._build_uic_counts(matched, unmatched_source, unmatched_osm)

        # -- Build set of OSM node IDs that are members of pre-grouped stop units --
        grouped_osm_node_ids: set[str] = set()
        for stop_unit in getattr(output, 'osm_stop_units', []):
            if getattr(stop_unit, 'stop_kind', 'single') == 'single':
                continue
            for member in getattr(stop_unit, 'members', []):
                grouped_osm_node_ids.add(str(member.node_id))

        # -- OSM duplicate groups (excludes pre-grouped nodes) ----------------
        ctx._build_osm_duplicate_map(matched, unmatched_osm, grouped_osm_node_ids)

        # -- Track source keys handled by duplicate_propagation --------------
        for rec in matched:
            if rec.match_type == 'duplicate_propagation':
                ctx.handled_duplicate_keys.add(str(rec.source_node.key))

        return ctx

    # ------------------------------------------------------------------
    # Public helpers used by predicates
    # ------------------------------------------------------------------

    def nearest_osm_distance(self, lat: float, lon: float) -> Optional[float]:
        """Great-circle distance (m) to the closest OSM point, or None."""
        return self._nearest_distance(self.osm_kdtree, self.osm_points, lat, lon)

    def nearest_source_distance(self, lat: float, lon: float) -> Optional[float]:
        """Great-circle distance (m) to the closest source point, or None."""
        return self._nearest_distance(self.source_kdtree, self.source_points, lat, lon)

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    def _build_spatial_indexes(self, matched: list['MatchRecord'], unmatched_source: list['SourceStop'], unmatched_osm: list['OsmNode']):
        # OSM point cloud (matched osm + unmatched osm)
        osm_coords = []
        for rec in matched:
            osm_coords.append((rec.osm_node.lat, rec.osm_node.lon))
        for node in unmatched_osm:
            osm_coords.append((node.lat, node.lon))

        if osm_coords:
            self.osm_points = batch_to_xyz(osm_coords).tolist()
            self.osm_kdtree = KDTree(self.osm_points)

        # source point cloud (matched source + unmatched source)
        source_coords = []
        for rec in matched:
            source_coords.append((rec.source_node.lat, rec.source_node.lon))
        for node in unmatched_source:
            source_coords.append((node.lat, node.lon))

        if source_coords:
            self.source_points = batch_to_xyz(source_coords).tolist()
            self.source_kdtree = KDTree(self.source_points)

    def _build_uic_counts(self, matched: list['MatchRecord'], unmatched_source: list['SourceStop'], unmatched_osm: list['OsmNode']):
        # source UIC counts
        for rec in matched:
            if rec.source_node.station_ref:
                key = str(rec.source_node.station_ref)
                self.source_count_by_uic[key] = self.source_count_by_uic.get(key, 0) + 1
        for node in unmatched_source:
            if node.station_ref:
                key = str(node.station_ref)
                self.source_count_by_uic[key] = self.source_count_by_uic.get(key, 0) + 1

        # OSM UIC counts (+ platform sub-count)
        for rec in matched:
            if rec.osm_node.station_ref:
                key = str(rec.osm_node.station_ref)
                self.osm_count_by_uic[key] = self.osm_count_by_uic.get(key, 0) + 1
                if rec.osm_node.is_station is False and _is_platform_like(rec.osm_node.public_transport):
                    self.osm_platform_count_by_uic[key] = self.osm_platform_count_by_uic.get(key, 0) + 1
                    
        for node in unmatched_osm:
            if node.station_ref:
                key = str(node.station_ref)
                self.osm_count_by_uic[key] = self.osm_count_by_uic.get(key, 0) + 1
                if node.is_station is False and _is_platform_like(node.public_transport):
                    self.osm_platform_count_by_uic[key] = self.osm_platform_count_by_uic.get(key, 0) + 1

    def _build_osm_duplicate_map(self, matched: list['MatchRecord'], unmatched_osm: list['OsmNode'],
                                 grouped_osm_node_ids: set[str] | None = None):
        """Build OSM duplicate groups by (uic_ref, local_ref) for platform-like nodes.

        Excludes node IDs that are members of pre-grouped OSM pairs (platform ↔ stop_position)
        to avoid flagging handled groups as duplicates.
        """
        grouped_osm_node_ids = grouped_osm_node_ids or set()
        by_key: dict[tuple, set] = {}

        def _add(uic, local_ref, node_id, pt):
            if not uic or not local_ref or not _is_platform_like(pt):
                return
            if str(node_id) in grouped_osm_node_ids:
                return
            key = (str(uic).strip(), str(local_ref).strip().lower())
            by_key.setdefault(key, set()).add(str(node_id))

        for rec in matched:
            _add(
                rec.osm_node.station_ref,
                rec.osm_node.local_ref,
                rec.osm_node.node_id,
                rec.osm_node.public_transport,
            )
        for node in unmatched_osm:
            _add(
                node.station_ref,
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
