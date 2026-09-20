"""Read the public result contract without importing the matching engine.

This implementation deliberately belongs to the consumer. The wire schema,
documented in engine/RESULT_FORMAT.md, is the only shared dependency.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

SUPPORTED_SCHEMA_VERSION = 1
SECTIONS = (
    "source_stops", "osm_nodes", "matches", "unmatched", "groups",
    "problems", "routes", "extensions", "diagnostics",
)


class InvalidBundle(ValueError):
    """The run is incomplete or is not a supported result schema."""


def _require(condition, message):
    if not condition:
        raise InvalidBundle(message)


def _reject_nonfinite(value):
    raise InvalidBundle(f"Non-finite JSON value: {value}")


def _json(handle):
    return json.load(handle, parse_constant=_reject_nonfinite)


def _position(row):
    lat, lon = row.get("lat"), row.get("lon")
    return (
        type(lat) in (int, float) and type(lon) in (int, float)
        and math.isfinite(lat) and math.isfinite(lon)
        and -90 <= lat <= 90 and -180 <= lon <= 180
    )


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
                raise InvalidBundle('Invalid source variants in stop call') from exc
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


def _validate_records(records):
    """Validate iterable wire sections; keep identity indexes rather than full snapshots."""
    source, osm, osm_by_id = {}, {}, {}
    for row in records['source_stops']:
        key, namespace, source_id = row.get('key'), row.get('namespace'), row.get('source_id')
        _require(isinstance(namespace, str) and namespace and ':' not in namespace, 'Invalid source namespace')
        _require(isinstance(source_id, str) and source_id and key == f'{namespace}:{source_id}', 'Inconsistent source key')
        _require(key not in source, 'Duplicate source key')
        _require(_position(row), 'Invalid coordinates for source stop')
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
            _require(set(member_ids) <= osm_by_id.keys(), 'Unknown OSM group member')
            _require(len(member_ids) == len(set(member_ids)), 'Duplicate OSM group member')
            _require(row.get('representative_node_id') in member_ids, 'Unknown OSM group representative')
            _require(not grouped_osm.intersection(member_ids), 'Overlapping OSM stop units')
            grouped_osm.update(member_ids)
            if kind == 'trio':
                sides = {member['node_id'] for member in members if member['member_role'] == 'trio_side'}
                if sides <= matched_osm_ids:
                    valid_effective.update(member['node_id'] for member in members if member['member_role'] == 'trio_middle')
        else:
            raise InvalidBundle('Unknown group side')
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
            _require('value' in row, f'Missing {section} entry value')
            values[key] = row.get('value')
        if section == 'routes':
            _validate_routes(values, set(source))
        else:
            for name in ('route_evidence', 'duplicate_osm_group_map', 'quality_metrics', 'gtfs_atlas_stats', 'atlas_filtering'):
                _require(name not in values or isinstance(values[name], dict), f'Invalid {name} extension')
            for name in ('gtfs_stops', 'gtfs_atlas_state'):
                _require(name not in values or (isinstance(values[name], list) and all(isinstance(row, dict) for row in values[name])), f'Invalid {name} extension')
            evidence = values.get('route_evidence') or {}
            _require(set(evidence.get('source', {})) <= source.keys(), 'Route evidence references unknown source stop')
            _require(set(evidence.get('osm', {})) <= osm_by_id.keys(), 'Route evidence references unknown OSM stop')
            duplicates = values.get('duplicate_osm_group_map') or {}
            for key, members in duplicates.items():
                _require(key in members and len(set(members)) >= 2 and set(members) <= osm_by_id.keys(), 'Unknown OSM discrepancy group member')
    for row in records['diagnostics']:
        _require(isinstance(row, dict) and isinstance(row.get('code'), str), 'Diagnostic needs a stable code')



def validate_records(bundle):
    """Check the wire contract independently, before projection or DB staging."""
    try:
        _require(isinstance(bundle, dict), "Invalid bundle object")
        for section in SECTIONS:
            rows = bundle.get(section)
            _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), f"Invalid {section} records")
        _validate_records(bundle)
        return bundle
    except InvalidBundle:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        raise InvalidBundle(f"Malformed result record: {exc}") from exc


def read_bundle(directory):
    directory = Path(directory).resolve()
    try:
        with (directory / "manifest.json").open(encoding="utf-8") as handle:
            manifest = _json(handle)
        _require(isinstance(manifest, dict), "Invalid manifest object")
        _require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == SUPPORTED_SCHEMA_VERSION, "Unsupported result schema version")
        _require(isinstance(manifest.get("run_id"), str) and manifest["run_id"], "Missing run ID")
        _require(isinstance(manifest.get("metadata"), dict), "Missing result metadata")
        _require(isinstance(manifest.get("files"), dict) and set(manifest["files"]) == set(SECTIONS), "Incomplete result manifest")
        result = {"manifest": manifest}
        for section in SECTIONS:
            info = manifest["files"][section]
            _require(isinstance(info, dict), f"Invalid file descriptor: {section}")
            name = f"{section}.jsonl.gz"
            _require(info.get("name") == name, f"Unexpected filename for {section}")
            path = directory / name
            _require(path.is_file() and not path.is_symlink(), f"Missing result file: {name}")
            _require(path.stat().st_size == info.get("bytes"), f"Incorrect file size: {name}")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            _require(digest.hexdigest() == info.get("sha256"), f"Checksum mismatch: {name}")
            rows = []
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line, parse_constant=_reject_nonfinite)
                    _require(isinstance(row, dict), f"Invalid record in {name}")
                    rows.append(row)
            _require(type(info.get("rows")) is int and len(rows) == info["rows"], f"Row count mismatch: {name}")
            result[section] = rows
        return validate_records(result)
    except InvalidBundle:
        raise
    except (OSError, ValueError, TypeError, KeyError, EOFError, AttributeError, OverflowError) as exc:
        raise InvalidBundle(f"Cannot read complete result bundle: {exc}") from exc
