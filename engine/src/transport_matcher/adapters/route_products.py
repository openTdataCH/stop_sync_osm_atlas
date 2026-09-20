"""Read optional route products at an explicit adapter boundary."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROUTE_FILENAMES = {
    'atlas_line_families': 'atlas_line_families.csv',
    'atlas_itineraries': 'atlas_itineraries.csv',
    'atlas_itinerary_stop_calls': 'atlas_itinerary_stop_calls.csv',
    'osm_route_masters': 'osm_route_masters.csv',
    'osm_route_relations': 'osm_route_relations.csv',
    'osm_route_relation_members': 'osm_route_relation_members.csv',
    'osm_route_relation_stops': 'osm_route_relation_stops.csv',
}


def load_all_route_data(processed_dir: str | Path, *, source_only=False) -> dict[str, pd.DataFrame]:
    """Load present products; malformed existing products fail the run clearly."""
    result = {}
    for key, filename in ROUTE_FILENAMES.items():
        if source_only and not key.startswith('atlas_'):
            continue
        path = Path(processed_dir) / filename
        if path.exists():
            try:
                result[key] = pd.read_csv(path, dtype=str, keep_default_na=False)
            except pd.errors.EmptyDataError:
                result[key] = pd.DataFrame()
    return result


def read_gtfs_identity_cache(processed_dir: str | Path) -> tuple[list[dict], list[dict]]:
    paths = [Path(processed_dir) / filename for filename in (
        'gtfs_stops_raw.csv', 'gtfs_stop_identity_resolution.csv',
    )]
    if not any(path.exists() for path in paths):
        return [], []
    if not all(path.exists() for path in paths):
        raise ValueError('Both GTFS stop and identity cache products are required together')
    rows = []
    numeric_columns = {
        'stop_lat', 'stop_lon', 'gtfs_stop_lat', 'gtfs_stop_lon',
        'atlas_lat', 'atlas_lon', 'confidence', 'distance_m',
    }
    for path in paths:
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError:
            rows.append([])
            continue
        product = []
        for raw in frame.to_dict(orient='records'):
            row = {key: (value if value != '' else None) for key, value in raw.items()}
            for key in numeric_columns & row.keys():
                row[key] = float(row[key]) if row[key] is not None else None
            if row.get('details_json'):
                try:
                    row['details_json'] = json.loads(row['details_json'])
                except json.JSONDecodeError:
                    # Old CSV caches used Python dict repr; accept only literals.
                    row['details_json'] = ast.literal_eval(row['details_json'])
                if not isinstance(row['details_json'], dict):
                    raise ValueError(f'{path}: details_json must contain an object')
            product.append(row)
        rows.append(product)
    return rows[0], rows[1]


def source_route_evidence(route_data: dict[str, pd.DataFrame]) -> dict[str, dict[str, list]]:
    """Build optional stop evidence without flattening ordered stop-call products."""
    neutral = ('source_line_families', 'source_itineraries', 'source_itinerary_stop_calls')
    legacy = ('atlas_line_families', 'atlas_itineraries', 'atlas_itinerary_stop_calls')
    required = neutral if all(key in route_data for key in neutral) else legacy
    if not all(key in route_data and not route_data[key].empty for key in required):
        return {}
    family_id_field = 'source_family_id' if required == neutral else 'atlas_line_id'
    itinerary_id_field = 'source_itinerary_id' if required == neutral else 'atlas_itinerary_id'
    source_key_field = 'source_stop_key' if required == neutral else 'resolved_sloid'
    families = {str(row[family_id_field]): row for row in route_data[required[0]].to_dict('records')}
    itineraries = {str(row[itinerary_id_field]): row for row in route_data[required[1]].to_dict('records')}
    evidence = {}
    seen = set()
    for row in route_data[required[2]].to_dict('records'):
        source_key = row.get(source_key_field) or row.get('sloid')
        itinerary = itineraries.get(str(row.get(itinerary_id_field)), {})
        route_id = itinerary.get(family_id_field)
        if not source_key or not route_id:
            continue
        direction = itinerary.get('direction_id')
        if direction not in (None, ''):
            try:
                direction = str(int(float(direction)))
            except (ValueError, TypeError):
                direction = str(direction)
        else:
            direction = None
        identity = (str(source_key), str(route_id), direction)
        if identity in seen:
            continue
        seen.add(identity)
        family = families.get(str(route_id), {})
        evidence.setdefault(str(source_key), {'gtfs': []})['gtfs'].append({
            'route_id': str(route_id),
            'route_id_normalized': family.get('route_id_normalized'),
            'route_name_short': family.get('route_short_name'),
            'route_name_long': family.get('route_long_name'),
            'direction_id': direction,
            'direction_name': itinerary.get('direction_label'),
        })
    return evidence


def scope_source_stop_keys(route_data: dict[str, pd.DataFrame], keys_by_id: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Translate native source references to stable engine keys, keeping foreign keys."""
    result = dict(route_data)
    calls_key = 'source_itinerary_stop_calls' if 'source_itinerary_stop_calls' in result else 'atlas_itinerary_stop_calls'
    calls = result.get(calls_key)
    if calls is None:
        return result
    calls = calls.copy()
    result[calls_key] = calls
    for column in ('source_stop_key', 'sloid', 'resolved_sloid', 'canonical_stop_key'):
        if column in calls:
            calls[column] = calls[column].map(lambda value: keys_by_id.get(str(value), value))
    for column in ('sloid_variants', 'resolved_sloid_variants'):
        if column in calls:
            def scope_variants(value: Any) -> Any:
                if not isinstance(value, str) or not value:
                    return value
                parsed = json.loads(value)
                return json.dumps([keys_by_id.get(str(item), item) for item in parsed])
            calls[column] = calls[column].map(scope_variants)
    return result


def unresolved_osm_member_diagnostics(route_data: dict[str, pd.DataFrame]) -> list[dict]:
    """Describe stop members outside the currently supported geometry extract."""
    members = route_data.get('osm_route_relation_members')
    if members is None or members.empty:
        return []
    # Route extracts can contain millions of way members. Filter the two
    # relevant columns before materializing at most ten example dictionaries.
    roles = members.get('member_role', pd.Series('', index=members.index)).fillna('').astype(str)
    resolved = members.get('resolved_node_id', pd.Series(None, index=members.index, dtype=object))
    missing = roles.str.startswith(('stop', 'platform')) & (resolved.isna() | resolved.eq(''))
    count = int(missing.sum())
    if not count:
        return []
    examples = members.loc[missing, ['relation_id', 'member_type', 'member_ref']].head(10).to_dict('records')
    return [{
        'code': 'unsupported_or_external_osm_route_members',
        'stage': 'osm_adapter',
        'count': count,
        'reason': 'Stop members without supported geometry are retained in raw inputs but excluded from normalized itinerary calls.',
        'examples': [
            {'relation_id': row.get('relation_id'), 'element_type': row.get('member_type'), 'element_id': row.get('member_ref')}
            for row in examples
        ],
    }]
