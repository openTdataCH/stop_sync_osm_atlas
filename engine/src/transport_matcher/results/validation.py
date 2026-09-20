"""Producer-owned validation of complete result snapshots and serialized bundles.

This module has no review-application dependencies. Consumers independently
validate the documented wire contract before applying it to their own storage.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path


class InvalidResult(ValueError):
    """A result is incomplete, internally inconsistent or corrupt."""


def _require(condition, message):
    if not condition:
        raise InvalidResult(message)


def _reject_nonfinite(value):
    raise InvalidResult(f'Non-finite JSON value: {value}')


def _position(row):
    lat, lon = row.get('lat'), row.get('lon')
    return type(lat) in (int, float) and type(lon) in (int, float) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def _problem(row):
    _require(isinstance(row, dict), 'Problem must be an object')
    _require(isinstance(row.get('problem_type'), str) and row['problem_type'], 'Missing problem type')
    _require(type(row.get('priority')) is int and row['priority'] in (1, 2, 3), 'Invalid problem priority')


def _rows_by_id(rows, label):
    result = {}
    for row in rows:
        _require(isinstance(row, dict), f'Invalid {label} row')
        key = row.get('id')
        _require(type(key) is int and key > 0 and key not in result, f'Missing or duplicate {label} ID')
        result[key] = row
    return result


def _validate_routes(routes, source_keys):
    families = _rows_by_id(routes.get('line_families', []), 'route family')
    itineraries = _rows_by_id(routes.get('itineraries', []), 'itinerary')
    calls = _rows_by_id(routes.get('stop_calls', []), 'stop call')
    family_matches = _rows_by_id(routes.get('line_family_matches', []), 'route family match')
    itinerary_matches = _rows_by_id(routes.get('itinerary_matches', []), 'itinerary match')
    for row in itineraries.values():
        _require(row.get('line_family_id') in families, 'Itinerary references unknown route family')
    for row in calls.values():
        _require(row.get('itinerary_id') in itineraries, 'Stop call references unknown itinerary')
        source_key = row.get('source_sloid')
        _require(source_key is None or source_key in source_keys, 'Stop call references unknown source stop')
        variants = row.get('source_sloid_variants') or []
        if isinstance(variants, str):
            try:
                variants = json.loads(variants)
            except ValueError as exc:
                raise InvalidResult('Invalid source variants in stop call') from exc
        _require(isinstance(variants, list) and set(variants) <= source_keys, 'Stop call variants reference unknown source stop')
        # Raw OSM members and unresolved GTFS keys can legitimately be outside
        # the selected stop extract. Only resolved source references are FKs.
    for row in family_matches.values():
        left, right = row.get('atlas_line_family_id'), row.get('osm_line_family_id')
        _require(left in families and right in families, 'Route match references unknown family')
        _require(families[left].get('source') in ('atlas', 'source') and families[right].get('source') == 'osm', 'Route match has incompatible sides')
    for row in itinerary_matches.values():
        parent = family_matches.get(row.get('line_family_match_id'))
        left, right = itineraries.get(row.get('atlas_itinerary_id')), itineraries.get(row.get('osm_itinerary_id'))
        _require(parent is not None and left is not None and right is not None, 'Itinerary match references unknown entities')
        _require(left['line_family_id'] == parent['atlas_line_family_id'] and right['line_family_id'] == parent['osm_line_family_id'], 'Itinerary match belongs to another route family')


def validate_records(records):
    """Validate iterable wire sections; keep identity indexes rather than full snapshots."""
    source, osm, osm_by_id = {}, {}, {}
    for row in records['source_stops']:
        key, namespace, source_id = row.get('key'), row.get('namespace'), row.get('source_id')
        _require(isinstance(namespace, str) and namespace and ':' not in namespace, 'Invalid source namespace')
        _require(isinstance(source_id, str) and source_id and key == f'{namespace}:{source_id}', 'Inconsistent source key')
        _require(key not in source and _position(row), 'Duplicate source key or invalid coordinates')
        source[key] = namespace
    for row in records['osm_nodes']:
        key, kind, node_id = row.get('key'), row.get('element_type'), row.get('node_id')
        _require(kind in ('node', 'way', 'relation') and isinstance(node_id, str) and node_id, 'Invalid OSM identity')
        _require(kind == 'node' or node_id.startswith(f'{kind}_'), 'OSM non-node identity needs its type prefix')
        _require(kind != 'node' or not node_id.startswith(('way_', 'relation_')), 'Conflicting OSM type prefix')
        _require(key == f"osm:{kind}:{node_id.removeprefix(f'{kind}_')}", 'Inconsistent OSM key')
        _require(key not in osm and node_id not in osm_by_id and _position(row), 'Duplicate OSM identity or invalid coordinates')
        osm[key], osm_by_id[node_id] = node_id, key
    _require(source or osm, 'Refusing an empty result bundle')
    matched_source, matched_osm, pairs, expected_match_problems = set(), set(), set(), set()
    for row in records['matches']:
        left, right = row.get('source_key'), row.get('osm_key')
        _require(left in source and right in osm, 'Match references unknown entity')
        _require((left, right) not in pairs, 'Duplicate match pair')
        _require(isinstance(row.get('method'), str) and row['method'], 'Missing matching method')
        distance = row.get('distance_m')
        _require(type(distance) in (int, float) and math.isfinite(distance) and distance >= 0, 'Invalid match distance')
        _require(isinstance(row.get('evidence'), dict), 'Missing structured match evidence')
        pairs.add((left, right))
        matched_source.add(left)
        matched_osm.add(right)
        for problem in row.get('problems', []):
            _problem(problem)
            expected_match_problems.add((problem['problem_type'], problem['priority'], left, osm[right]))
    unmatched = {'source': set(), 'osm': set()}
    effective = set()
    for row in records['unmatched']:
        side, key = row.get('side'), row.get('key')
        _require(side in unmatched and key in (source if side == 'source' else osm), 'Unknown unmatched entity')
        _require(key not in unmatched[side], 'Duplicate unmatched entity')
        _require(type(row.get('isolated')) is bool, 'Unmatched entity needs an isolation status')
        unmatched[side].add(key)
        if side == 'osm':
            _require(type(row.get('effectively_matched')) is bool, 'OSM unmatched entity needs effective-match status')
            if row['effectively_matched']:
                effective.add(osm[key])
    _require(not matched_source & unmatched['source'] and not matched_osm & unmatched['osm'], 'Entity marked both matched and unmatched')
    _require(matched_source | unmatched['source'] == set(source), 'Source match coverage is incomplete')
    _require(matched_osm | unmatched['osm'] == set(osm), 'OSM match coverage is incomplete')
    grouped_source, grouped_osm, valid_effective = set(), set(), set()
    matched_osm_ids = {osm[key] for key in matched_osm}
    for row in records['groups']:
        if row.get('side') == 'source':
            members = row.get('members', [])
            _require(len(members) >= 2 and len(members) == len(set(members)), 'Source duplicate group needs distinct members')
            _require(set(members) <= source.keys() and row.get('key') in members, 'Unknown source group member')
            _require(len({source[key] for key in members}) == 1, 'Source group crosses dataset namespaces')
            _require(not grouped_source.intersection(members), 'Overlapping source groups')
            grouped_source.update(members)
        elif row.get('side') == 'osm':
            members = row.get('members', [])
            member_ids = [member.get('node_id') for member in members]
            roles = [member.get('member_role') for member in members]
            kind = row.get('stop_kind')
            expected_roles = {'single': ['single'], 'pair': ['pair_a', 'pair_b'], 'trio': ['trio_middle', 'trio_side', 'trio_side']}
            _require(kind in expected_roles and sorted(roles) == sorted(expected_roles[kind]), 'Invalid OSM stop-unit roles')
            _require(len(member_ids) == len(set(member_ids)) and set(member_ids) <= osm_by_id.keys(), 'Unknown or duplicate OSM group member')
            _require(row.get('representative_node_id') in member_ids, 'Unknown OSM group representative')
            _require(not grouped_osm.intersection(member_ids), 'Overlapping OSM stop units')
            grouped_osm.update(member_ids)
            if kind == 'trio':
                sides = {member['node_id'] for member in members if member['member_role'] == 'trio_side'}
                if sides <= matched_osm_ids:
                    valid_effective.update(member['node_id'] for member in members if member['member_role'] == 'trio_middle')
        else:
            raise InvalidResult('Unknown group side')
    _require(grouped_osm == set(osm_by_id), 'OSM stop-unit coverage is incomplete')
    _require(effective == valid_effective, 'Effective-match status disagrees with trio side matches')
    problem_ids, actual_match_problems = set(), set()
    source_unmatched_problems, osm_unmatched_problems = set(), set()
    for row in records['problems']:
        _problem(row)
        key, left, right = row.get('problem_id'), row.get('source_keys', []), row.get('osm_ids', [])
        _require(isinstance(key, str) and key and key not in problem_ids, 'Missing or duplicate problem ID')
        _require((left or right) and set(left) <= source.keys() and set(right) <= osm_by_id.keys(), 'Problem references unknown entities')
        problem_ids.add(key)
        actual_match_problems.update((row['problem_type'], row['priority'], source_key, osm_id) for source_key in left for osm_id in right)
        if row['problem_type'] == 'unmatched':
            source_unmatched_problems.update(left)
            osm_unmatched_problems.update(right)
    _require(expected_match_problems <= actual_match_problems, 'Matched problem is absent from complete detection results')
    _require(source_unmatched_problems == unmatched['source'], 'Source unmatched detection coverage is incomplete')
    _require(osm_unmatched_problems == {osm[key] for key in unmatched['osm']} - effective, 'OSM unmatched detection coverage is incomplete')
    for section in ('routes', 'extensions'):
        values = {}
        for row in records[section]:
            key = row.get('kind')
            _require(isinstance(key, str) and key and key not in values, f'Invalid {section} entry')
            values[key] = row.get('value')
        if section == 'routes':
            _validate_routes(values, set(source))
        else:
            evidence = values.get('route_evidence') or {}
            _require(set(evidence.get('source', {})) <= source.keys(), 'Route evidence references unknown source stop')
            _require(set(evidence.get('osm', {})) <= osm_by_id.keys(), 'Route evidence references unknown OSM stop')
            duplicates = values.get('duplicate_osm_group_map') or {}
            for key, members in duplicates.items():
                _require(key in members and len(set(members)) >= 2 and set(members) <= osm_by_id.keys(), 'Unknown OSM discrepancy group member')
    for row in records['diagnostics']:
        _require(isinstance(row, dict) and isinstance(row.get('code'), str), 'Diagnostic needs a stable code')


def validate_output(result):
    """Reject incomplete normalized outputs before serialization can hide omissions."""
    from .bundle import _sections, _json_value
    source = {node.key: node for node in result.all_source_nodes}
    osm = {node.key: node for node in result.all_osm_nodes}
    _require(len(source) == len(result.all_source_nodes), 'Duplicate source entity declaration')
    _require(len(osm) == len(result.all_osm_nodes), 'Duplicate OSM entity declaration')
    for row in result.matched:
        _require(row.source_node.key in source and row.osm_node.key in osm, 'Matched entity missing from complete entity lists')
        _require(row.source_node == source[row.source_node.key] and row.osm_node == osm[row.osm_node.key], 'Matched entity disagrees with normalized record')
    _require({node.key for node in result.unmatched_source} <= source.keys(), 'Unmatched source missing from complete entity list')
    _require({node.key for node in result.unmatched_osm} <= osm.keys(), 'Unmatched OSM missing from complete entity list')
    for key, members in result.duplicate_key_map.items():
        _require(key in members and set(members) <= source.keys(), 'Unknown source duplicate-map member')
        _require(all(set(result.duplicate_key_map.get(member, [])) == set(members) for member in members), 'Source duplicate map is incomplete or inconsistent')
    _require(set(result.source_isolated_keys) <= {node.key for node in result.unmatched_source}, 'Unknown isolated source key')
    _require(set(result.isolated_osm_ids) <= {node.node_id for node in result.unmatched_osm}, 'Unknown isolated OSM ID')
    _require(set(result.effectively_matched_osm_ids) <= {node.node_id for node in result.unmatched_osm}, 'Unknown effectively matched OSM ID')
    validate_records({section: (_json_value(row) for row in rows) for section, rows in _sections(result).items()})
    return result


def validate_bundle(directory):
    """Verify checksums, counts and semantic coverage of a serialized producer bundle."""
    from .bundle import SCHEMA_VERSION, SECTIONS
    directory = Path(directory)
    try:
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        _require(isinstance(manifest, dict), 'Invalid manifest object')
        _require(isinstance(manifest.get('metadata'), dict), 'Missing result metadata')
        _require(type(manifest.get('schema_version')) is int and manifest['schema_version'] == SCHEMA_VERSION, 'Unsupported result schema version')
        _require(set(manifest.get('files', {})) == set(SECTIONS), 'Incomplete result manifest')
        _require(isinstance(manifest.get('run_id'), str) and manifest['run_id'], 'Missing run ID')
        def rows(section):
            info = manifest['files'][section]
            name = f'{section}.jsonl.gz'
            _require(info.get('name') == name, 'Unexpected result filename')
            path = directory / name
            _require(path.is_file() and not path.is_symlink(), 'Missing result file')
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            _require(path.stat().st_size == info.get('bytes') and digest.hexdigest() == info.get('sha256'), f'Checksum or size mismatch: {section}')
            count = 0
            with gzip.open(path, 'rt', encoding='utf-8') as handle:
                for line in handle:
                    value = json.loads(line, parse_constant=_reject_nonfinite)
                    _require(isinstance(value, dict), 'Result row must be an object')
                    count += 1
                    yield value
            _require(type(info.get('rows')) is int and count == info['rows'], f'Row count mismatch: {section}')
        validate_records({section: rows(section) for section in SECTIONS})
        return manifest
    except InvalidResult:
        raise
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise InvalidResult(f'Cannot read complete result bundle: {exc}') from exc
