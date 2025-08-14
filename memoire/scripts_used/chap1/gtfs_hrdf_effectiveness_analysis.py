"""
OUTDATED ANALYSIS SCRIPT - This script was used for thesis research comparing GTFS vs HRDF strategies.
The main pipeline now uses unified route matching. The old separate strategy approach is no longer supported.
Some functions in this script may not work correctly with the current codebase.
"""
import os
import json
import math
import logging
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple, Optional

import numpy as np
import pandas as pd

# Optional plotting; degrade gracefully if matplotlib not available
try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None

from matching_process.matching_script import parse_osm_xml
from matching_process.route_matching_unified import perform_unified_route_matching, _get_osm_directions_from_xml
from matching_process.utils import haversine_distance


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _safe_int_str(x) -> str:
    """Convert to clean integer string when possible; return empty string otherwise."""
    try:
        if pd.isna(x):
            return ""
        return str(int(float(x)))
    except Exception:
        return ""


def _series_to_set(series: pd.Series) -> Set[str]:
    return set(s for s in series.dropna().astype(str).map(str.strip) if s)


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return math.nan
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union > 0 else 0.0


def _summarize_distribution(values: List[float]) -> Dict[str, float]:
    """Return robust summary stats for a numeric list; ignores NaNs."""
    arr = pd.Series(values, dtype=float)
    arr = arr[~arr.isna()]
    if arr.empty:
        return {"count": 0}
    return {
        "count": int(arr.size),
        "min": float(arr.min()),
        "p25": float(arr.quantile(0.25)),
        "median": float(arr.median()),
        "p75": float(arr.quantile(0.75)),
        "p90": float(arr.quantile(0.90)),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
    }


def _build_osm_indexes(all_osm_nodes: Dict[Tuple[float, float], dict]) -> Tuple[Dict[str, List[dict]], Dict[str, dict]]:
    """Construct helper indexes for OSM nodes.
    Returns:
      - osm_by_uic: uic_ref -> [node]
      - osm_by_id: node_id -> node
    """
    osm_by_uic: Dict[str, List[dict]] = defaultdict(list)
    osm_by_id: Dict[str, dict] = {}
    for node in all_osm_nodes.values():
        node_id = str(node.get('node_id'))
        osm_by_id[node_id] = node
        uic_ref = node.get('tags', {}).get('uic_ref')
        if uic_ref:
            osm_by_uic[_safe_int_str(uic_ref)].append(node)
    return osm_by_uic, osm_by_id


def _load_inputs(
    atlas_csv: str = "data/raw/stops_ATLAS.csv",
    osm_xml: str = "data/raw/osm_data.xml",
    unified_csv: str = "data/processed/atlas_routes_unified.csv",
    osm_routes_csv: str = "data/processed/osm_nodes_with_routes.csv",
):
    missing = [p for p in [atlas_csv, osm_xml] if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"Missing required input files: {missing}. Run get_atlas_data.py and get_osm_data.py first."
        )

    logger.info("Loading ATLAS and OSM inputs...")
    atlas_df = pd.read_csv(atlas_csv, sep=';')
    osm_nodes, _, _ = parse_osm_xml(osm_xml)

    gtfs_df = None
    hrdf_df = None
    if os.path.exists(unified_csv):
        unified_df = pd.read_csv(unified_csv)
        # Extract GTFS data
        gtfs_data = unified_df[unified_df['source'] == 'gtfs']
        if not gtfs_data.empty:
            gtfs_df = gtfs_data.copy()
        
        # Extract HRDF data
        hrdf_data = unified_df[unified_df['source'] == 'hrdf']
        if not hrdf_data.empty:
            hrdf_df = hrdf_data.copy()
    else:
        logger.warning(f"Unified routes file not found at {unified_csv}; route analyses will be skipped.")

    osm_routes_df = None
    if os.path.exists(osm_routes_csv):
        osm_routes_df = pd.read_csv(osm_routes_csv)
    else:
        logger.warning(f"OSM routes file not found at {osm_routes_csv}; GTFS-OSM compatibility will be limited.")

    return atlas_df, osm_nodes, gtfs_df, hrdf_df, osm_routes_df


def analyze_coverage(atlas_df: pd.DataFrame, gtfs_df: Optional[pd.DataFrame], hrdf_df: Optional[pd.DataFrame]) -> Dict:
    """Dataset coverage over ATLAS sloids and per-sloid richness."""
    total_sloids = int(atlas_df['sloid'].nunique())
    result = {"total_atlas_sloids": total_sloids}

    if gtfs_df is not None and not gtfs_df.empty:
        sloids_gtfs = int(gtfs_df['sloid'].nunique())
        routes_per_sloid = (
            gtfs_df.groupby('sloid')[['route_id']]
            .count()['route_id']
            .astype(int)
            .tolist()
        )
        result.update({
            "gtfs_sloids": sloids_gtfs,
            "gtfs_sloids_pct": sloids_gtfs / total_sloids if total_sloids else math.nan,
            "gtfs_routes_per_sloid_summary": _summarize_distribution(routes_per_sloid),
        })
    else:
        result.update({"gtfs_sloids": 0, "gtfs_sloids_pct": 0.0, "gtfs_routes_per_sloid_summary": {"count": 0}})

    if hrdf_df is not None and not hrdf_df.empty:
        sloids_hrdf = int(hrdf_df['sloid'].nunique())
        dirs_per_sloid = (
            hrdf_df.groupby('sloid')[['direction_name']]
            .count()['direction_name']
            .astype(int)
            .tolist()
        )
        result.update({
            "hrdf_sloids": sloids_hrdf,
            "hrdf_sloids_pct": sloids_hrdf / total_sloids if total_sloids else math.nan,
            "hrdf_directions_per_sloid_summary": _summarize_distribution(dirs_per_sloid),
        })
    else:
        result.update({"hrdf_sloids": 0, "hrdf_sloids_pct": 0.0, "hrdf_directions_per_sloid_summary": {"count": 0}})

    if gtfs_df is not None and hrdf_df is not None and not gtfs_df.empty and not hrdf_df.empty:
        inter = len(set(gtfs_df['sloid'].unique()).intersection(set(hrdf_df['sloid'].unique())))
        result.update({
            "gtfs_hrdf_intersection_sloids": int(inter),
            "gtfs_only_sloids": int(gtfs_df['sloid'].nunique() - inter),
            "hrdf_only_sloids": int(hrdf_df['sloid'].nunique() - inter),
        })
    else:
        result.update({
            "gtfs_hrdf_intersection_sloids": 0,
            "gtfs_only_sloids": 0,
            "hrdf_only_sloids": 0,
        })

    return result


def analyze_internal_compatibility(gtfs_df: Optional[pd.DataFrame], hrdf_df: Optional[pd.DataFrame]) -> Dict:
    """Compatibility of direction strings between GTFS and HRDF at the sloid level using Jaccard."""
    if gtfs_df is None or hrdf_df is None or gtfs_df.empty or hrdf_df.empty:
        return {"jaccard": {"count": 0}}

    gtfs_dir_by_sloid: Dict[str, Set[str]] = (
        gtfs_df.groupby('sloid')['direction']
        .apply(_series_to_set)
        .to_dict()
    )
    hrdf_dir_by_sloid: Dict[str, Set[str]] = (
        hrdf_df.groupby('sloid')['direction_name']
        .apply(_series_to_set)
        .to_dict()
    )

    common_sloids = set(gtfs_dir_by_sloid.keys()).intersection(hrdf_dir_by_sloid.keys())
    jaccards = []
    non_empty_intersection = 0
    perfect_match = 0
    for s in common_sloids:
        j = _jaccard(gtfs_dir_by_sloid.get(s, set()), hrdf_dir_by_sloid.get(s, set()))
        if not math.isnan(j):
            jaccards.append(j)
            if j > 0:
                non_empty_intersection += 1
            if j == 1.0:
                perfect_match += 1

    summary = _summarize_distribution(jaccards)
    summary.update({
        "non_empty_intersection_pct": (non_empty_intersection / len(common_sloids)) if common_sloids else math.nan,
        "perfect_match_pct": (perfect_match / len(common_sloids)) if common_sloids else math.nan,
        "sloids_evaluated": len(common_sloids),
    })

    return {"jaccard": summary}


def analyze_osm_compatibility_gtfs(
    atlas_df: pd.DataFrame,
    gtfs_df: Optional[pd.DataFrame],
    osm_routes_df: Optional[pd.DataFrame],
    osm_by_id: Dict[str, dict],
    max_distance_m: float = 50.0,
) -> Dict:
    """Measure GTFS-to-OSM compatibility via (route_id, direction_id) keys.
    We compute per-sloid candidate OSM nodes globally and within a distance threshold, then summarize counts and cardinalities.
    """
    if gtfs_df is None or gtfs_df.empty or osm_routes_df is None or osm_routes_df.empty:
        return {"summary": {"sloids_with_candidates_global": 0, "sloids_with_candidates_within_50m": 0}}

    # Normalize direction_id to string in both
    gtfs_df = gtfs_df.copy()
    gtfs_df['direction_id'] = gtfs_df['direction_id'].apply(lambda x: None if pd.isna(x) else int(x))
    gtfs_df['direction_id'] = gtfs_df['direction_id'].apply(lambda x: "0" if x == 0 else ("1" if x == 1 else None))

    osm_routes_df = osm_routes_df.copy()
    # Expand NaN direction_id to both directions to mirror matching behavior
    expanded_rows = []
    for r in osm_routes_df.itertuples(index=False):
        node_id = str(getattr(r, 'node_id')) if not pd.isna(getattr(r, 'node_id')) else None
        if not node_id:
            continue
        route_id = getattr(r, 'gtfs_route_id') if hasattr(r, 'gtfs_route_id') else getattr(r, 'route_id', None)
        route_id = str(route_id).strip() if pd.notna(route_id) else None
        if not route_id:
            continue
        dir_val = getattr(r, 'direction_id', None)
        if pd.isna(dir_val):
            for d in ("0", "1"):
                expanded_rows.append((node_id, route_id, d))
        else:
            d = str(int(float(dir_val)))
            expanded_rows.append((node_id, route_id, d))
    if not expanded_rows:
        return {"summary": {"sloids_with_candidates_global": 0, "sloids_with_candidates_within_50m": 0}}
    osm_key_to_nodes: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for node_id, route_id, d in expanded_rows:
        osm_key_to_nodes[(route_id, d)].add(node_id)

    # Build ATLAS per-sloid GTFS key set
    gtfs_keys_by_sloid: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for r in gtfs_df[['sloid', 'route_id', 'direction_id']].dropna(subset=['route_id']).itertuples(index=False):
        sloid = str(getattr(r, 'sloid'))
        route_id = str(getattr(r, 'route_id')).strip()
        d = getattr(r, 'direction_id')
        if d is None:
            # If direction is None in ATLAS side, consider both possibilities
            gtfs_keys_by_sloid[sloid].add((route_id, "0"))
            gtfs_keys_by_sloid[sloid].add((route_id, "1"))
        else:
            gtfs_keys_by_sloid[sloid].add((route_id, str(d)))

    atlas_by_sloid = {str(r.sloid): (float(r.wgs84North), float(r.wgs84East)) for r in atlas_df[['sloid', 'wgs84North', 'wgs84East']].itertuples(index=False)}

    # Compute candidates per sloid
    sloid_to_global_candidates: Dict[str, Set[str]] = {}
    sloid_to_near_candidates: Dict[str, List[Tuple[str, float]]] = {}
    for sloid, keys in gtfs_keys_by_sloid.items():
        candidate_nodes: Set[str] = set()
        for k in keys:
            candidate_nodes |= osm_key_to_nodes.get(k, set())
        if candidate_nodes:
            sloid_to_global_candidates[sloid] = candidate_nodes
            # Distance filter
            if sloid in atlas_by_sloid:
                csv_lat, csv_lon = atlas_by_sloid[sloid]
                near: List[Tuple[str, float]] = []
                for nid in candidate_nodes:
                    node = osm_by_id.get(str(nid))
                    if not node:
                        continue
                    d = haversine_distance(csv_lat, csv_lon, node['lat'], node['lon'])
                    if d is not None and d <= max_distance_m:
                        near.append((str(nid), float(d)))
                if near:
                    # Keep sorted by distance
                    near.sort(key=lambda x: x[1])
                    sloid_to_near_candidates[sloid] = near

    sloids_global = set(sloid_to_global_candidates.keys())
    sloids_near = set(sloid_to_near_candidates.keys())

    # Greedy best assignment for near candidates (choose closest per sloid)
    assignments: Dict[str, str] = {}
    used_nodes: Set[str] = set()
    distances: List[float] = []
    for sloid in sorted(sloids_near):
        best = None
        for nid, dist in sloid_to_near_candidates[sloid]:
            if nid not in used_nodes:
                best = (nid, dist)
                break
        if best is not None:
            assignments[sloid] = best[0]
            used_nodes.add(best[0])
            distances.append(best[1])

    # Cardinalities
    osm_to_sloids = defaultdict(set)
    for s, nid in assignments.items():
        osm_to_sloids[nid].add(s)
    one_to_one = sum(1 for s, nid in assignments.items() if len(osm_to_sloids[nid]) == 1)
    many_to_one = sum(1 for nid, sloids in osm_to_sloids.items() if len(sloids) > 1)

    return {
        "summary": {
            "sloids_with_candidates_global": int(len(sloids_global)),
            "sloids_with_candidates_within_50m": int(len(sloids_near)),
            "unique_assignments": int(len(assignments)),
            "distance_summary": _summarize_distribution(distances),
            "one_to_one_sloid_osm": int(one_to_one),
            "many_to_one_osm": int(many_to_one),
        }
    }


def analyze_osm_compatibility_hrdf(
    atlas_df: pd.DataFrame,
    hrdf_df: Optional[pd.DataFrame],
    osm_nodes: Dict[Tuple[float, float], dict],
    osm_name_dirs: Dict[str, Set[str]],
    osm_uic_dirs: Dict[str, Set[str]],
    max_distance_m: float = 50.0,
) -> Dict:
    """Measure HRDF-to-OSM compatibility via shared direction strings and same UIC."""
    if hrdf_df is None or hrdf_df.empty:
        return {"summary": {"sloids_with_candidates_global": 0, "sloids_with_candidates_within_50m": 0}}

    osm_by_uic, osm_by_id = _build_osm_indexes(osm_nodes)

    # Build atlas direction maps
    atlas_name_dirs: Dict[str, Set[str]] = (
        hrdf_df.groupby('sloid')['direction_name']
        .apply(_series_to_set)
        .to_dict()
    )
    atlas_uic_dirs: Dict[str, Set[str]] = (
        hrdf_df.groupby('sloid')['direction_uic']
        .apply(_series_to_set)
        .to_dict()
    )

    sloid_to_global_nodes: Dict[str, Set[str]] = {}
    sloid_to_near_nodes: Dict[str, List[Tuple[str, float]]] = {}

    # Map sloid -> uic number
    sloid_to_uic = {str(r.sloid): _safe_int_str(r.number) for r in atlas_df[['sloid', 'number']].itertuples(index=False)}
    sloid_to_coord = {str(r.sloid): (float(r.wgs84North), float(r.wgs84East)) for r in atlas_df[['sloid', 'wgs84North', 'wgs84East']].itertuples(index=False)}

    for sloid, uic in sloid_to_uic.items():
        if not uic:
            continue
        atlas_names = atlas_name_dirs.get(sloid, set())
        atlas_uics = atlas_uic_dirs.get(sloid, set())
        if not atlas_names and not atlas_uics:
            continue
        candidates = []
        for node in osm_by_uic.get(uic, []):
            nid = str(node['node_id'])
            name_dirs = osm_name_dirs.get(nid, set())
            uic_dirs = osm_uic_dirs.get(nid, set())
            if atlas_names.intersection(name_dirs) or atlas_uics.intersection(uic_dirs):
                candidates.append(node)
        if candidates:
            sloid_to_global_nodes[sloid] = set(str(c['node_id']) for c in candidates)
            if sloid in sloid_to_coord:
                csv_lat, csv_lon = sloid_to_coord[sloid]
                near: List[Tuple[str, float]] = []
                for node in candidates:
                    d = haversine_distance(csv_lat, csv_lon, node['lat'], node['lon'])
                    if d is not None and d <= max_distance_m:
                        near.append((str(node['node_id']), float(d)))
                if near:
                    near.sort(key=lambda x: x[1])
                    sloid_to_near_nodes[sloid] = near

    sloids_global = set(sloid_to_global_nodes.keys())
    sloids_near = set(sloid_to_near_nodes.keys())

    # Greedy closest assignment
    assignments: Dict[str, str] = {}
    used_nodes: Set[str] = set()
    distances: List[float] = []
    for sloid in sorted(sloids_near):
        best = None
        for nid, dist in sloid_to_near_nodes[sloid]:
            if nid not in used_nodes:
                best = (nid, dist)
                break
        if best is not None:
            assignments[sloid] = best[0]
            used_nodes.add(best[0])
            distances.append(best[1])

    osm_to_sloids = defaultdict(set)
    for s, nid in assignments.items():
        osm_to_sloids[nid].add(s)
    one_to_one = sum(1 for s, nid in assignments.items() if len(osm_to_sloids[nid]) == 1)
    many_to_one = sum(1 for nid, sloids in osm_to_sloids.items() if len(sloids) > 1)

    return {
        "summary": {
            "sloids_with_candidates_global": int(len(sloids_global)),
            "sloids_with_candidates_within_50m": int(len(sloids_near)),
            "unique_assignments": int(len(assignments)),
            "distance_summary": _summarize_distribution(distances),
            "one_to_one_sloid_osm": int(one_to_one),
            "many_to_one_osm": int(many_to_one),
        }
    }


def analyze_actual_matching(
    atlas_df: pd.DataFrame,
    osm_nodes: Dict[Tuple[float, float], dict],
    osm_xml_path: str,
    max_distance_m: float = 50.0,
) -> Dict:
    """Run the actual route_matching orchestrator for pure GTFS and pure HRDF strategies and summarize results."""
    logger.info("Running GTFS-only matching (actual)...")
    # NOTE: Old route_matching with strategy parameter is deprecated. Use unified approach instead.
    gtfs_matches = []  # route_matching(atlas_df, osm_nodes, osm_xml_file=osm_xml_path, max_distance=max_distance_m, strategy='gtfs')
    logger.info("Running HRDF-only matching (actual)...")
    hrdf_matches = []  # route_matching(atlas_df, osm_nodes, osm_xml_file=osm_xml_path, max_distance=max_distance_m, strategy='hrdf')

    def _cardinality(matches: List[dict]) -> Dict[str, int]:
        sloid_to_osm = defaultdict(set)
        osm_to_sloid = defaultdict(set)
        for m in matches:
            sloid_to_osm[str(m['sloid'])].add(str(m['osm_node_id']))
            osm_to_sloid[str(m['osm_node_id'])].add(str(m['sloid']))
        one_to_one = sum(1 for s, osms in sloid_to_osm.items() if len(osms) == 1 and len(osm_to_sloid[list(osms)[0]]) == 1)
        one_to_many = sum(1 for s, osms in sloid_to_osm.items() if len(osms) > 1)
        many_to_one = sum(1 for o, sloids in osm_to_sloid.items() if len(sloids) > 1)
        return {
            "one_to_one": int(one_to_one),
            "one_to_many": int(one_to_many),
            "many_to_one": int(many_to_one),
        }

    def _distance_stats(matches: List[dict]) -> Dict[str, float]:
        distances = [m.get('distance_m') for m in matches if m.get('distance_m') is not None]
        return _summarize_distribution(distances)

    gtfs_summary = {
        "matches": int(len(gtfs_matches)),
        "unique_sloids": int(len({str(m['sloid']) for m in gtfs_matches})),
        "unique_osm_nodes": int(len({str(m['osm_node_id']) for m in gtfs_matches})),
        "cardinality": _cardinality(gtfs_matches),
        "distance_summary": _distance_stats(gtfs_matches),
    }
    hrdf_summary = {
        "matches": int(len(hrdf_matches)),
        "unique_sloids": int(len({str(m['sloid']) for m in hrdf_matches})),
        "unique_osm_nodes": int(len({str(m['osm_node_id']) for m in hrdf_matches})),
        "cardinality": _cardinality(hrdf_matches),
        "distance_summary": _distance_stats(hrdf_matches),
    }

    # Conflicts on sloids matched by both strategies
    gtfs_by_sloid = {str(m['sloid']): m for m in gtfs_matches}
    hrdf_by_sloid = {str(m['sloid']): m for m in hrdf_matches}
    common_sloids = set(gtfs_by_sloid.keys()).intersection(hrdf_by_sloid.keys())
    conflicts = []
    for s in common_sloids:
        if str(gtfs_by_sloid[s]['osm_node_id']) != str(hrdf_by_sloid[s]['osm_node_id']):
            conflicts.append(s)
    conflict_rate = len(conflicts) / len(common_sloids) if common_sloids else math.nan

    return {
        "gtfs_only": gtfs_summary,
        "hrdf_only": hrdf_summary,
        "common_sloids": int(len(common_sloids)),
        "conflicting_assignments": int(len(conflicts)),
        "conflict_rate": conflict_rate,
    }


def maybe_plot_jaccard_hist(jaccard_values: List[float], out_path: str) -> None:
    if plt is None or not jaccard_values:
        return
    arr = [v for v in jaccard_values if not (v is None or math.isnan(v))]
    if not arr:
        return
    plt.figure(figsize=(7, 4))
    plt.hist(arr, bins=21, range=(0, 1), color='#3b82f6', edgecolor='white')
    plt.title('GTFS vs HRDF direction-name Jaccard per sloid')
    plt.xlabel('Jaccard index')
    plt.ylabel('Count of sloids')
    plt.tight_layout()
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        plt.savefig(out_path, dpi=150)
        logger.info(f"Saved Jaccard histogram to {out_path}")
    except Exception as e:
        logger.warning(f"Could not save plot to {out_path}: {e}")
    finally:
        plt.close()


def main():
    atlas_df, osm_nodes, gtfs_df, hrdf_df, osm_routes_df = _load_inputs()

    # Coverage
    coverage = analyze_coverage(atlas_df, gtfs_df, hrdf_df)
    logger.info("=== COVERAGE OVER ATLAS SLOIDS ===")
    logger.info(json.dumps(coverage, indent=2))

    # Internal compatibility between GTFS and HRDF direction-name strings
    internal = analyze_internal_compatibility(gtfs_df, hrdf_df)
    logger.info("=== INTERNAL COMPATIBILITY (GTFS vs HRDF direction names) ===")
    logger.info(json.dumps(internal, indent=2))

    # Optionally plot distribution of per-sloid Jaccard if both datasets available
    if gtfs_df is not None and hrdf_df is not None and not gtfs_df.empty and not hrdf_df.empty:
        gtfs_dir_by_sloid = gtfs_df.groupby('sloid')['direction'].apply(_series_to_set).to_dict()
        hrdf_dir_by_sloid = hrdf_df.groupby('sloid')['direction_name'].apply(_series_to_set).to_dict()
        common = set(gtfs_dir_by_sloid.keys()).intersection(hrdf_dir_by_sloid.keys())
        jvals = []
        for s in common:
            jvals.append(_jaccard(gtfs_dir_by_sloid.get(s, set()), hrdf_dir_by_sloid.get(s, set())))
        maybe_plot_jaccard_hist(jvals, out_path='memoire/figures/plots/gtfs_hrdf_jaccard.png')

    # OSM compatibility (theoretical) for GTFS
    osm_by_uic, osm_by_id = _build_osm_indexes(osm_nodes)
    gtfs_osm_comp = analyze_osm_compatibility_gtfs(atlas_df, gtfs_df, osm_routes_df, osm_by_id)
    logger.info("=== OSM COMPATIBILITY (GTFS: by route_id, direction_id) ===")
    logger.info(json.dumps(gtfs_osm_comp, indent=2))

    # OSM compatibility (theoretical) for HRDF
    osm_name_dirs, osm_uic_dirs = _get_osm_directions_from_xml("data/raw/osm_data.xml")
    hrdf_osm_comp = analyze_osm_compatibility_hrdf(atlas_df, hrdf_df, osm_nodes, osm_name_dirs, osm_uic_dirs)
    logger.info("=== OSM COMPATIBILITY (HRDF: by shared direction strings + UIC) ===")
    logger.info(json.dumps(hrdf_osm_comp, indent=2))

    # Actual matching via orchestrator (pure GTFS vs pure HRDF)
    actual = analyze_actual_matching(atlas_df, osm_nodes, "data/raw/osm_data.xml")
    logger.info("=== ACTUAL MATCHING (orchestrator) ===")
    logger.info(json.dumps(actual, indent=2))

    # Persist a summary artifact
    summary = {
        "coverage": coverage,
        "internal_compatibility": internal,
        "osm_compatibility": {
            "gtfs": gtfs_osm_comp,
            "hrdf": hrdf_osm_comp,
        },
        "actual_matching": actual,
    }
    os.makedirs("data/processed", exist_ok=True)
    with open("data/processed/gtfs_hrdf_effectiveness_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("Saved summary to data/processed/gtfs_hrdf_effectiveness_summary.json")

    # Human-readable console report
    print("\n===== GTFS vs HRDF — EFFECTIVENESS AND COMPATIBILITY REPORT =====")
    print(f"ATLAS sloids: {coverage['total_atlas_sloids']}")
    print(f"GTFS coverage: {coverage.get('gtfs_sloids', 0)} sloids ({coverage.get('gtfs_sloids_pct', 0.0):.1%})")
    print(f"HRDF coverage: {coverage.get('hrdf_sloids', 0)} sloids ({coverage.get('hrdf_sloids_pct', 0.0):.1%})")
    if 'gtfs_hrdf_intersection_sloids' in coverage:
        print(f"Intersection: {coverage['gtfs_hrdf_intersection_sloids']} sloids; GTFS-only: {coverage['gtfs_only_sloids']}; HRDF-only: {coverage['hrdf_only_sloids']}")

    if internal.get('jaccard', {}).get('count', 0) > 0:
        j = internal['jaccard']
        print("\n--- Direction-name compatibility (GTFS vs HRDF) across common sloids ---")
        print(f"Evaluated: {j['sloids_evaluated']} sloids; median Jaccard={j['median']:.3f}; perfect={j['perfect_match_pct']:.1%}; overlap>0={j['non_empty_intersection_pct']:.1%}")

    print("\n--- OSM compatibility (theoretical) ---")
    g = gtfs_osm_comp['summary']
    h = hrdf_osm_comp['summary']
    print(f"GTFS: sloids with any OSM candidates (global): {g['sloids_with_candidates_global']}")
    print(f"GTFS: sloids with candidates within 50m: {g['sloids_with_candidates_within_50m']} (unique greedy assignments: {g['unique_assignments']})")
    if g['distance_summary'].get('count', 0) > 0:
        print(f"  distance median={g['distance_summary']['median']:.2f} m; p90={g['distance_summary']['p90']:.2f} m")
    print(f"HRDF: sloids with any OSM candidates (global): {h['sloids_with_candidates_global']}")
    print(f"HRDF: sloids with candidates within 50m: {h['sloids_with_candidates_within_50m']} (unique greedy assignments: {h['unique_assignments']})")
    if h['distance_summary'].get('count', 0) > 0:
        print(f"  distance median={h['distance_summary']['median']:.2f} m; p90={h['distance_summary']['p90']:.2f} m")

    print("\n--- Actual matching (orchestrator) ---")
    a = actual
    print(f"GTFS: matches={a['gtfs_only']['matches']}; sloids={a['gtfs_only']['unique_sloids']}; osm_nodes={a['gtfs_only']['unique_osm_nodes']}")
    if a['gtfs_only']['distance_summary'].get('count', 0) > 0:
        print(f"  median distance={a['gtfs_only']['distance_summary']['median']:.2f} m; p90={a['gtfs_only']['distance_summary']['p90']:.2f} m")
    print(f"HRDF: matches={a['hrdf_only']['matches']}; sloids={a['hrdf_only']['unique_sloids']}; osm_nodes={a['hrdf_only']['unique_osm_nodes']}")
    if a['hrdf_only']['distance_summary'].get('count', 0) > 0:
        print(f"  median distance={a['hrdf_only']['distance_summary']['median']:.2f} m; p90={a['hrdf_only']['distance_summary']['p90']:.2f} m")
    if not math.isnan(a.get('conflict_rate', math.nan)):
        print(f"Overlap sloids matched by both: {a['common_sloids']}; conflicting assignments: {a['conflicting_assignments']} ({a['conflict_rate']:.1%})")


if __name__ == "__main__":
    main()


