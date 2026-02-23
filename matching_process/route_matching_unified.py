"""
Route-based matching predicate.

Matches ATLAS stops to OSM nodes by comparing GTFS / HRDF route tokens
derived from ``atlas_routes_unified.csv`` and ``osm_nodes_with_routes.csv``.
"""
import logging
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

import pandas as pd

from matching_process.pipeline import MatchingContext
from matching_process.match_record import create_match_record, extract_atlas_fields
from matching_process.utils import haversine_distance
from matching_process.spatial_index import (
    build_kdtree_from_nodes, meters_to_unit_chord_radius, lat_lon_to_xyz_list, to_xyz,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loaders (unchanged logic, cleaned up)
# ---------------------------------------------------------------------------

def _normalize_route_id_for_matching(route_id):
    if not route_id:
        return None
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def _normalize_direction_id(val):
    try:
        if pd.isna(val):
            return None
        return str(int(float(val)))
    except Exception:
        return None


def _get_osm_directions_from_xml(xml_file):
    """Extract per-node direction strings from route relations in the OSM XML."""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception:
        return defaultdict(set), defaultdict(set)

    node_id_to_name: dict[str, str] = {}
    node_id_to_uic: dict[str, str] = {}
    for node in root.findall('.//node'):
        nid = node.get('id')
        for tag in node.findall('./tag'):
            k = tag.get('k')
            if k == 'name':
                node_id_to_name[nid] = tag.get('v')
            elif k == 'uic_ref':
                node_id_to_uic[nid] = tag.get('v')

    name_dirs: dict[str, set] = defaultdict(set)
    uic_dirs: dict[str, set] = defaultdict(set)

    for relation in root.findall('.//relation'):
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

    return name_dirs, uic_dirs


def _load_unified_routes(path: str = 'data/processed/atlas_routes_unified.csv'):
    by_sloid: dict[str, dict[str, list]] = defaultdict(lambda: {'gtfs': [], 'hrdf': []})
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
    except FileNotFoundError:
        return by_sloid
    except Exception as exc:
        logger.warning(f"Error loading unified routes: {exc}")
        return by_sloid

    for _, row in df.iterrows():
        sloid = str(row['sloid']) if pd.notna(row['sloid']) else None
        if not sloid:
            continue
        src = str(row.get('source', ''))
        entry = {
            'route_id': row.get('route_id') if pd.notna(row.get('route_id')) else None,
            'route_id_normalized': row.get('route_id_normalized') if pd.notna(row.get('route_id_normalized')) else None,
            'line_name': row.get('line_name') if pd.notna(row.get('line_name')) else None,
            'direction_id': _normalize_direction_id(row.get('direction_id')),
            'direction_name': row.get('direction_name') if pd.notna(row.get('direction_name')) else None,
            'direction_uic': row.get('direction_uic') if pd.notna(row.get('direction_uic')) else None,
        }
        if src == 'gtfs':
            by_sloid[sloid]['gtfs'].append(entry)
        elif src == 'hrdf':
            by_sloid[sloid]['hrdf'].append(entry)
    return by_sloid


def _load_osm_routes(csv_path: str = 'data/processed/osm_nodes_with_routes.csv'):
    mapping: dict[str, list] = defaultdict(list)

    # Build fallback name → route_id from GTFS routes.txt
    route_name_to_id: dict[str, str] = {}
    gtfs_root = 'data/raw'
    if os.path.isdir(gtfs_root):
        for fname in os.listdir(gtfs_root):
            candidate = os.path.join(gtfs_root, fname, 'routes.txt')
            if fname.startswith('gtfs') and os.path.exists(candidate):
                try:
                    gdf = pd.read_csv(candidate, dtype=str,
                                      usecols=['route_id', 'route_short_name', 'route_long_name'])
                    for _, r in gdf.iterrows():
                        for col in ('route_short_name', 'route_long_name'):
                            if pd.notna(r.get(col)):
                                route_name_to_id[str(r[col]).strip()] = str(r['route_id']).strip()
                except Exception:
                    pass
                break

    try:
        df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    except Exception:
        return mapping

    for _, row in df.iterrows():
        node_id = str(row.get('node_id')) if pd.notna(row.get('node_id')) else None
        if not node_id:
            continue
        direction_id = _normalize_direction_id(row.get('direction_id'))
        route_name = str(row.get('route_name')).strip() if pd.notna(row.get('route_name')) else None
        gtfs_id = str(row.get('gtfs_route_id')).strip() if pd.notna(row.get('gtfs_route_id')) else None
        if not gtfs_id and route_name and route_name in route_name_to_id:
            gtfs_id = route_name_to_id[route_name]
        for did in ([direction_id] if direction_id is not None else ['0', '1']):
            mapping[node_id].append({
                'gtfs_route_id': gtfs_id,
                'direction_id': did,
                'route_name': route_name,
            })
    return mapping


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------

def route_match(ctx: MatchingContext) -> list[dict]:
    """Match ATLAS stops to OSM boundaries strictly by common transit routes/lines."""
    matches: list[dict] = []

    hrdf_routes = _load_unified_routes()
    if not hrdf_routes: # Check if the dictionary is empty
        logger.warning("route_match: Route data unavailable, skipping.")
        return matches

    osm_route_map = _load_osm_routes()
    name_dirs, uic_dirs = _get_osm_directions_from_xml(ctx.osm_xml_file)

    for entry in ctx.atlas.get_unmatched_records():
        sloid = str(entry.get('sloid', ''))
        if not sloid:
            continue

        atlas_routes_data = hrdf_routes.get(sloid, {'gtfs': [], 'hrdf': []})
        if not atlas_routes_data['gtfs'] and not atlas_routes_data['hrdf']:
            continue

        csv_lat = float(entry['wgs84North'])
        csv_lon = float(entry['wgs84East'])

        # Find OSM candidates within max_distance (route matching explicitly ALLOWS station mappings)
        candidates = ctx.osm.query_radius(csv_lat, csv_lon, ctx.max_distance, include_stations=True)
        if not candidates:
            continue
            
        # Join the relations for candidates
        candidate_list = []
        for c, d in candidates:
            node_id = str(c.get('node_id'))
            routes = osm_route_map.get(node_id, [])
            candidate_list.append((c, d, routes))
            
        candidates = candidate_list

        # --- Build token sets for ATLAS stop ---
        gtfs_tokens: set[tuple[str, str]] = set()
        for e in atlas_routes_data['gtfs']:
            if e.get('route_id') and e.get('direction_id'):
                gtfs_tokens.add((e['route_id'], e['direction_id']))
            if e.get('route_id_normalized') and e.get('direction_id'):
                gtfs_tokens.add((e['route_id_normalized'], e['direction_id']))

        hrdf_tokens: set[tuple[str, str]] = set()
        for e in atlas_routes_data['hrdf']:
            if e.get('line_name') and e.get('direction_uic'):
                hrdf_tokens.add((e['line_name'], e['direction_uic']))

        atlas_dir_names: set[str] = set()
        for e in atlas_routes_data['hrdf'] + atlas_routes_data['gtfs']:
            dn = e.get('direction_name')
            if dn:
                atlas_dir_names.add(dn)

        matched_node = None
        matched_dist = None
        match_source = None
        match_evidence = None

        # P1: GTFS tokens
        if gtfs_tokens:
            for node, dist, node_routes in candidates:
                node_tokens: set[tuple[str, str]] = set()
                for r in node_routes:
                    rid = r.get('gtfs_route_id')
                    did = r.get('direction_id', '0')
                    if rid:
                        node_tokens.add((rid, did))
                        norm = _normalize_route_id_for_matching(rid)
                        if norm:
                            node_tokens.add((norm, did))
                if gtfs_tokens & node_tokens:
                    matched_node, matched_dist = node, dist
                    match_source, match_evidence = 'gtfs', 'gtfs_tokens'
                    break

        # P2: HRDF UIC direction
        if matched_node is None and hrdf_tokens:
            for node, dist, _ in candidates:
                nid = str(node['node_id'])
                for _, dir_uic in hrdf_tokens:
                    if dir_uic in uic_dirs.get(nid, set()):
                        matched_node, matched_dist = node, dist
                        match_source, match_evidence = 'hrdf', 'hrdf_uic'
                        break
                if matched_node:
                    break

        # P3: name-based direction fallback
        if matched_node is None:
            dir_names: set[str] = set()
            for e in atlas_routes_data['hrdf'] + atlas_routes_data['gtfs']:
                dn = e.get('direction_name')
                if dn:
                    dir_names.add(dn)
            if dir_names:
                for node, dist, _ in candidates:
                    nid = str(node['node_id'])
                    if any(dn in name_dirs.get(nid, set()) for dn in dir_names):
                        matched_node, matched_dist = node, dist
                        src = 'hrdf' if any(
                            e.get('direction_name') in dir_names
                            for e in atlas_routes_data['hrdf']
                        ) else 'gtfs'
                        match_source, match_evidence = src, 'direction_name'
                        break

        if matched_node is not None:
            matches.append(create_match_record(
                sloid=sloid,
                csv_lat=csv_lat,
                csv_lon=csv_lon,
                osm_node=matched_node,
                distance_m=matched_dist,
                match_type=f"route_unified_{match_source}",
                matching_notes=match_evidence,
                number=entry.get('number'),
                **extract_atlas_fields(entry),
            ))
            ctx.osm.mark_used(str(matched_node['node_id']))

    return matches
