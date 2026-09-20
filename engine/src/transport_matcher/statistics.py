"""Pure quality summaries computed with a matching run, never by the review app."""
import math
import logging
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

def _compute_no_nearby_atlas_count(
    matched_records: list,
    unmatched_atlas: list,
    unmatched_osm: list,
    radius_m: float = 50.0,
) -> int:
    """Count unmatched OSM nodes with no ATLAS node within *radius_m* metres.

    Builds a temporary KDTree of all ATLAS positions (matched + unmatched)
    and queries each unmatched OSM node against it.
    """
    try:
        from scipy.spatial import KDTree
        from transport_matcher.core.utils.spatial_index import batch_to_xyz, to_xyz
    except Exception:
        return 0

    atlas_coords = []
    for rec in matched_records:
        a = getattr(rec, 'source_node', None)
        if a and getattr(a, 'lat', None) is not None:
            atlas_coords.append((float(a.lat), float(a.lon)))
    for node in unmatched_atlas:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is not None and lon is not None :
            atlas_coords.append((float(lat), float(lon)))

    if not atlas_coords:
        return len(unmatched_osm)

    atlas_xyz = batch_to_xyz(atlas_coords)
    tree = KDTree(atlas_xyz)

    # Convert radius to unit-sphere chord distance
    chord_r = 2 * math.sin(radius_m / (2 * 6_371_000))

    no_nearby_count = 0
    for node in unmatched_osm:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is None or lon is None:
            no_nearby_count += 1
            continue
        xyz = to_xyz(float(lat), float(lon))
        dist, _ = tree.query(xyz, k=1)
        if dist > chord_r:
            no_nearby_count += 1

    return no_nearby_count


def _classify_match_type(match_type: str) -> str:
    """Map a raw match_type string to a display stage name."""
    if match_type == 'exact':
        return 'exact'
    if match_type == 'name':
        return 'name'
    if match_type == 'distance_matching_trio':
        return 'distance_trio'
    if match_type == 'distance_matching_1_uic_ref':
        return 'distance_stage1_uic_ref'
    if match_type == 'distance_matching_1_uic_name':
        return 'distance_stage1_uic_name'
    if match_type == 'distance_matching_1_name':
        return 'distance_stage1_name'
    if match_type.startswith('distance_matching_1_'):
        return 'distance_stage1'
    if match_type == 'long_distance_group_proximity_uic_ref':
        return 'distance_stage1b_uic_ref'
    if match_type == 'long_distance_group_proximity_uic_name':
        return 'distance_stage1b_uic_name'
    if match_type == 'long_distance_group_proximity_name':
        return 'distance_stage1b_name'
    if match_type.startswith('long_distance_group_proximity_'):
        return 'distance_stage1b'
    if match_type == 'distance_matching_2':
        return 'distance_stage2'
    if match_type == 'distance_matching_3a':
        return 'distance_stage3a_pass1'
    if match_type == 'distance_matching_3a_second_pass':
        return 'distance_stage3a_pass2'
    if match_type == 'distance_matching_3b':
        return 'distance_stage3b'
    if 'gtfs' in match_type:
        return 'route_gtfs'
    if match_type.startswith('route_'):
        return 'route_gtfs'
    if match_type == 'duplicate_propagation':
        return 'post_duplicate_propagation'
    if match_type == 'osm_group_propagation':
        return 'post_osm_group_propagation'
    return 'other'


def _distance_stats(distances: List[float]) -> Dict[str, Any]:
    """Compute mean, median, p95 for a list of distances."""
    if not distances:
        return {"mean_m": None, "median_m": None, "p95_m": None, "count": 0}
    distances_sorted = sorted(distances)
    p95_idx = int(math.ceil(0.95 * len(distances_sorted))) - 1
    return {
        "mean_m": round(statistics.mean(distances_sorted), 2),
        "median_m": round(statistics.median(distances_sorted), 2),
        "p95_m": round(distances_sorted[max(0, p95_idx)], 2),
        "count": len(distances_sorted),
    }


def compute_quality_metrics(
    matched_records: list,
    all_osm_nodes: list,
    osm_stop_units: list | None = None,
) -> Dict[str, Any]:
    """Compute matching quality metrics from pipeline results.

    Builds a temporary KDTree of all OSM nodes to evaluate whether each
    matched pair uses the nearest available OSM node.
    """
    from scipy.spatial import KDTree
    from transport_matcher.core.utils.spatial_index import batch_to_xyz, to_xyz

    # ------------------------------------------------------------------
    # 1. Distance quality
    # ------------------------------------------------------------------
    all_distances: List[float] = []
    distances_by_stage: Dict[str, List[float]] = defaultdict(list)

    for rec in matched_records:
        d = getattr(rec, 'distance_m', None)
        if d is not None and not math.isnan(d):
            all_distances.append(d)
            stage = _classify_match_type(getattr(rec, 'match_type', '') or '')
            distances_by_stage[stage].append(d)

    overall_dist = _distance_stats(all_distances)
    by_stage_dist = {stage: _distance_stats(dists) for stage, dists in sorted(distances_by_stage.items())}

    # Build KDTree for "not matched to closest" and cross-predicate consistency
    osm_coords: List[Tuple[float, float]] = []
    osm_node_ids: List[str] = []
    for node in all_osm_nodes:
        lat, lon = getattr(node, 'lat', None), getattr(node, 'lon', None)
        if lat is not None and lon is not None :
            osm_coords.append((float(lat), float(lon)))
            osm_node_ids.append(str(node.node_id))

    not_closest_count = 0
    consistent_count = 0
    total_evaluated = 0
    not_closest_by_stage: Dict[str, int] = {}

    if osm_coords:
        osm_xyz = batch_to_xyz(osm_coords)
        tree = KDTree(osm_xyz)

        for rec in matched_records:
            atlas_node = getattr(rec, 'source_node', None)
            osm_node = getattr(rec, 'osm_node', None)
            if atlas_node is None or osm_node is None:
                continue
            a_lat, a_lon = getattr(atlas_node, 'lat', None), getattr(atlas_node, 'lon', None)
            matched_osm_id = str(osm_node.node_id)
            if a_lat is None or a_lon is None:
                continue

            query_point = to_xyz(a_lat, a_lon)
            nearest_distance, idx = tree.query(query_point, k=1)
            nearest_osm_id = osm_node_ids[idx]
            
            stage = _classify_match_type(getattr(rec, 'match_type', '') or '')

            total_evaluated += 1
            matched_point = to_xyz(osm_node.lat, osm_node.lon)
            matched_distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(query_point, matched_point)))
            if matched_distance <= nearest_distance + 1e-12:
                consistent_count += 1
            else:
                not_closest_count += 1
                not_closest_by_stage[stage] = not_closest_by_stage.get(stage, 0) + 1

    not_closest_pct = round(not_closest_count / total_evaluated * 100, 1) if total_evaluated else 0.0
    consistency_pct = round(consistent_count / total_evaluated * 100, 1) if total_evaluated else 0.0

    distance_quality = {
        "overall": overall_dist,
        "by_stage": by_stage_dist,
        "not_matched_to_closest": {
            "count": not_closest_count,
            "total_evaluated": total_evaluated,
            "percent": not_closest_pct,
        },
        "not_matched_to_closest_by_stage": not_closest_by_stage,
    }

    # ------------------------------------------------------------------
    # 2. Many-to-one analysis
    # ------------------------------------------------------------------
    node_to_stop_id: Dict[str, str] = {}
    for stop_idx, stop_unit in enumerate(osm_stop_units or []):
        for member in getattr(stop_unit, 'members', []) or []:
            node_id = getattr(member, 'node_id', None)
            if node_id:
                node_to_stop_id[str(node_id)] = str(stop_idx)

    atlas_to_osm: Dict[str, set] = defaultdict(set)
    osm_to_atlas: Dict[str, set] = defaultdict(set)

    for rec in matched_records:
        sloid = getattr(getattr(rec, 'source_node', None), 'key', None)
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if sloid and osm_id:
            canonical_osm_stop = node_to_stop_id.get(str(osm_id), f"node:{osm_id}")
            atlas_to_osm[str(sloid)].add(canonical_osm_stop)
            osm_to_atlas[canonical_osm_stop].add(str(sloid))

    atlas_multi = {s: ids for s, ids in atlas_to_osm.items() if len(ids) > 1}
    osm_multi = {n: ids for n, ids in osm_to_atlas.items() if len(ids) > 1}

    # Calculate distributions for many-to-one matches
    atlas_dist_counts = defaultdict(int)
    for ids in atlas_multi.values():
        atlas_dist_counts[len(ids)] += 1
    atlas_distribution = [
        {"ratio": f"1A:{n}O", "count": count}
        for n, count in sorted(atlas_dist_counts.items())
    ]

    osm_dist_counts = defaultdict(int)
    for ids in osm_multi.values():
        osm_dist_counts[len(ids)] += 1
    osm_distribution = [
        {"ratio": f"{n}A:1O", "count": count}
        for n, count in sorted(osm_dist_counts.items())
    ]

    many_to_one = {
        "atlas_to_multiple_osm": {
            "count": len(atlas_multi),
            "max_per_atlas": max((len(v) for v in atlas_multi.values()), default=0),
            "distribution": atlas_distribution,
        },
        "osm_to_multiple_atlas": {
            "count": len(osm_multi),
            "max_per_osm": max((len(v) for v in osm_multi.values()), default=0),
            "distribution": osm_distribution,
        },
    }

    # ------------------------------------------------------------------
    # 3. Cross-predicate consistency (reuses KDTree results from above)
    # ------------------------------------------------------------------
    cross_predicate = {
        "consistent_with_nearest": consistent_count,
        "would_differ_by_nearest": not_closest_count,
        "total_evaluated": total_evaluated,
        "consistency_percent": consistency_pct,
    }

    # ------------------------------------------------------------------
    # 4. OSM stop-unit grouping stats
    # ------------------------------------------------------------------
    osm_stop_units = osm_stop_units or []

    matched_osm_ids = set()
    for rec in matched_records:
        osm_id = getattr(getattr(rec, 'osm_node', None), 'node_id', None)
        if osm_id:
            matched_osm_ids.add(str(osm_id))

    grouped_units = [u for u in osm_stop_units if getattr(u, 'stop_kind', 'single') in ('pair', 'trio')]
    total_groups = len(grouped_units)
    by_type: Dict[str, int] = defaultdict(int)
    both_matched = 0
    neither_matched = 0

    for stop_unit in grouped_units:
        group_key = getattr(stop_unit, 'group_kind', None) or getattr(stop_unit, 'stop_kind', 'unknown')
        by_type[group_key] += 1
        member_ids = [str(member.node_id) for member in getattr(stop_unit, 'members', [])]
        if any(member_id in matched_osm_ids for member_id in member_ids):
            both_matched += 1
        else:
            neither_matched += 1

    osm_group_stats = {
        "total_groups": total_groups,
        "by_type": dict(by_type),
        "both_members_matched": both_matched,
        "neither_matched": neither_matched,
    }

    logger.info(
        f"Quality metrics: consistency={consistency_pct}%, "
        f"not_closest={not_closest_count}, many_to_one_atlas={len(atlas_multi)}, "
        f"osm_groups={total_groups}"
    )

    return {
        "distance_quality": distance_quality,
        "many_to_one": many_to_one,
        "cross_predicate_consistency": cross_predicate,
        "osm_groups": osm_group_stats,
    }


