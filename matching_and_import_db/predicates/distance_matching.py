"""
Distance-based matching predicates.

Three predicates, each progressively looser:

* **group_proximity** – conflict-free bipartite matching within UIC / name groups
* **local_ref_distance** – exact ``local_ref`` match within *max_distance*
* **nearest_distance** – single-candidate or ratio-test proximity match
"""
import numpy as np
from collections import defaultdict
import logging

from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.models import AtlasNode, OsmNode
from matching_and_import_db.utils.common import haversine_distance

logger = logging.getLogger(__name__)

# Ratio-test constants (Stage 3b)
RATIO_TEST_MIN_D2 = 10   # minimum d2 in metres
RATIO_TEST_FACTOR = 4    # d2 / d1 must be ≥ this


# ---------------------------------------------------------------------------
# Shared helper – conflict-free bipartite matching
# ---------------------------------------------------------------------------

def bipartite_match(atlas_entries: list[AtlasNode], osm_nodes: list[OsmNode],
                    max_distance: float) -> list[tuple[int, int, float]]:
    """
    Try a conflict-free nearest-neighbour assignment.

    Returns a list of ``(atlas_idx, osm_idx, distance)`` tuples when *every*
    ATLAS entry's nearest OSM node reciprocally agrees AND all distances are
    within *max_distance*.  Returns ``[]`` on any conflict or violation.
    """
    n = len(atlas_entries)
    m = len(osm_nodes)
    if n != m or n == 0:
        return []

    # Extract coordinates
    a_coords = np.array([(a.lat, a.lon) for a in atlas_entries])
    o_coords = np.array([(o.lat, o.lon) for o in osm_nodes])
    
    # Broadcast to n x m x 2
    lat1 = np.radians(a_coords[:, 0])[:, np.newaxis]
    lon1 = np.radians(a_coords[:, 1])[:, np.newaxis]
    lat2 = np.radians(o_coords[:, 0])[np.newaxis, :]
    lon2 = np.radians(o_coords[:, 1])[np.newaxis, :]
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    
    R = 6371000.0
    dist_matrix = R * c

    # Find nearest OSM for each ATLAS
    min_osm_indices = np.argmin(dist_matrix, axis=1)
    # Find nearest ATLAS for each OSM
    min_atlas_indices = np.argmin(dist_matrix, axis=0)

    results = []
    
    for ai in range(n):
        oi = min_osm_indices[ai]
        if min_atlas_indices[oi] == ai: # Mutual nearest
            d = float(dist_matrix[ai, oi])
            if d <= max_distance:
                results.append((ai, int(oi), d))
            else:
                return []
        else:
            return []
            
    return results


# ---------------------------------------------------------------------------
# Predicate 1 – group proximity
# ---------------------------------------------------------------------------

class GroupProximityPredicate(BasePredicate):
    """Conflict-free bipartite proximity matching within UIC / name groups."""

    def run(self, ctx: MatchingContext) -> None:
        matched_here: set[str] = set()

        # --- Build OSM groupings ---
        osm_by: dict[str, dict[str, list[OsmNode]]] = {
            'uic_ref': ctx.osm.get_all_unmatched_grouped('uic_ref'),
            'uic_name': ctx.osm.get_all_unmatched_grouped('uic_name'),
            'name': ctx.osm.get_all_unmatched_grouped('name'),
        }

        # --- Try each grouping key in priority order ---
        # Note: 'number' -> uic_ref, 'designationOfficial' -> designation_official.
        grouping_keys = [
            ('uic_ref', lambda n: n.uic_ref),
            ('uic_name', lambda n: n.designation_official),
            ('name', lambda n: n.designation_official),
        ]

        # Convert unmatched atlas entries to list
        remaining = [e for e in ctx.atlas.get_unmatched_records() if e.sloid not in matched_here]
        
        for osm_key, getter in grouping_keys:
            grouped_atlas = defaultdict(list)
            for rec in remaining:
                val = getter(rec)
                if val and val != "":
                    grouped_atlas[str(val)].append(rec)

            for group_val_str, atlas_entries in grouped_atlas.items():
                valid_atlas_entries = [e for e in atlas_entries if e.sloid not in matched_here]
                if not valid_atlas_entries:
                    continue

                avail = [n for n in osm_by[osm_key].get(group_val_str, [])
                         if not ctx.osm.is_used(n.node_id)]
                pairs = bipartite_match(valid_atlas_entries, avail, ctx.max_distance)
                if not pairs:
                    continue

                for ai, oi, dist in pairs:
                    entry = valid_atlas_entries[ai]
                    osm = avail[oi]
                    ctx.commit(
                        atlas_node=entry,
                        osm_node=osm,
                        match_type=f'distance_matching_1_{osm_key}',
                        distance_m=dist,
                        notes=f"Conflict-free proximity match ({osm_key})",
                    )
                    matched_here.add(entry.sloid)

            # update remaining logic
            remaining = [e for e in remaining if e.sloid not in matched_here]


# ---------------------------------------------------------------------------
# Predicate 2 – local_ref within distance
# ---------------------------------------------------------------------------

class LocalRefDistancePredicate(BasePredicate):
    """Match by exact ``local_ref`` == ATLAS ``designation`` within *max_distance*."""

    def run(self, ctx: MatchingContext) -> None:
        unmatched = ctx.atlas.get_unmatched_records()
        if not unmatched:
            return

        coords = [(e.lat, e.lon) for e in unmatched]
        batch_candidates = ctx.osm.batch_query_radius(coords, ctx.max_distance, include_stations=False)

        for i, entry in enumerate(unmatched):
            desig = (entry.designation or '').strip()
            if not desig:
                continue

            best_node = None
            best_dist = float('inf')

            # Will automatically omit used / station OSMs
            candidates = batch_candidates[i]
            for node, d in candidates:
                lr = (node.local_ref or '').strip()
                if lr.lower() != desig.lower():
                    continue
                if d < best_dist:
                    best_node = node
                    best_dist = d

            if best_node:
                ctx.commit(
                    atlas_node=entry,
                    osm_node=best_node,
                    match_type='distance_matching_2',
                    distance_m=best_dist,
                    notes="Exact local_ref match within max_distance",
                )


# ---------------------------------------------------------------------------
# Predicate 3 – nearest candidate / ratio test
# ---------------------------------------------------------------------------

class NearestDistancePredicate(BasePredicate):
    """Single-candidate match or ratio-test match within *max_distance*."""

    def run(self, ctx: MatchingContext) -> None:
        unmatched = ctx.atlas.get_unmatched_records()
        if not unmatched:
            return

        coords = [(e.lat, e.lon) for e in unmatched]
        batch_candidates = ctx.osm.batch_query_radius(coords, ctx.max_distance, include_stations=False)

        for i, entry in enumerate(unmatched):
            # Collect all candidates within max_distance (already filters out used IDs & stations natively via KDTree)
            candidates = batch_candidates[i]
            if not candidates:
                continue
                
            # Filter out candidates whose local_ref contradicts ATLAS designation
            desig = (entry.designation or '').strip().lower()
            if desig:
                candidates = [
                    (node, d) for node, d in candidates
                    if not (node.local_ref or '').strip() or (node.local_ref or '').strip().lower() == desig
                ]
                if not candidates:
                    continue

            candidates.sort(key=lambda x: x[1])

            # Case A: single candidate
            if len(candidates) == 1:
                node, d = candidates[0]
                ctx.commit(
                    atlas_node=entry,
                    osm_node=node,
                    match_type='distance_matching_3a',
                    distance_m=d,
                    notes="Single candidate within max_distance",
                )

            # Case B: ratio test
            elif len(candidates) > 1:
                d1 = candidates[0][1]
                d2 = candidates[1][1]
                if d2 >= RATIO_TEST_MIN_D2 and d2 / d1 >= RATIO_TEST_FACTOR:
                    node = candidates[0][0]
                    ctx.commit(
                        atlas_node=entry,
                        osm_node=node,
                        match_type='distance_matching_3b',
                        distance_m=d1,
                        notes=f"Ratio test: d1={d1:.1f}m, d2={d2:.1f}m, ratio={d2 / d1:.1f}",
                    )
