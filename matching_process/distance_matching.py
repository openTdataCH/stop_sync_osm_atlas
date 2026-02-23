"""
Distance-based matching predicates.

Three predicates, each progressively looser:

* **group_proximity** – conflict-free bipartite matching within UIC / name groups
* **local_ref_distance** – exact ``local_ref`` match within *max_distance*
* **nearest_distance** – single-candidate or ratio-test proximity match
"""
from collections import defaultdict
import logging

import pandas as pd

from matching_process.pipeline import MatchingContext, make_match
from matching_process.utils import is_osm_station, haversine_distance

logger = logging.getLogger(__name__)

# Ratio-test constants (Stage 3b)
RATIO_TEST_MIN_D2 = 10   # minimum d2 in metres
RATIO_TEST_FACTOR = 4    # d2 / d1 must be ≥ this


# ---------------------------------------------------------------------------
# Shared helper – conflict-free bipartite matching
# ---------------------------------------------------------------------------

def bipartite_match(atlas_entries: list[dict], osm_nodes: list[dict],
                    max_distance: float) -> list[tuple[int, int, float]]:
    """
    Try a conflict-free nearest-neighbour assignment.

    Returns a list of ``(atlas_idx, osm_idx, distance)`` tuples when *every*
    ATLAS entry's nearest OSM node reciprocally agrees AND all distances are
    within *max_distance*.  Returns ``[]`` on any conflict or violation.
    """
    n = len(atlas_entries)
    if n != len(osm_nodes) or n == 0:
        return []

    # Build and sort the full distance matrix
    matrix: list[tuple[int, int, float]] = []
    for ai, a in enumerate(atlas_entries):
        for oi, o in enumerate(osm_nodes):
            d = haversine_distance(
                float(a['wgs84North']), float(a['wgs84East']),
                o['lat'], o['lon'],
            )
            if d is not None:
                matrix.append((ai, oi, d))
    matrix.sort(key=lambda x: x[2])

    # Each ATLAS entry's closest OSM
    a_to_o: dict[int, tuple[int, float]] = {}
    for ai, oi, d in matrix:
        if ai not in a_to_o:
            a_to_o[ai] = (oi, d)

    # Each OSM node's closest ATLAS
    o_to_a: dict[int, tuple[int, float]] = {}
    for ai, oi, d in matrix:
        if oi not in o_to_a:
            o_to_a[oi] = (ai, d)

    # Reciprocal check
    for ai, (oi, _) in a_to_o.items():
        if oi in o_to_a and o_to_a[oi][0] != ai:
            return []

    # Distance check
    for _, (_, d) in a_to_o.items():
        if d > max_distance:
            return []

    return [(ai, oi, d) for ai, (oi, d) in a_to_o.items()]


# ---------------------------------------------------------------------------
# Predicate 1 – group proximity
# ---------------------------------------------------------------------------

def group_proximity(ctx: MatchingContext) -> list[dict]:
    """Conflict-free bipartite proximity matching within UIC / name groups."""
    matches: list[dict] = []
    matched_here: set[str] = set()

    # --- Build OSM groupings ---
    osm_by: dict[str, dict[str, list[dict]]] = {
        'uic_ref': ctx.osm.get_all_unmatched_grouped('uic_ref', stop_position_only=False),
        'uic_name': ctx.osm.get_all_unmatched_grouped('uic_name', stop_position_only=False),
        'name': ctx.osm.get_all_unmatched_grouped('name', stop_position_only=False),
    }
    osm_sp_by: dict[str, dict[str, list[dict]]] = {
        'uic_ref': ctx.osm.get_all_unmatched_grouped('uic_ref', stop_position_only=True),
        'uic_name': ctx.osm.get_all_unmatched_grouped('uic_name', stop_position_only=True),
        'name': ctx.osm.get_all_unmatched_grouped('name', stop_position_only=True),
    }

    # --- Try each grouping key in priority order ---
    grouping_keys = [
        ('uic_ref', 'number'),
        ('uic_name', 'designationOfficial'),
        ('name', 'designationOfficial'),
    ]

    # Convert unmatched atlas dicts to grouping dictionary manually to avoid pandas
    remaining = [e for e in ctx.atlas.get_unmatched_records() if e['sloid'] not in matched_here]
    
    for osm_key, atlas_col in grouping_keys:
        grouped_atlas = defaultdict(list)
        for rec in remaining:
            val = rec.get(atlas_col)
            if pd.notna(val) and val != "":
                grouped_atlas[str(val)].append(rec)

        for group_val_str, atlas_entries in grouped_atlas.items():
            # Filter entries that might be matched already
            valid_atlas_entries = [e for e in atlas_entries if e['sloid'] not in matched_here]
            if not valid_atlas_entries:
                continue

            # Try all-nodes first, then stop_position-only fallback
            for node_pool, suffix in [
                (osm_by[osm_key].get(group_val_str, []), ''),
                (osm_sp_by[osm_key].get(group_val_str, []), '_stop_position'),
            ]:
                avail = [n for n in node_pool if not ctx.osm.is_used(n['node_id'])]
                pairs = bipartite_match(valid_atlas_entries, avail, ctx.max_distance)
                if not pairs:
                    continue

                for ai, oi, _dist in pairs:
                    entry = valid_atlas_entries[ai]
                    osm = avail[oi]
                    matches.append(make_match(
                        entry, osm,
                        f'distance_matching_1_{osm_key}{suffix}',
                        f"Conflict-free proximity match ({osm_key})",
                        pool_size=len(avail),
                    ))
                    matched_here.add(entry['sloid'])
                    ctx.osm.mark_used(osm['node_id'])
                break  # don't try stop_position fallback when all-nodes worked

        # update remaining logic
        remaining = [e for e in remaining if e['sloid'] not in matched_here]

    return matches


# ---------------------------------------------------------------------------
# Predicate 2 – local_ref within distance
# ---------------------------------------------------------------------------

def local_ref_distance(ctx: MatchingContext) -> list[dict]:
    """Match by exact ``local_ref`` == ATLAS ``designation`` within *max_distance*."""
    matches: list[dict] = []

    for entry in ctx.atlas.get_unmatched_records():
        desig = (
            str(entry.get('designation', '')).strip()
            if pd.notna(entry.get('designation')) else ''
        )
        if not desig:
            continue

        csv_lat = float(entry['wgs84North'])
        csv_lon = float(entry['wgs84East'])

        best_node = None
        best_dist = float('inf')

        # Will automatically omit used / station OSMs
        candidates = ctx.osm.query_radius(csv_lat, csv_lon, ctx.max_distance, include_stations=False)
        for node, d in candidates:
            lr = (node.get('local_ref') or '').strip()
            if lr.lower() != desig.lower():
                continue
            if d < best_dist:
                best_node = node
                best_dist = d

        if best_node:
            matches.append(make_match(
                entry, best_node, 'distance_matching_2',
                "Exact local_ref match within max_distance",
            ))
            ctx.osm.mark_used(best_node['node_id'])

    return matches


# ---------------------------------------------------------------------------
# Predicate 3 – nearest candidate / ratio test
# ---------------------------------------------------------------------------

def nearest_distance(ctx: MatchingContext) -> list[dict]:
    """Single-candidate match or ratio-test match within *max_distance*."""
    matches: list[dict] = []

    for entry in ctx.atlas.get_unmatched_records():
        csv_lat = float(entry['wgs84North'])
        csv_lon = float(entry['wgs84East'])

        # Collect all candidates within max_distance (already filters out used IDs & stations natively via KDTree)
        candidates = ctx.osm.query_radius(csv_lat, csv_lon, ctx.max_distance, include_stations=False)
        if not candidates:
            continue
            
        candidates.sort(key=lambda x: x[1])

        # Case A: single candidate
        if len(candidates) == 1:
            node, d = candidates[0]
            matches.append(make_match(
                entry, node, 'distance_matching_3a',
                "Single candidate within max_distance",
                pool_size=1,
            ))
            ctx.osm.mark_used(node['node_id'])

        # Case B: ratio test
        elif len(candidates) > 1:
            d1 = candidates[0][1]
            d2 = candidates[1][1]
            if d2 >= RATIO_TEST_MIN_D2 and d2 / d1 >= RATIO_TEST_FACTOR:
                node = candidates[0][0]
                matches.append(make_match(
                    entry, node, 'distance_matching_3b',
                    f"Ratio test: d1={d1:.1f}m, d2={d2:.1f}m, "
                    f"ratio={d2 / d1:.1f}",
                    pool_size=len(candidates),
                ))
                ctx.osm.mark_used(node['node_id'])

    return matches
