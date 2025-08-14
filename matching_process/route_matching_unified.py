import pandas as pd
from collections import defaultdict
import logging
import os
import xml.etree.ElementTree as ET
from .utils import haversine_distance

logger = logging.getLogger(__name__)


def _normalize_route_id_for_matching(route_id):
    if not route_id:
        return None
    import re
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def _normalize_direction_id(direction_val):
    try:
        if pd.isna(direction_val):
            return None
        return str(int(float(direction_val)))
    except Exception:
        return None


def _get_osm_directions_from_xml(xml_file):
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception:
        return defaultdict(set), defaultdict(set)

    node_id_to_name = {}
    node_id_to_uic = {}
    for node in root.findall('.//node'):
        node_id = node.get('id')
        for tag in node.findall('./tag'):
            if tag.get('k') == 'name':
                node_id_to_name[node_id] = tag.get('v')
            elif tag.get('k') == 'uic_ref':
                node_id_to_uic[node_id] = tag.get('v')

    osm_name_directions_map = defaultdict(set)
    osm_uic_directions_map = defaultdict(set)
    for relation in root.findall('.//relation'):
        if any(tag.get('k') == 'type' and tag.get('v') == 'route' for tag in relation.findall('./tag')):
            member_nodes = [member.get('ref') for member in relation.findall("./member[@type='node']")]
            if len(member_nodes) >= 2:
                first_node_id, last_node_id = member_nodes[0], member_nodes[-1]
                first_name, last_name = node_id_to_name.get(first_node_id), node_id_to_name.get(last_node_id)
                if first_name and last_name:
                    direction_string = f"{first_name} → {last_name}"
                    for node_id in member_nodes:
                        osm_name_directions_map[node_id].add(direction_string)
                first_uic, last_uic = node_id_to_uic.get(first_node_id), node_id_to_uic.get(last_node_id)
                if first_uic and last_uic:
                    direction_string = f"{first_uic} → {last_uic}"
                    for node_id in member_nodes:
                        osm_uic_directions_map[node_id].add(direction_string)
    return osm_name_directions_map, osm_uic_directions_map


def _load_unified_routes(unified_csv_path: str = 'data/processed/atlas_routes_unified.csv'):
    df = pd.read_csv(unified_csv_path)
    # Build per-sloid indexes
    by_sloid = defaultdict(lambda: {
        'gtfs': [],
        'hrdf': []
    })
    for _, row in df.iterrows():
        sloid = str(row['sloid']) if pd.notna(row['sloid']) else None
        if not sloid:
            continue
        src = str(row.get('source'))
        entry = {
            'route_id': row.get('route_id') if pd.notna(row.get('route_id')) else None,
            'route_id_normalized': row.get('route_id_normalized') if pd.notna(row.get('route_id_normalized')) else None,
            'route_name_short': row.get('route_name_short') if pd.notna(row.get('route_name_short')) else None,
            'route_name_long': row.get('route_name_long') if pd.notna(row.get('route_name_long')) else None,
            'line_name': row.get('line_name') if pd.notna(row.get('line_name')) else None,
            'direction_id': _normalize_direction_id(row.get('direction_id')),
            'direction_name': row.get('direction_name') if pd.notna(row.get('direction_name')) else None,
            'direction_uic': row.get('direction_uic') if pd.notna(row.get('direction_uic')) else None,
            'evidence': row.get('evidence') if pd.notna(row.get('evidence')) else None,
            'as_of': row.get('as_of') if pd.notna(row.get('as_of')) else None,
        }
        if src == 'gtfs':
            by_sloid[sloid]['gtfs'].append(entry)
        elif src == 'hrdf':
            by_sloid[sloid]['hrdf'].append(entry)
    return by_sloid


def _load_osm_routes(osm_routes_csv: str = 'data/processed/osm_nodes_with_routes.csv'):
    mapping = defaultdict(list)
    # Build fallback mapping from GTFS route names to route_id
    route_name_to_id = {}
    gtfs_routes_path = None
    gtfs_root = 'data/raw'
    if os.path.isdir(gtfs_root):
        for fname in os.listdir(gtfs_root):
            candidate = os.path.join(gtfs_root, fname, 'routes.txt')
            if fname.startswith('gtfs') and os.path.exists(candidate):
                gtfs_routes_path = candidate
                break
    if gtfs_routes_path:
        try:
            gtfs_routes_df = pd.read_csv(gtfs_routes_path, dtype=str, usecols=['route_id', 'route_short_name', 'route_long_name'])
            for _, r in gtfs_routes_df.iterrows():
                if pd.notna(r.get('route_short_name')):
                    route_name_to_id[str(r['route_short_name']).strip()] = str(r['route_id']).strip()
                if pd.notna(r.get('route_long_name')):
                    route_name_to_id[str(r['route_long_name']).strip()] = str(r['route_id']).strip()
        except Exception:
            route_name_to_id = {}
    try:
        df = pd.read_csv(osm_routes_csv)
    except Exception:
        return mapping
    # Build tokens per node
    for _, row in df.iterrows():
        node_id = str(row.get('node_id')) if pd.notna(row.get('node_id')) else None
        if not node_id:
            continue
        direction_id = _normalize_direction_id(row.get('direction_id'))
        route_name = str(row.get('route_name')).strip() if pd.notna(row.get('route_name')) else None
        gtfs_route_id = str(row.get('gtfs_route_id')).strip() if pd.notna(row.get('gtfs_route_id')) else None
        if not gtfs_route_id and route_name and route_name in route_name_to_id:
            gtfs_route_id = route_name_to_id[route_name]
        # If direction missing, consider both directions 0 and 1
        directions_to_add = [direction_id] if direction_id is not None else ['0', '1']
        for did in directions_to_add:
            mapping[node_id].append({
                'gtfs_route_id': gtfs_route_id,
                'direction_id': did,
                'route_name': route_name,
            })
    return mapping


def perform_unified_route_matching(unmatched_df, xml_nodes, osm_xml_file, used_osm_nodes, max_distance=50):
    # Load data once
    unified_by_sloid = _load_unified_routes()
    osm_routes = _load_osm_routes()
    osm_name_dirs, osm_uic_dirs = _get_osm_directions_from_xml(osm_xml_file)

    matches = []
    newly_used = set()

    # Build name/UIC direction availability per node
    def node_has_uic_dir(node_id, dir_uic_str):
        return dir_uic_str in osm_uic_dirs.get(node_id, set())

    def node_has_name_dir(node_id, dir_name_str):
        return dir_name_str in osm_name_dirs.get(node_id, set())

    for _, row in unmatched_df.iterrows():
        sloid = str(row['sloid'])
        csv_lat = float(row['wgs84North'])
        csv_lon = float(row['wgs84East'])
        uic_ref = str(row.get('number', '')).strip() if pd.notna(row.get('number')) else ''
        entries = unified_by_sloid.get(sloid, {'gtfs': [], 'hrdf': []})

        # Candidate OSM nodes nearby (limit by distance roughly using all xml_nodes)
        candidates = []
        for (lat, lon), node in xml_nodes.items():
            node_id = str(node['node_id'])
            if node_id in used_osm_nodes or node_id in newly_used:
                continue
            dist = haversine_distance(csv_lat, csv_lon, lat, lon)
            if dist is not None and dist <= max_distance:
                # enrich with route tokens present for node
                candidates.append((node, lat, lon, dist, osm_routes.get(node_id, [])))

        # Priority P1/P2 GTFS, P3 HRDF, P4 name-based HRDF/GTFS
        matched = None
        match_meta = None

        # Build GTFS tokens from entries
        gtfs_tokens = set()
        for e in entries['gtfs']:
            if e.get('route_id') and e.get('direction_id'):
                gtfs_tokens.add((e['route_id'], e['direction_id']))
            if e.get('route_id_normalized') and e.get('direction_id'):
                gtfs_tokens.add((e['route_id_normalized'], e['direction_id']))

        # Build HRDF tokens
        hrdf_tokens = set()
        for e in entries['hrdf']:
            if e.get('line_name') and e.get('direction_uic'):
                hrdf_tokens.add((e['line_name'], e['direction_uic']))

        # Try P1/P2: GTFS tokens
        for node, lat, lon, dist, node_routes in candidates:
            node_id = str(node['node_id'])
            # Derive tokens for node from OSM routes
            node_tokens = set()
            for r in node_routes:
                rid = r.get('gtfs_route_id')
                did = r.get('direction_id') or '0'
                if rid:
                    node_tokens.add((rid, did))
                    rid_norm = _normalize_route_id_for_matching(rid)
                    if rid_norm:
                        node_tokens.add((rid_norm, did))

            # Check intersection
            common = gtfs_tokens.intersection(node_tokens)
            if common:
                matched = node
                match_meta = {
                    'source': 'gtfs',
                    'evidence': 'gtfs_tokens',
                    'route_token': list(common)[0]
                }
                break

        # Try P3: HRDF tokens
        if matched is None and hrdf_tokens:
            for node, lat, lon, dist, node_routes in candidates:
                node_id = str(node['node_id'])
                for token in hrdf_tokens:
                    line_name, dir_uic = token
                    if node_has_uic_dir(node_id, dir_uic):
                        matched = node
                        match_meta = {
                            'source': 'hrdf',
                            'evidence': 'hrdf_uic',
                            'route_token': token
                        }
                        break
                if matched is not None:
                    break

        # Try P4: name-based fallback using direction_name
        if matched is None:
            # Build available direction_name strings from unified
            dir_names = set(e['direction_name'] for e in entries['hrdf'] if e.get('direction_name'))
            dir_names.update(e['direction_name'] for e in entries['gtfs'] if e.get('direction_name'))
            if dir_names:
                for node, lat, lon, dist, node_routes in candidates:
                    node_id = str(node['node_id'])
                    if any(node_has_name_dir(node_id, dn) for dn in dir_names):
                        matched = node
                        match_meta = {
                            'source': 'hrdf' if any(e.get('direction_name') in dir_names for e in entries['hrdf']) else 'gtfs',
                            'evidence': 'direction_name',
                            'route_token': None
                        }
                        break

        if matched is not None:
            osm_node_id = str(matched['node_id'])
            newly_used.add(osm_node_id)
            # Determine distance for matched candidate
            dist = None
            for node, lat, lon, d, _routes in candidates:
                if str(node['node_id']) == osm_node_id:
                    dist = d
                    break
            tags = matched.get('tags', {}) if isinstance(matched.get('tags', {}), dict) else {}
            result = {
                'sloid': sloid,
                'number': row.get('number'),
                'csv_lat': csv_lat,
                'csv_lon': csv_lon,
                'csv_business_org_abbr': row.get('servicePointBusinessOrganisationAbbreviationEn', ''),
                'osm_node_id': osm_node_id,
                'osm_lat': matched['lat'],
                'osm_lon': matched['lon'],
                'distance_m': dist,
                'match_type': f"route_unified_{match_meta['source']}",
                'matching_notes': match_meta['evidence'],
                'osm_uic_ref': tags.get('uic_ref', ''),
                'osm_public_transport': tags.get('public_transport', ''),
                'osm_railway': tags.get('railway', ''),
                'osm_amenity': tags.get('amenity', ''),
                'osm_aerialway': tags.get('aerialway', ''),
                'osm_name': tags.get('name', ''),
                'osm_uic_name': tags.get('uic_name', ''),
                'osm_network': tags.get('network', ''),
                'osm_operator': tags.get('operator', ''),
                'osm_local_ref': matched.get('local_ref')
            }
            matches.append(result)

    return matches, newly_used


