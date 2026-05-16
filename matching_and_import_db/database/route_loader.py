"""Route data loaders for the database import pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from itertools import count
from pathlib import Path
from typing import Any

import pandas as pd

from matching_and_import_db.models import MatchingOutput
from matching_and_import_db.utils.route_id import normalize_route_id


PROCESSED_DIR = Path('data/processed')
_NON_WORD_RE = re.compile(r'[^a-z0-9]+')
_ITINERARY_MATCH_MIN_RATIO = 0.8
_NON_ATLAS_STOP_KEY_PREFIXES = ('gtfs:', 'osm:', 'uic:')


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == '' or text.lower() == 'nan'


def _to_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value).strip()


def _to_int(value: Any, default: int = 0) -> int:
    if _is_missing(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_name(value: Any) -> str | None:
    text = _to_text(value)
    if text is None:
        return None
    normalized = _NON_WORD_RE.sub(' ', text.lower()).strip()
    return normalized or None


def _hash_sequence(values: list[str]) -> str:
    digest = hashlib.sha1('>'.join(values).encode('utf-8')).hexdigest()
    return digest[:16]


def _load_optional_csv(filename: str) -> pd.DataFrame | None:
    path = PROCESSED_DIR / filename
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, dtype=str)
    except Exception as exc:
        print(f"Warning: Failed to load {path}: {exc}")
        return None


def _records(dataframe: pd.DataFrame | None) -> list[dict[str, Any]]:
    if dataframe is None or dataframe.empty:
        return []
    return dataframe.to_dict(orient='records')


def _coord_distance_m(lat_a: float | None, lon_a: float | None, lat_b: float | None, lon_b: float | None) -> float | None:
    if lat_a is None or lon_a is None or lat_b is None or lon_b is None:
        return None
    mean_lat_rad = math.radians((lat_a + lat_b) / 2.0)
    dx = (lon_a - lon_b) * 111_320.0 * math.cos(mean_lat_rad)
    dy = (lat_a - lat_b) * 111_320.0
    return math.hypot(dx, dy)


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = _to_text(value)
        if text is not None:
            return text
    return None


def _parse_uic_from_gtfs_stop_id(stop_id: str | None) -> str | None:
    text = _to_text(stop_id)
    if text is None:
        return None
    prefix = text.split(':', 1)[0]
    return prefix if prefix.isdigit() else None


def load_all_route_data() -> dict[str, pd.DataFrame]:
    """Load the normalized raw route-product CSVs."""
    filenames = {
        'atlas_line_families': 'atlas_line_families.csv',
        'atlas_itineraries': 'atlas_itineraries.csv',
        'atlas_itinerary_stop_calls': 'atlas_itinerary_stop_calls.csv',
        'osm_route_masters': 'osm_route_masters.csv',
        'osm_route_master_tags': 'osm_route_master_tags.csv',
        'osm_route_master_members': 'osm_route_master_members.csv',
        'osm_route_relations': 'osm_route_relations.csv',
        'osm_route_relation_tags': 'osm_route_relation_tags.csv',
        'osm_route_relation_members': 'osm_route_relation_members.csv',
        'osm_route_relation_stops': 'osm_route_relation_stops.csv',
    }
    data: dict[str, pd.DataFrame] = {}
    for key, filename in filenames.items():
        dataframe = _load_optional_csv(filename)
        if dataframe is not None:
            data[key] = dataframe
    return data


def _build_base_lookups(base_data: MatchingOutput | None, known_sloids: set[str]) -> dict[str, Any]:
    atlas_stop_lookup: dict[str, dict[str, Any]] = {}
    atlas_uic_candidates: dict[str, set[str]] = defaultdict(set)
    osm_node_lookup: dict[str, Any] = {}
    matched_osm_to_sloid: dict[str, str] = {}

    if base_data is None:
        return {
            'atlas_stop_lookup': atlas_stop_lookup,
            'osm_node_lookup': osm_node_lookup,
            'matched_osm_to_sloid': matched_osm_to_sloid,
            'unique_atlas_sloid_by_uic': {},
        }

    def register_atlas_node(node: Any) -> None:
        sloid = _to_text(getattr(node, 'sloid', None))
        if sloid is None:
            return
        atlas_stop_lookup[sloid] = {
            'sloid': sloid,
            'lat': _to_float(getattr(node, 'lat', None)),
            'lon': _to_float(getattr(node, 'lon', None)),
            'uic_ref': _to_text(getattr(node, 'uic_ref', None)),
            'designation': _to_text(getattr(node, 'designation', None)),
            'designation_official': _to_text(getattr(node, 'designation_official', None)),
        }
        if sloid in known_sloids:
            uic_ref = _to_text(getattr(node, 'uic_ref', None))
            if uic_ref is not None:
                atlas_uic_candidates[uic_ref].add(sloid)

    def register_osm_node(node: Any) -> None:
        node_id = _to_text(getattr(node, 'node_id', None))
        if node_id is None:
            return
        osm_node_lookup[node_id] = node

    for match in getattr(base_data, 'matched', []):
        register_atlas_node(match.atlas_node)
        register_osm_node(match.osm_node)
        atlas_sloid = _to_text(match.atlas_node.sloid)
        osm_node_id = _to_text(match.osm_node.node_id)
        if atlas_sloid in known_sloids and osm_node_id is not None:
            matched_osm_to_sloid[osm_node_id] = atlas_sloid

    for atlas_node in getattr(base_data, 'unmatched_atlas', []):
        register_atlas_node(atlas_node)
    for osm_node in getattr(base_data, 'unmatched_osm', []):
        register_osm_node(osm_node)
    for osm_node in getattr(base_data, 'all_osm_nodes', []):
        register_osm_node(osm_node)

    unique_atlas_sloid_by_uic = {
        uic_ref: next(iter(sloids))
        for uic_ref, sloids in atlas_uic_candidates.items()
        if len(sloids) == 1
    }
    return {
        'atlas_stop_lookup': atlas_stop_lookup,
        'osm_node_lookup': osm_node_lookup,
        'matched_osm_to_sloid': matched_osm_to_sloid,
        'unique_atlas_sloid_by_uic': unique_atlas_sloid_by_uic,
    }


def _build_atlas_stop_call_row(
    row: dict[str, Any],
    known_sloids: set[str],
    atlas_stop_lookup: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    resolved_sloid = _to_text(row.get('resolved_sloid') or row.get('sloid'))
    skipped_sloid = False
    if resolved_sloid not in known_sloids:
        skipped_sloid = resolved_sloid is not None
        resolved_sloid = None

    atlas_meta = atlas_stop_lookup.get(resolved_sloid) if resolved_sloid else None
    gtfs_stop_id = _to_text(row.get('gtfs_stop_id') or row.get('stop_id'))
    stop_label = _first_non_empty(
        row.get('stop_label'),
        row.get('stop_name'),
        atlas_meta.get('designation_official') if atlas_meta else None,
        atlas_meta.get('designation') if atlas_meta else None,
        gtfs_stop_id,
    )
    uic_number = _first_non_empty(
        row.get('uic_number'),
        atlas_meta.get('uic_ref') if atlas_meta else None,
        _parse_uic_from_gtfs_stop_id(gtfs_stop_id),
    )
    canonical_stop_key = _first_non_empty(
        row.get('canonical_stop_key'),
        resolved_sloid,
        f'gtfs:{gtfs_stop_id}' if gtfs_stop_id else None,
    )
    stop_lat = _to_float(row.get('stop_lat'))
    stop_lon = _to_float(row.get('stop_lon'))
    if atlas_meta is not None:
        stop_lat = stop_lat if stop_lat is not None else atlas_meta.get('lat')
        stop_lon = stop_lon if stop_lon is not None else atlas_meta.get('lon')

    return {
        'atlas_itinerary_id': _to_text(row.get('atlas_itinerary_id')),
        'stop_sequence': _to_int(row.get('stop_sequence')),
        'gtfs_stop_id': gtfs_stop_id,
        'resolved_sloid': resolved_sloid,
        'resolved_sloid_variants': _to_text(row.get('resolved_sloid_variants') or row.get('sloid_variants')),
        'canonical_stop_key': canonical_stop_key,
        'stop_label': stop_label,
        'uic_number': uic_number,
        'platform_code': _to_text(row.get('platform_code')),
        'stop_lat': stop_lat,
        'stop_lon': stop_lon,
    }, skipped_sloid


def _build_atlas_source_rows(
    all_route_data: dict[str, pd.DataFrame],
    known_sloids: set[str],
    atlas_stop_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    line_family_rows: list[dict[str, Any]] = []
    atlas_line_source = all_route_data.get('atlas_line_families')
    for row in _records(atlas_line_source):
        atlas_line_id = _to_text(row.get('atlas_line_id'))
        if atlas_line_id is None:
            continue
        line_family_rows.append({
            'atlas_line_id': atlas_line_id,
            'route_id_normalized': _first_non_empty(row.get('route_id_normalized'), normalize_route_id(atlas_line_id)),
            'agency_id': _to_text(row.get('agency_id')),
            'route_short_name': _to_text(row.get('route_short_name')),
            'route_long_name': _to_text(row.get('route_long_name')),
            'route_desc': _to_text(row.get('route_desc')),
            'route_type': _to_text(row.get('route_type')),
        })

    itinerary_rows: list[dict[str, Any]] = []
    stop_call_rows: list[dict[str, Any]] = []
    skipped_sloids = 0
    atlas_itineraries_df = all_route_data.get('atlas_itineraries')
    atlas_stop_calls_df = all_route_data.get('atlas_itinerary_stop_calls')
    if atlas_itineraries_df is not None and atlas_stop_calls_df is not None:
        for row in _records(atlas_itineraries_df):
            atlas_itinerary_id = _to_text(row.get('atlas_itinerary_id'))
            atlas_line_id = _to_text(row.get('atlas_line_id'))
            if atlas_itinerary_id is None or atlas_line_id is None:
                continue
            itinerary_rows.append({
                'atlas_itinerary_id': atlas_itinerary_id,
                'atlas_line_id': atlas_line_id,
                'direction_id': _to_text(row.get('direction_id')),
                'representative_headsign': _to_text(row.get('representative_headsign')),
                'direction_label': _to_text(row.get('direction_label')),
                'trip_count': _to_int(row.get('trip_count'), default=0),
                'shape_id': _to_text(row.get('shape_id')),
                'geometry_wkt': _to_text(row.get('geometry_wkt')),
                'headsign_or_pattern_hash': _to_text(row.get('headsign_or_pattern_hash') or row.get('pattern_hash')),
            })
        for row in _records(atlas_stop_calls_df):
            normalized_row, skipped = _build_atlas_stop_call_row(row, known_sloids, atlas_stop_lookup)
            if normalized_row['atlas_itinerary_id'] is None:
                continue
            skipped_sloids += 1 if skipped else 0
            stop_call_rows.append(normalized_row)

    return {
        'atlas_line_families': line_family_rows,
        'atlas_itineraries': itinerary_rows,
        'atlas_itinerary_stop_calls': stop_call_rows,
        'skipped_sloids': skipped_sloids,
    }


def _resolve_osm_stop_fields(node_id: str | None, row: dict[str, Any], lookups: dict[str, Any]) -> dict[str, Any]:
    osm_node_lookup = lookups['osm_node_lookup']
    matched_osm_to_sloid = lookups['matched_osm_to_sloid']
    unique_atlas_sloid_by_uic = lookups['unique_atlas_sloid_by_uic']
    atlas_stop_lookup = lookups['atlas_stop_lookup']

    node = osm_node_lookup.get(node_id) if node_id is not None else None
    uic_ref = _first_non_empty(row.get('uic_ref'), getattr(node, 'uic_ref', None) if node else None)
    canonical_stop_key = matched_osm_to_sloid.get(node_id) if node_id is not None else None
    if canonical_stop_key is None and uic_ref is not None:
        canonical_stop_key = unique_atlas_sloid_by_uic.get(uic_ref)
    if canonical_stop_key is None:
        canonical_stop_key = _to_text(row.get('canonical_stop_key'))
    if canonical_stop_key is None and node_id is not None:
        canonical_stop_key = f'osm:{node_id}'

    atlas_meta = atlas_stop_lookup.get(canonical_stop_key) if canonical_stop_key in atlas_stop_lookup else None
    stop_lat = _to_float(row.get('stop_lat'))
    stop_lon = _to_float(row.get('stop_lon'))
    if stop_lat is None and node is not None:
        stop_lat = _to_float(getattr(node, 'lat', None))
    if stop_lon is None and node is not None:
        stop_lon = _to_float(getattr(node, 'lon', None))
    if atlas_meta is not None:
        stop_lat = stop_lat if stop_lat is not None else atlas_meta.get('lat')
        stop_lon = stop_lon if stop_lon is not None else atlas_meta.get('lon')

    return {
        'canonical_stop_key': canonical_stop_key,
        'stop_label': _first_non_empty(
            row.get('stop_label'),
            getattr(node, 'name', None) if node else None,
            getattr(node, 'uic_name', None) if node else None,
            getattr(node, 'local_ref', None) if node else None,
            node_id,
        ),
        'uic_ref': uic_ref,
        'stop_lat': stop_lat,
        'stop_lon': stop_lon,
    }


def _build_osm_source_rows(all_route_data: dict[str, pd.DataFrame], lookups: dict[str, Any]) -> dict[str, Any]:
    route_master_rows: list[dict[str, Any]] = []
    for row in _records(all_route_data.get('osm_route_masters')):
        route_master_id = _to_text(row.get('route_master_id'))
        if route_master_id is None:
            continue
        route_master_rows.append({
            'route_master_id': route_master_id,
            'route_master': _to_text(row.get('route_master')),
            'name': _to_text(row.get('name')),
            'ref': _to_text(row.get('ref')),
            'operator': _to_text(row.get('operator')),
            'operator_wikidata': _to_text(row.get('operator_wikidata')),
            'network': _to_text(row.get('network')),
            'network_wikidata': _to_text(row.get('network_wikidata')),
            'is_non_gtfs': str(row.get('is_non_gtfs')).lower() == 'true',
            'colour': _to_text(row.get('colour')),
            'gtfs_route_id': _to_text(row.get('gtfs_route_id')),
            'run_id': _to_text(row.get('run_id')),
        })

    route_master_tag_rows: list[dict[str, Any]] = []
    for row in _records(all_route_data.get('osm_route_master_tags')):
        route_master_id = _to_text(row.get('route_master_id'))
        tag_key = _to_text(row.get('tag_key'))
        if route_master_id is None or tag_key is None:
            continue
        route_master_tag_rows.append({
            'route_master_id': route_master_id,
            'tag_key': tag_key,
            'tag_value': _to_text(row.get('tag_value')),
        })

    route_master_member_rows: list[dict[str, Any]] = []
    seen_route_master_members: set[tuple[str, str]] = set()
    for row in _records(all_route_data.get('osm_route_master_members')):
        route_master_id = _to_text(row.get('route_master_id'))
        relation_id = _to_text(row.get('relation_id'))
        if route_master_id is None or relation_id is None:
            continue
        membership_key = (route_master_id, relation_id)
        if membership_key in seen_route_master_members:
            continue
        seen_route_master_members.add(membership_key)
        route_master_member_rows.append({
            'route_master_id': route_master_id,
            'relation_id': relation_id,
            'member_sequence': _to_int(row.get('member_sequence')),
            'member_role': _to_text(row.get('member_role')),
        })

    relation_rows: list[dict[str, Any]] = []
    relation_source = all_route_data.get('osm_route_relations')
    for row in _records(relation_source):
        relation_id = _to_text(row.get('relation_id'))
        if relation_id is None:
            continue
        relation_rows.append({
            'relation_id': relation_id,
            'route': _to_text(row.get('route')),
            'name': _to_text(row.get('name')),
            'ref': _to_text(row.get('ref')),
            'operator': _to_text(row.get('operator')),
            'operator_wikidata': _to_text(row.get('operator_wikidata')),
            'network': _to_text(row.get('network')),
            'network_wikidata': _to_text(row.get('network_wikidata')),
            'is_non_gtfs': str(row.get('is_non_gtfs')).lower() == 'true',
            'from_name': _to_text(row.get('from_name')),
            'to_name': _to_text(row.get('to_name')),
            'via': _to_text(row.get('via')),
            'public_transport_version': _to_text(row.get('public_transport_version')),
            'colour': _to_text(row.get('colour')),
            'gtfs_route_id': _to_text(row.get('gtfs_route_id')),
            'gtfs_trip_id': _to_text(row.get('gtfs_trip_id')),
            'gtfs_trip_id_sample': _to_text(row.get('gtfs_trip_id_sample')),
            'gtfs_shape_id': _to_text(row.get('gtfs_shape_id')),
            'route_master_id': _to_text(row.get('route_master_id')),
            'family_origin': _to_text(row.get('family_origin')),
            'synthetic_family_key': _to_text(row.get('synthetic_family_key')),
            'run_id': _to_text(row.get('run_id')),
        })

    relation_tag_rows: list[dict[str, Any]] = []
    relation_tag_source = all_route_data.get('osm_route_relation_tags')
    for row in _records(relation_tag_source):
        relation_id = _to_text(row.get('relation_id'))
        tag_key = _to_text(row.get('tag_key'))
        if relation_id is None or tag_key is None:
            continue
        relation_tag_rows.append({
            'relation_id': relation_id,
            'tag_key': tag_key,
            'tag_value': _to_text(row.get('tag_value')),
        })

    relation_member_rows: list[dict[str, Any]] = []
    relation_member_source = all_route_data.get('osm_route_relation_members')
    for row in _records(relation_member_source):
        relation_id = _to_text(row.get('relation_id'))
        member_type = _first_non_empty(row.get('member_type'), 'node' if _to_text(row.get('resolved_node_id')) else None)
        member_ref = _first_non_empty(row.get('member_ref'), row.get('resolved_node_id'))
        if relation_id is None or member_type is None or member_ref is None:
            continue
        relation_member_rows.append({
            'relation_id': relation_id,
            'member_type': member_type,
            'member_ref': member_ref,
            'member_role': _to_text(row.get('member_role')),
            'member_sequence': _to_int(row.get('member_sequence')),
            'resolved_node_id': _to_text(row.get('resolved_node_id')),
            'direction_id_derived': _to_text(row.get('direction_id_derived')),
        })

    relation_stop_rows: list[dict[str, Any]] = []
    explicit_relation_stops = all_route_data.get('osm_route_relation_stops')
    if explicit_relation_stops is not None and not explicit_relation_stops.empty:
        for row in _records(explicit_relation_stops):
            relation_id = _to_text(row.get('relation_id'))
            osm_node_id = _to_text(row.get('osm_node_id'))
            if relation_id is None or osm_node_id is None:
                continue
            resolved = _resolve_osm_stop_fields(osm_node_id, row, lookups)
            relation_stop_rows.append({
                'relation_id': relation_id,
                'direction_id': _to_text(row.get('direction_id')),
                'stop_sequence': _to_int(row.get('stop_sequence')),
                'osm_node_id': osm_node_id,
                'stop_role': _to_text(row.get('stop_role')),
                **resolved,
            })
    else:
        for row in relation_member_rows:
            osm_node_id = _to_text(row.get('resolved_node_id'))
            if osm_node_id is None:
                continue
            resolved = _resolve_osm_stop_fields(osm_node_id, row, lookups)
            relation_stop_rows.append({
                'relation_id': row['relation_id'],
                'direction_id': row.get('direction_id_derived'),
                'stop_sequence': row['member_sequence'],
                'osm_node_id': osm_node_id,
                'stop_role': row.get('member_role'),
                **resolved,
            })

    relation_stop_rows.sort(key=lambda row: (row['relation_id'], row['stop_sequence'], row['osm_node_id'] or ''))
    return {
        'osm_route_masters': route_master_rows,
        'osm_route_master_tags': route_master_tag_rows,
        'osm_route_master_members': route_master_member_rows,
        'osm_route_relations': relation_rows,
        'osm_route_relation_tags': relation_tag_rows,
        'osm_route_relation_members': relation_member_rows,
        'osm_route_relation_stops': relation_stop_rows,
    }


def _build_line_family_rows(
    atlas_rows: dict[str, Any],
    osm_rows: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    line_family_id_counter = count(1)
    line_family_rows: list[dict[str, Any]] = []
    atlas_line_to_family_id: dict[str, int] = {}
    relation_id_to_family_id: dict[str, int] = {}

    for row in atlas_rows['atlas_line_families']:
        family_id = next(line_family_id_counter)
        atlas_line_to_family_id[row['atlas_line_id']] = family_id
        line_family_rows.append({
            'id': family_id,
            'source': 'atlas',
            'source_family_id': row['atlas_line_id'],
            'family_origin': 'atlas_gtfs',
            'route_type': row.get('route_type'),
            'display_route_id': row['atlas_line_id'],
            'public_name': _first_non_empty(row.get('route_long_name'), row.get('route_short_name'), row['atlas_line_id']),
            'ref': row.get('route_short_name'),
            'operator': row.get('agency_id'),
            'operator_wikidata': None,
            'network': None,
            'network_wikidata': None,
            'is_non_gtfs': False,
            'gtfs_route_id': row['atlas_line_id'],
            'normalized_route_id': _first_non_empty(row.get('route_id_normalized'), normalize_route_id(row['atlas_line_id'])),
            'atlas_line_id': row['atlas_line_id'],
            'route_master_id': None,
            'representative_relation_id': None,
        })

    route_master_lookup = {row['route_master_id']: row for row in osm_rows['osm_route_masters']}
    family_groups: dict[tuple[str, str], dict[str, Any]] = {}

    for row in osm_rows['osm_route_masters']:
        key = ('route_master', row['route_master_id'])
        family_groups[key] = {
            'family_origin': 'route_master',
            'source_family_id': row['route_master_id'],
            'route_master_row': row,
            'relations': [],
        }

    for relation in osm_rows['osm_route_relations']:
        route_master_id = relation.get('route_master_id')
        gtfs_route_id = relation.get('gtfs_route_id')
        normalized_gtfs_route_id = _first_non_empty(normalize_route_id(gtfs_route_id), gtfs_route_id)
        ref = relation.get('ref')
        operator = relation.get('operator')
        operator_wikidata = relation.get('operator_wikidata')
        network = relation.get('network')
        network_wikidata = relation.get('network_wikidata')
        route = relation.get('route')

        if route_master_id and route_master_id in route_master_lookup:
            key = ('route_master', route_master_id)
            family_origin = 'route_master'
            source_family_id = route_master_id
        elif normalized_gtfs_route_id:
            key = ('synthetic_gtfs_route_id', normalized_gtfs_route_id)
            family_origin = 'synthetic_gtfs_route_id'
            source_family_id = normalized_gtfs_route_id
        elif _first_non_empty(ref, operator, network, route):
            synthetic_key = '|'.join(value or '' for value in (route, ref, operator, network))
            key = ('synthetic_ref_operator', synthetic_key)
            family_origin = 'synthetic_ref_operator'
            source_family_id = synthetic_key
        else:
            key = ('synthetic_relation', relation['relation_id'])
            family_origin = 'synthetic_relation'
            source_family_id = relation['relation_id']

        group = family_groups.setdefault(
            key,
            {
                'family_origin': family_origin,
                'source_family_id': source_family_id,
                'route_master_row': route_master_lookup.get(route_master_id),
                'relations': [],
            },
        )
        group['relations'].append(relation)

    for group in family_groups.values():
        family_id = next(line_family_id_counter)
        route_master_row = group.get('route_master_row') or {}
        relations = group.get('relations') or []
        representative_relation = relations[0] if relations else {}
        gtfs_route_id = _first_non_empty(route_master_row.get('gtfs_route_id'), representative_relation.get('gtfs_route_id'))
        normalized_route_id = _first_non_empty(normalize_route_id(gtfs_route_id), normalize_route_id(representative_relation.get('ref')), gtfs_route_id)
        line_family_rows.append({
            'id': family_id,
            'source': 'osm',
            'source_family_id': group['source_family_id'],
            'family_origin': group['family_origin'],
            'route_type': _first_non_empty(representative_relation.get('route'), route_master_row.get('route_master')),
            'display_route_id': _first_non_empty(gtfs_route_id, route_master_row.get('ref'), representative_relation.get('ref'), group['source_family_id']),
            'public_name': _first_non_empty(route_master_row.get('name'), representative_relation.get('name'), representative_relation.get('ref'), group['source_family_id']),
            'ref': _first_non_empty(route_master_row.get('ref'), representative_relation.get('ref')),
            'operator': _first_non_empty(route_master_row.get('operator'), representative_relation.get('operator')),
            'operator_wikidata': _first_non_empty(route_master_row.get('operator_wikidata'), representative_relation.get('operator_wikidata')),
            'network': _first_non_empty(route_master_row.get('network'), representative_relation.get('network')),
            'network_wikidata': _first_non_empty(route_master_row.get('network_wikidata'), representative_relation.get('network_wikidata')),
            'is_non_gtfs': bool(route_master_row.get('is_non_gtfs') or representative_relation.get('is_non_gtfs')),
            'gtfs_route_id': gtfs_route_id,
            'normalized_route_id': normalized_route_id,
            'atlas_line_id': None,
            'route_master_id': route_master_row.get('route_master_id'),
            'representative_relation_id': representative_relation.get('relation_id'),
        })
        for relation in relations:
            relation_id_to_family_id[relation['relation_id']] = family_id

    return line_family_rows, atlas_line_to_family_id, relation_id_to_family_id


def _build_itinerary_rows(
    atlas_rows: dict[str, Any],
    osm_rows: dict[str, Any],
    atlas_line_to_family_id: dict[str, int],
    relation_id_to_family_id: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    itinerary_id_counter = count(1)
    stop_call_id_counter = count(1)
    itinerary_rows: list[dict[str, Any]] = []
    stop_call_rows: list[dict[str, Any]] = []
    stop_calls_by_itinerary_id: dict[int, list[dict[str, Any]]] = defaultdict(list)

    atlas_stop_calls_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in atlas_rows['atlas_itinerary_stop_calls']:
        atlas_stop_calls_by_source[row['atlas_itinerary_id']].append(row)
    for rows in atlas_stop_calls_by_source.values():
        rows.sort(key=lambda row: row['stop_sequence'])

    for row in atlas_rows['atlas_itineraries']:
        line_family_id = atlas_line_to_family_id.get(row['atlas_line_id'])
        if line_family_id is None:
            continue
        generic_itinerary_id = next(itinerary_id_counter)
        call_rows = atlas_stop_calls_by_source.get(row['atlas_itinerary_id'], [])
        itinerary_rows.append({
            'id': generic_itinerary_id,
            'source': 'atlas',
            'line_family_id': line_family_id,
            'source_itinerary_id': row['atlas_itinerary_id'],
            'direction_id': row.get('direction_id'),
            'headsign_or_pattern_hash': row.get('headsign_or_pattern_hash'),
            'display_name': _first_non_empty(row.get('direction_label'), row.get('representative_headsign'), row['atlas_itinerary_id']),
            'representative_headsign': row.get('representative_headsign'),
            'from_name': None,
            'to_name': None,
            'trip_count': row.get('trip_count'),
            'shape_id': row.get('shape_id'),
            'geometry_wkt': row.get('geometry_wkt'),
            'canonical_stop_count': len(call_rows),
        })
        for call_row in call_rows:
            stop_call = {
                'id': next(stop_call_id_counter),
                'itinerary_id': generic_itinerary_id,
                'stop_sequence': call_row['stop_sequence'],
                'source_stop_id': call_row.get('gtfs_stop_id'),
                'source_sloid': call_row.get('resolved_sloid'),
                'source_sloid_variants': call_row.get('resolved_sloid_variants'),
                'source_node_id': None,
                'canonical_stop_key': call_row.get('canonical_stop_key'),
                'stop_label': call_row.get('stop_label'),
                'uic_ref': call_row.get('uic_number'),
                'platform_code': call_row.get('platform_code'),
                'stop_lat': call_row.get('stop_lat'),
                'stop_lon': call_row.get('stop_lon'),
                'member_role': None,
            }
            stop_call_rows.append(stop_call)
            stop_calls_by_itinerary_id[generic_itinerary_id].append(stop_call)

    relation_stop_rows_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in osm_rows['osm_route_relation_stops']:
        relation_stop_rows_by_relation[row['relation_id']].append(row)
    for rows in relation_stop_rows_by_relation.values():
        rows.sort(key=lambda row: row['stop_sequence'])

    for row in osm_rows['osm_route_relations']:
        line_family_id = relation_id_to_family_id.get(row['relation_id'])
        if line_family_id is None:
            continue
        call_rows = relation_stop_rows_by_relation.get(row['relation_id'], [])
        generic_itinerary_id = next(itinerary_id_counter)
        sequence_pattern_hash = _hash_sequence([
            _first_non_empty(call_row.get('canonical_stop_key'), f"osm:{call_row.get('osm_node_id')}")
            for call_row in call_rows
        ]) if call_rows else None
        direction_id = next((call_row.get('direction_id') for call_row in call_rows if call_row.get('direction_id') is not None), None)
        itinerary_rows.append({
            'id': generic_itinerary_id,
            'source': 'osm',
            'line_family_id': line_family_id,
            'source_itinerary_id': row['relation_id'],
            'direction_id': direction_id,
            'headsign_or_pattern_hash': sequence_pattern_hash,
            'display_name': _first_non_empty(row.get('name'), f"{row.get('from_name')} -> {row.get('to_name')}" if row.get('from_name') or row.get('to_name') else None, row.get('ref'), row['relation_id']),
            'representative_headsign': _first_non_empty(row.get('name'), row.get('ref')),
            'from_name': row.get('from_name'),
            'to_name': row.get('to_name'),
            'trip_count': 1,
            'shape_id': row.get('gtfs_shape_id'),
            'geometry_wkt': None,
            'canonical_stop_count': len(call_rows),
        })
        for call_row in call_rows:
            stop_call = {
                'id': next(stop_call_id_counter),
                'itinerary_id': generic_itinerary_id,
                'stop_sequence': call_row['stop_sequence'],
                'source_stop_id': None,
                'source_sloid': None,
                'source_sloid_variants': None,
                'source_node_id': call_row.get('osm_node_id'),
                'canonical_stop_key': call_row.get('canonical_stop_key'),
                'stop_label': call_row.get('stop_label'),
                'uic_ref': call_row.get('uic_ref'),
                'platform_code': None,
                'stop_lat': call_row.get('stop_lat'),
                'stop_lon': call_row.get('stop_lon'),
                'member_role': call_row.get('stop_role'),
            }
            stop_call_rows.append(stop_call)
            stop_calls_by_itinerary_id[generic_itinerary_id].append(stop_call)

    return itinerary_rows, stop_call_rows, stop_calls_by_itinerary_id


def _score_line_family_pair(atlas_family: dict[str, Any], osm_family: dict[str, Any]) -> tuple[float, str | None]:
    if atlas_family['source'] != 'atlas' or osm_family['source'] != 'osm':
        return 0.0, None

    atlas_route_id = _to_text(atlas_family.get('gtfs_route_id'))
    atlas_normalized = _to_text(atlas_family.get('normalized_route_id'))

    osm_gtfs_route_id = _to_text(osm_family.get('gtfs_route_id'))
    osm_normalized = _to_text(osm_family.get('normalized_route_id'))

    if atlas_route_id and osm_gtfs_route_id and atlas_route_id == osm_gtfs_route_id:
        return 1.0, 'exact_gtfs_route_id'
    if atlas_normalized and osm_normalized and atlas_normalized == osm_normalized:
        return 0.95, 'normalized_gtfs_route_id'
    if atlas_route_id and _to_text(osm_family.get('display_route_id')) == atlas_route_id:
        return 0.9, 'display_route_id_match'
    return 0.0, None


def _parse_json_list(value: Any) -> list[str]:
    text = _to_text(value)
    if text is None:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in (_to_text(entry) for entry in parsed) if item is not None]


def _is_resolved_atlas_sloid(value: Any) -> bool:
    text = _to_text(value)
    if text is None:
        return False
    return not text.startswith(_NON_ATLAS_STOP_KEY_PREFIXES)


def _resolved_stop_identities(stop_call: dict[str, Any]) -> set[str]:
    identities: set[str] = set()

    source_sloid = _to_text(stop_call.get('source_sloid'))
    if _is_resolved_atlas_sloid(source_sloid):
        identities.add(source_sloid)

    for variant in _parse_json_list(stop_call.get('source_sloid_variants')):
        if _is_resolved_atlas_sloid(variant):
            identities.add(variant)

    canonical_stop_key = _to_text(stop_call.get('canonical_stop_key'))
    if _is_resolved_atlas_sloid(canonical_stop_key):
        identities.add(canonical_stop_key)

    return identities


def _match_stop_calls(atlas_call: dict[str, Any], osm_call: dict[str, Any]) -> str | None:
    atlas_identities = _resolved_stop_identities(atlas_call)
    osm_identities = _resolved_stop_identities(osm_call)
    if atlas_identities and osm_identities:
        if atlas_identities & osm_identities:
            return 'resolved_sloid_match'
        return None

    atlas_uic = _to_text(atlas_call.get('uic_ref'))
    osm_uic = _to_text(osm_call.get('uic_ref'))
    if atlas_uic and osm_uic and atlas_uic == osm_uic:
        return 'uic_match'

    return None


def _align_stop_sequences(atlas_calls: list[dict[str, Any]], osm_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = len(atlas_calls)
    cols = len(osm_calls)
    scores = [[0] * (cols + 1) for _ in range(rows + 1)]
    trace: list[list[tuple[str, str | None] | None]] = [[None] * (cols + 1) for _ in range(rows + 1)]

    for i in range(1, rows + 1):
        trace[i][0] = ('up', None)
    for j in range(1, cols + 1):
        trace[0][j] = ('left', None)

    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            match_type = _match_stop_calls(atlas_calls[i - 1], osm_calls[j - 1])
            diagonal = scores[i - 1][j - 1] + (1 if match_type else 0)
            up = scores[i - 1][j]
            left = scores[i][j - 1]
            if match_type and diagonal >= up and diagonal >= left:
                scores[i][j] = diagonal
                trace[i][j] = ('diag', match_type)
            elif up >= left:
                scores[i][j] = up
                trace[i][j] = ('up', None)
            else:
                scores[i][j] = left
                trace[i][j] = ('left', None)

    alignments: list[dict[str, Any]] = []
    i = rows
    j = cols
    while i > 0 or j > 0:
        direction, match_type = trace[i][j] or ('left', None)
        if direction == 'diag':
            alignments.append({
                'atlas_call': atlas_calls[i - 1],
                'osm_call': osm_calls[j - 1],
                'alignment_type': match_type,
            })
            i -= 1
            j -= 1
        elif direction == 'up':
            alignments.append({
                'atlas_call': atlas_calls[i - 1],
                'osm_call': None,
                'alignment_type': 'atlas_only',
            })
            i -= 1
        else:
            alignments.append({
                'atlas_call': None,
                'osm_call': osm_calls[j - 1],
                'alignment_type': 'osm_only',
            })
            j -= 1

    alignments.reverse()
    return alignments, scores[rows][cols]


def _direction_ids_match(atlas_itinerary: dict[str, Any], osm_itinerary: dict[str, Any]) -> bool:
    atlas_direction = _to_text(atlas_itinerary.get('direction_id'))
    osm_direction = _to_text(osm_itinerary.get('direction_id'))
    return atlas_direction is not None and atlas_direction == osm_direction


def _score_itinerary_pair(
    atlas_itinerary: dict[str, Any],
    osm_itinerary: dict[str, Any],
    atlas_calls: list[dict[str, Any]],
    osm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    direction_matches = _direction_ids_match(atlas_itinerary, osm_itinerary)
    alignments, matched_stop_count = _align_stop_sequences(atlas_calls, osm_calls)
    stop_score = round(matched_stop_count / max(len(atlas_calls), len(osm_calls), 1), 4)
    is_eligible = direction_matches and stop_score >= _ITINERARY_MATCH_MIN_RATIO
    if not direction_matches:
        match_reason = 'direction_mismatch'
    elif is_eligible:
        match_reason = 'ordered_stop_match'
    else:
        match_reason = 'below_stop_match_threshold'
    return {
        'direction_score': 1.0 if direction_matches else 0.0,
        'stop_score': stop_score,
        'geometry_score': None,
        'overall_score': stop_score,
        'match_reason': match_reason,
        'alignments': alignments,
        'matched_stop_count': matched_stop_count,
        'atlas_stop_count': len(atlas_calls),
        'osm_stop_count': len(osm_calls),
        'is_eligible': is_eligible,
    }


def _choose_best_itinerary_pairs(
    atlas_itineraries: list[dict[str, Any]],
    osm_itineraries: list[dict[str, Any]],
    pair_scores: dict[tuple[int, int], dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    if not atlas_itineraries or not osm_itineraries:
        return []

    atlas_sorted = sorted(atlas_itineraries, key=lambda row: row['id'])
    osm_sorted = sorted(osm_itineraries, key=lambda row: row['id'])
    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for atlas_itinerary in atlas_sorted:
        for osm_itinerary in osm_sorted:
            score_row = pair_scores[(atlas_itinerary['id'], osm_itinerary['id'])]
            is_eligible = score_row.get('is_eligible')
            if is_eligible is None:
                is_eligible = float(score_row.get('overall_score') or 0.0) > 0.25
            if not is_eligible:
                continue
            candidates.append((atlas_itinerary, osm_itinerary, score_row))

    candidates.sort(
        key=lambda item: (
            -int(item[2].get('matched_stop_count', 0)),
            -float(item[2].get('stop_score', item[2].get('overall_score', 0.0) or 0.0)),
            item[0]['id'],
            item[1]['id'],
        )
    )

    chosen_pairs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    used_atlas_ids: set[int] = set()
    used_osm_ids: set[int] = set()
    for atlas_itinerary, osm_itinerary, score_row in candidates:
        if atlas_itinerary['id'] in used_atlas_ids or osm_itinerary['id'] in used_osm_ids:
            continue
        used_atlas_ids.add(atlas_itinerary['id'])
        used_osm_ids.add(osm_itinerary['id'])
        chosen_pairs.append((atlas_itinerary, osm_itinerary, score_row))

    return chosen_pairs


def build_route_write_payload(
    all_route_data: dict[str, pd.DataFrame],
    known_sloids: set[str],
    base_data: MatchingOutput | None = None,
) -> dict[str, Any]:
    """Prepare raw and normalized route-product rows for DB insertion."""
    lookups = _build_base_lookups(base_data, known_sloids)
    atlas_rows = _build_atlas_source_rows(all_route_data, known_sloids, lookups['atlas_stop_lookup'])
    osm_rows = _build_osm_source_rows(all_route_data, lookups)

    line_family_rows, atlas_line_to_family_id, relation_id_to_family_id = _build_line_family_rows(atlas_rows, osm_rows)
    itinerary_rows, stop_call_rows, stop_calls_by_itinerary_id = _build_itinerary_rows(
        atlas_rows,
        osm_rows,
        atlas_line_to_family_id,
        relation_id_to_family_id,
    )

    atlas_line_families = [row for row in line_family_rows if row['source'] == 'atlas']
    osm_line_families = [row for row in line_family_rows if row['source'] == 'osm']
    line_family_match_id_counter = count(1)
    itinerary_match_id_counter = count(1)

    line_family_match_rows: list[dict[str, Any]] = []
    itinerary_match_rows: list[dict[str, Any]] = []

    candidate_pairs = []
    for atlas_family in atlas_line_families:
        for osm_family in osm_line_families:
            if osm_family.get('is_non_gtfs'):
                continue
            score, reason = _score_line_family_pair(atlas_family, osm_family)
            if score <= 0.0 or reason is None:
                continue
            candidate_pairs.append((score, atlas_family, osm_family, reason))
    candidate_pairs.sort(key=lambda item: (-item[0], item[1]['id'], item[2]['id']))

    matched_atlas_family_ids: set[int] = set()
    matched_osm_family_ids: set[int] = set()
    for score, atlas_family, osm_family, reason in candidate_pairs:
        if atlas_family['id'] in matched_atlas_family_ids or osm_family['id'] in matched_osm_family_ids:
            continue
        line_family_match_rows.append({
            'id': next(line_family_match_id_counter),
            'atlas_line_family_id': atlas_family['id'],
            'osm_line_family_id': osm_family['id'],
            'match_method': reason,
        })
        matched_atlas_family_ids.add(atlas_family['id'])
        matched_osm_family_ids.add(osm_family['id'])

    itineraries_by_family_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for itinerary_row in itinerary_rows:
        itineraries_by_family_id[itinerary_row['line_family_id']].append(itinerary_row)
    for itinerary_list in itineraries_by_family_id.values():
        itinerary_list.sort(key=lambda row: row['id'])

    for line_family_match_row in line_family_match_rows:
        atlas_itineraries = itineraries_by_family_id.get(line_family_match_row['atlas_line_family_id'], [])
        osm_itineraries = itineraries_by_family_id.get(line_family_match_row['osm_line_family_id'], [])
        pair_scores: dict[tuple[int, int], dict[str, Any]] = {}
        for atlas_itinerary in atlas_itineraries:
            atlas_calls = stop_calls_by_itinerary_id.get(atlas_itinerary['id'], [])
            for osm_itinerary in osm_itineraries:
                osm_calls = stop_calls_by_itinerary_id.get(osm_itinerary['id'], [])
                pair_scores[(atlas_itinerary['id'], osm_itinerary['id'])] = _score_itinerary_pair(
                    atlas_itinerary,
                    osm_itinerary,
                    atlas_calls,
                    osm_calls,
                )

        chosen_pairs = _choose_best_itinerary_pairs(atlas_itineraries, osm_itineraries, pair_scores)
        matched_atlas_itinerary_ids: set[int] = set()
        matched_osm_itinerary_ids: set[int] = set()
        for atlas_itinerary, osm_itinerary, score_row in chosen_pairs:
            itinerary_match_id = next(itinerary_match_id_counter)
            matched_atlas_itinerary_ids.add(atlas_itinerary['id'])
            matched_osm_itinerary_ids.add(osm_itinerary['id'])
            itinerary_match_rows.append({
                'id': itinerary_match_id,
                'line_family_match_id': line_family_match_row['id'],
                'atlas_itinerary_id': atlas_itinerary['id'],
                'osm_itinerary_id': osm_itinerary['id'],
                'direction_score': score_row['direction_score'],
                'stop_score': score_row['stop_score'],
                'geometry_score': score_row['geometry_score'],
                'overall_score': score_row['overall_score'],
                'match_reason': score_row['match_reason'],
            })

    return {
        'atlas_line_families': atlas_rows['atlas_line_families'],
        'atlas_itineraries': atlas_rows['atlas_itineraries'],
        'atlas_itinerary_stop_calls': atlas_rows['atlas_itinerary_stop_calls'],
        'osm_route_masters': osm_rows['osm_route_masters'],
        'osm_route_master_tags': osm_rows['osm_route_master_tags'],
        'osm_route_master_members': osm_rows['osm_route_master_members'],
        'osm_route_relations': osm_rows['osm_route_relations'],
        'osm_route_relation_tags': osm_rows['osm_route_relation_tags'],
        'osm_route_relation_members': osm_rows['osm_route_relation_members'],
        'osm_route_relation_stops': osm_rows['osm_route_relation_stops'],
        'line_families': line_family_rows,
        'itineraries': itinerary_rows,
        'stop_calls': stop_call_rows,
        'line_family_matches': line_family_match_rows,
        'itinerary_matches': itinerary_match_rows,
        'matched_routes': len(line_family_match_rows),
        'skipped_sloids': atlas_rows['skipped_sloids'],
    }