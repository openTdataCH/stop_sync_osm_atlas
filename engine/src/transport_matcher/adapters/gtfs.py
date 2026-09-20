"""A feed-independent GTFS adapter with scoped identities and ordered calls."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

from transport_matcher.core.models import SourceStop
from transport_matcher.core.state import SourceState
from .base import AdapterResult
from .route_products import source_route_evidence, unresolved_osm_member_diagnostics
from .metadata import fingerprint


def _read_tables(path: Path) -> dict[str, list[dict[str, str]]]:
    names = ('stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt')
    tables = {}
    if path.is_dir():
        for name in names:
            if (path / name).exists():
                with (path / name).open(encoding='utf-8-sig', newline='') as handle:
                    tables[name] = list(csv.DictReader(handle))
    else:
        with zipfile.ZipFile(path) as archive:
            for name in names:
                candidates = [member for member in archive.namelist() if Path(member).name == name]
                if len(candidates) > 1:
                    raise ValueError(f'GTFS archive contains multiple {name} files')
                if candidates:
                    with archive.open(candidates[0]) as binary:
                        with io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as handle:
                            tables[name] = list(csv.DictReader(handle))
    if 'stops.txt' not in tables:
        raise ValueError('GTFS input requires stops.txt')
    return tables


def read_gtfs(path: str | Path, *, namespace: str) -> AdapterResult:
    """Read a GTFS folder or ZIP, without Swiss identifiers or geography filters.

    ``namespace`` identifies an agency/feed, and must remain stable between runs.
    Route evidence is optional. When supplied, all three route files must exist;
    loop calls and repeated visits are retained in numeric stop_sequence order.
    """
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', namespace):
        raise ValueError('GTFS namespace must contain only letters, digits, dot, dash or underscore')
    path = Path(path)
    tables = _read_tables(path)
    input_paths = [path / name for name in tables] if path.is_dir() else [path]
    stops = []
    by_id = {}
    seen_stop_ids = set()
    for row in tables['stops.txt']:
        stop_id = (row.get('stop_id') or '').strip()
        if not stop_id:
            raise ValueError('GTFS stop has an empty stop_id')
        if stop_id in seen_stop_ids:
            raise ValueError(f'Duplicate GTFS stop_id: {stop_id}')
        seen_stop_ids.add(stop_id)
        location_type = row.get('location_type') or '0'
        # The engine matches boarding stops, and excludes OSM stations. Parent
        # stations must not compete with child platforms for their OSM links.
        # Preserve other GTFS location types in the source extension instead.
        if location_type != '0':
            continue
        try:
            lat, lon = float(row['stop_lat']), float(row['stop_lon'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'GTFS stop {stop_id!r} requires numeric coordinates') from exc
        stop = SourceStop(
            namespace=namespace, source_id=stop_id, lat=lat, lon=lon,
            name=row.get('stop_name') or '', platform_code=row.get('platform_code') or '',
            parent_id=f"{namespace}:{row['parent_station']}" if row.get('parent_station') else None,
            stop_kind='platform',
            extensions={'gtfs': {key: value for key, value in row.items() if value != ''}},
        )
        by_id[stop_id] = stop
        stops.append(stop)

    route_files = {'routes.txt', 'trips.txt', 'stop_times.txt'}
    available_routes = route_files & tables.keys()
    if available_routes and available_routes != route_files:
        raise ValueError(f'GTFS route evidence is incomplete; missing {sorted(route_files - tables.keys())}')
    route_data = _build_route_products(tables, namespace, by_id) if available_routes else {}
    return AdapterResult(
        source=SourceState(stops, route_evidence_by_key=source_route_evidence(route_data)),
        route_data=route_data,
        extensions={'gtfs_source': {'namespace': namespace, 'stops': tables['stops.txt']}},
        metadata={'source': 'GTFS', 'namespace': namespace, 'route_evidence_available': bool(route_data),
                  'inputs': [fingerprint(item) for item in input_paths]},
    )


def _build_route_products(tables, namespace, by_id):
    route_key = lambda value: f'{namespace}:route:{value}'
    routes = {}
    families = []
    for row in tables['routes.txt']:
        route_id = row.get('route_id')
        if not route_id or route_id in routes:
            raise ValueError(f'Missing or duplicate GTFS route_id: {route_id!r}')
        routes[route_id] = row
        families.append({
            'source_family_id': route_key(route_id), 'route_id_normalized': route_key(route_id),
            **{column: row.get(column) for column in ('agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type')},
        })
    trips = {}
    for row in tables['trips.txt']:
        if not row.get('trip_id') or row['trip_id'] in trips or row.get('route_id') not in routes:
            raise ValueError(f'Invalid or duplicate GTFS trip: {row.get("trip_id")!r}')
        trips[row['trip_id']] = row
    calls_by_trip = defaultdict(list)
    all_stop_ids = {row['stop_id'] for row in tables['stops.txt']}
    for ordinal, row in enumerate(tables['stop_times.txt']):
        if row.get('stop_id') not in all_stop_ids:
            raise ValueError(f'GTFS stop time references unknown stop: {row.get("stop_id")!r}')
        if row.get('trip_id') not in trips:
            raise ValueError(f'GTFS stop time references unknown trip: {row.get("trip_id")!r}')
        try:
            sequence = int(row['stop_sequence'])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError('GTFS stop_sequence must be an integer') from exc
        calls_by_trip[row['trip_id']].append((sequence, ordinal, row))
    patterns = {}
    for trip_id, trip in trips.items():
        calls = sorted(calls_by_trip.get(trip_id, []))
        if not calls:
            continue
        sequence = tuple(row['stop_id'] for _, _, row in calls)
        identity = (trip['route_id'], trip.get('direction_id') or None, sequence)
        if identity in patterns:
            patterns[identity]['trip_count'] += 1
            continue
        digest = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()[:24]
        itinerary_id = f'{namespace}:itinerary:{digest}'
        patterns[identity] = {
            'source_itinerary_id': itinerary_id, 'source_family_id': route_key(trip['route_id']),
            'direction_id': trip.get('direction_id') or None,
            'direction_label': trip.get('trip_headsign') or None,
            'representative_headsign': trip.get('trip_headsign') or None,
            'headsign_or_pattern_hash': digest, 'trip_count': 1,
            'shape_id': trip.get('shape_id') or None,
            '_calls': calls,
        }
    itineraries, calls = [], []
    for pattern in patterns.values():
        ordered = pattern.pop('_calls')
        itineraries.append(pattern)
        for sequence, _, row in ordered:
            stop = by_id.get(row['stop_id'])
            calls.append({
                'source_itinerary_id': pattern['source_itinerary_id'], 'stop_sequence': sequence,
                'gtfs_stop_id': f"{namespace}:{row['stop_id']}",
                'source_stop_key': stop.key if stop else None,
                'canonical_stop_key': stop.key if stop else f"{namespace}:{row['stop_id']}",
                'stop_label': stop.name if stop else row['stop_id'],
                'platform_code': stop.platform_code if stop else None,
                'stop_lat': stop.lat if stop else None, 'stop_lon': stop.lon if stop else None,
            })
    return {
        'source_line_families': pd.DataFrame(families),
        'source_itineraries': pd.DataFrame(itineraries),
        'source_itinerary_stop_calls': pd.DataFrame(calls),
    }


def run_gtfs(gtfs_path: str | Path, osm_xml: str | Path, *, namespace: str, profile=None):
    """Run a selected GTFS feed against its OSM extract, including route results.

    Supplying a namespace explicitly declares that unscoped OSM ``gtfs:route_id``
    tags in this extract refer to this feed. For multi-feed extracts, normalize
    references separately and invoke the in-memory API with explicit evidence.
    """
    from transport_matcher.api import match
    from transport_matcher.core.route_state import RouteState
    from transport_matcher.profiles import MatchingProfile
    from transport_matcher.routes import build_route_write_payload
    from .osm import read_osm
    from .osm_routes import process_osm_routes_data
    adapter = read_gtfs(gtfs_path, namespace=namespace)
    osm = read_osm(osm_xml, route_namespace=namespace)
    profile = profile or MatchingProfile(profile_id=f'gtfs:{namespace}', capabilities=('stops', 'problems', 'routes'))
    osm_products = process_osm_routes_data(Path(osm_xml).read_text(encoding='utf-8'), out_dir=None)
    for key in ('osm_route_masters', 'osm_route_relations'):
        frame = osm_products[key]
        frame['gtfs_route_id'] = frame['gtfs_route_id'].map(lambda value: f'{namespace}:route:{value}' if value else None)
        frame['route_id_normalized'] = frame['gtfs_route_id']
    adapter.route_data.update(osm_products)
    source_families = adapter.route_data.get('source_line_families', pd.DataFrame())
    route_state = RouteState.from_records(
        [{'route_id': row['source_family_id'], 'route_id_normalized': row.get('route_id_normalized')}
         for row in source_families.to_dict('records')],
        adapter.route_data['osm_route_relations'].to_dict('records'),
    )
    output = match(adapter.source, osm, profile, route_evidence={'route_state': route_state})
    output.diagnostics.extend(unresolved_osm_member_diagnostics(osm_products))
    output.routes = build_route_write_payload(
        adapter.route_data, set(adapter.source.get_all_rows_as_dict()), output,
        require_direction_match=getattr(profile, "itinerary_require_direction", False),
        min_stop_ratio=getattr(profile, "itinerary_min_stop_ratio", 0.8),
    )
    output.extensions.update(adapter.extensions)
    output.metadata.update(adapter.metadata)
    capabilities = [cap for cap in output.metadata.get('capabilities', []) if cap != 'routes']
    if output.routes.get('line_families'):
        capabilities.append('routes')
    output.metadata['capabilities'] = capabilities
    output.metadata['inputs'].append(fingerprint(osm_xml))
    output.metadata['attribution'] = {'source': 'GTFS feed supplied by caller', 'osm': '© OpenStreetMap contributors, ODbL'}
    return output
