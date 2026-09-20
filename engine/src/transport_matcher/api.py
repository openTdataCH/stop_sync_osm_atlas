"""Public in-memory API: the same complete pipeline serves every data profile."""
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json

from .core.models import MatchingOutput, OsmStopUnitRecord, OsmStopMemberRecord, DetectedProblem
from .core.state import SourceState, OsmState
from .core.pipeline import MatchingContext, run_pipeline
from .core.route_state import RouteState
from .core.predicates.exact_matching import ExactReferencePredicate
from .core.predicates.name_matching import NameMatchPredicate
from .core.predicates.trio_distance_matching import TrioDistanceMatchingPredicate
from .core.predicates.distance_matching import GroupProximityPredicate, LocalRefDistancePredicate, NearestDistancePredicate
from .core.predicates.route_matching_gtfs import RouteMatchPredicate
from .core.problem_detection.context import ProblemContext
from .core.problem_detection.pipeline import STOP_PROBLEM_PIPELINE
from .core.utils.common import haversine_distance
from .profiles import MatchingProfile


def _predicates(profile):
    factories = {
        'trio': TrioDistanceMatchingPredicate,
        'exact': ExactReferencePredicate,
        'name': NameMatchPredicate,
        'route': RouteMatchPredicate,
        'group_proximity': GroupProximityPredicate,
        'long_distance_group_proximity': lambda: GroupProximityPredicate(
            max_distance=profile.long_distance,
            match_type_prefix='long_distance_group_proximity',
            notes_label='Conflict-free max-cardinality long-distance group proximity match',
            name='LongDistanceGroupProximityPredicate',
        ),
        'local_ref': LocalRefDistancePredicate,
        'nearest_single': lambda: NearestDistancePredicate(mode='single', pass_label='first'),
        'nearest_ratio': lambda: NearestDistancePredicate(mode='ratio', pass_label='first'),
        'nearest_second': lambda: NearestDistancePredicate(mode='single', pass_label='second'),
    }
    unknown = set(profile.predicate_names) - factories.keys()
    if unknown:
        raise ValueError(f'Unknown predicates: {sorted(unknown)}')
    return [factories[name]() for name in profile.predicate_names]


def _build_groups(source, osm, profile):
    if not profile.osm_grouping:
        return
    nodes = [node for node in source.get_all_rows_as_dict().values() if profile.allows_station_reference(node)]
    by_reference = defaultdict(list)
    for node in nodes:
        by_reference[node.station_ref].append(node)
    safe_references = set()
    for reference, source_nodes in by_reference.items():
        osm_nodes = [osm._to_osm_node(entry) for entry in osm._uic_ref_dict.get(reference, [])]
        # A raw station value can occur in unrelated feeds/scopes. Do not
        # pre-group such buckets; scoped predicates can still resolve links.
        if len({node.namespace for node in source_nodes}) == 1 and all(
            profile.station_references_compatible(source_node, osm_node)
            for source_node in source_nodes for osm_node in osm_nodes
        ):
            safe_references.add(reference)
    nodes = [node for node in nodes if node.station_ref in safe_references]
    counts = Counter(node.station_ref for node in nodes if node.station_ref)
    names = {node.name: node.station_ref for node in nodes if node.name and node.station_ref}
    distances = defaultdict(list)
    for node in nodes:
        candidates = osm._uic_ref_dict.get(node.station_ref, [])
        if candidates:
            distances[node.station_ref].append(min(
                haversine_distance(node.lat, node.lon, osm_node['lat'], osm_node['lon'])
                for osm_node in candidates
            ))
    osm.build_groups(dict(counts), names, dict(distances), policy=profile.grouping)


def _stop_units(osm):
    units, grouped = [], set()
    for representative, (kind, siblings) in osm._group_siblings.items():
        if kind.startswith('osm_pair_') and siblings:
            members = [OsmStopMemberRecord(representative, 'pair_a'), OsmStopMemberRecord(siblings[0].node_id, 'pair_b')]
            stop_kind = 'pair'
        elif kind == 'osm_trio':
            middle, first, second = osm.get_trio_for_representative(representative)
            members = [OsmStopMemberRecord(middle, 'trio_middle'), OsmStopMemberRecord(first, 'trio_side'), OsmStopMemberRecord(second, 'trio_side')]
            stop_kind = 'trio'
        else:
            continue
        units.append(OsmStopUnitRecord(stop_kind, kind, representative, members))
        grouped.update(member.node_id for member in members)
    for node in osm.get_all_nodes():
        if node.node_id not in grouped:
            units.append(OsmStopUnitRecord('single', None, node.node_id, [OsmStopMemberRecord(node.node_id, 'single')]))
    return units


def _problem(problem, source_keys=(), osm_ids=(), evidence=None):
    affected = [problem.problem_type, sorted(source_keys), sorted(osm_ids)]
    stable_id = sha256(json.dumps(affected, separators=(',', ':')).encode()).hexdigest()[:24]
    return DetectedProblem(
        stable_id, problem.problem_type, problem.priority, tuple(source_keys), tuple(osm_ids),
        {'has_source_duplicate': problem.has_source_duplicate,
         'has_osm_duplicate': problem.has_osm_duplicate, **(evidence or {})},
    )


def _detect(output, profile, route_state):
    ctx = ProblemContext.build(output)
    ctx.profile = profile
    ctx.route_state = route_state
    output.duplicate_osm_group_map = ctx.duplicate_osm_group_map
    matched_osm = {record.osm_node.node_id for record in output.matched}
    for unit in output.osm_stop_units:
        if unit.stop_kind == 'trio':
            sides = [m.node_id for m in unit.members if m.member_role == 'trio_side']
            if len(sides) == 2 and all(node_id in matched_osm for node_id in sides):
                output.effectively_matched_osm_ids.extend(m.node_id for m in unit.members if m.member_role == 'trio_middle')
    problems = {}
    for record in output.matched:
        record.evaluate_matched_problems(ctx, STOP_PROBLEM_PIPELINE)
        for result in record.problems:
            p = _problem(result, [record.source_node.key], [record.osm_node.node_id], record.evidence)
            problems[p.problem_id] = p
    for node in output.unmatched_source:
        nearest = ctx.nearest_osm_distance(node.lat, node.lon)
        if nearest is None or nearest > profile.isolation_radius:
            output.source_isolated_keys.append(node.key)
        for predicate in STOP_PROBLEM_PIPELINE:
            for result in predicate(ctx, node):
                p = _problem(result, [node.key], evidence={'nearest_osm_distance_m': nearest})
                problems[p.problem_id] = p
    for node in output.unmatched_osm:
        nearest = ctx.nearest_source_distance(node.lat, node.lon)
        if nearest is None or nearest > profile.isolation_radius:
            output.isolated_osm_ids.append(node.node_id)
        if node.node_id in output.effectively_matched_osm_ids:
            continue
        for predicate in STOP_PROBLEM_PIPELINE:
            for result in predicate(ctx, node):
                p = _problem(result, osm_ids=[node.node_id], evidence={'nearest_source_distance_m': nearest})
                problems[p.problem_id] = p
    output.problems = sorted(problems.values(), key=lambda p: (p.priority, p.problem_type, p.problem_id))


def match(source, osm, profile=None, route_evidence=None):
    """Match normalized records, returning matches, groups, unmatched entities and problems.

    Inputs are copied into fresh per-run states, so repeated calls and concurrent
    datasets do not inherit allocation or route state. Adapters are responsible for
    parser diagnostics and explicit namespace-scoped route identifiers.
    ``route_evidence`` may contain ``source``, ``osm``, and ``route_state`` overrides.
    """
    profile = profile or MatchingProfile()
    route_evidence = route_evidence or {}
    if isinstance(source, SourceState):
        source = SourceState(source.get_all_rows_as_dict().values(), source.duplicate_key_map,
                             route_evidence.get('source', source._route_evidence_by_key))
    else:
        source = SourceState(source, route_evidence_by_key=route_evidence.get('source'))
    if isinstance(osm, OsmState):
        osm = OsmState.from_records(osm.get_all_nodes(), node_routes=route_evidence.get('osm', osm._node_routes),
                                    name_dirs=osm.name_dirs, uic_dirs=osm.uic_dirs, station_ref_tag=profile.osm_station_ref_tag,
                                    preserve_name_alias_multiplicity=profile.preserve_name_alias_multiplicity)
    else:
        osm = OsmState.from_records(osm, node_routes=route_evidence.get('osm'), station_ref_tag=profile.osm_station_ref_tag,
                                    preserve_name_alias_multiplicity=profile.preserve_name_alias_multiplicity)
    route_state = route_evidence.get('route_state') or RouteState()
    _build_groups(source, osm, profile)
    ctx = MatchingContext(source=source, osm=osm, max_distance=profile.max_distance,
                          profile=profile, route_state=route_state)
    result = run_pipeline(_predicates(profile), ctx)
    output = MatchingOutput(
        matched=result.matched, unmatched_source=result.unmatched_source,
        unmatched_osm=result.unmatched_osm, duplicate_key_map=source.duplicate_key_map,
        osm_stop_units=_stop_units(osm), all_source_nodes=list(source.get_all_rows_as_dict().values()),
        all_osm_nodes=osm.get_all_nodes(), source_route_evidence_by_key=source._route_evidence_by_key,
        osm_node_routes=osm._node_routes, osm_name_dirs=osm.name_dirs, profile_id=profile.profile_id,
        diagnostics=list(ctx.diagnostics),
    )
    has_source_routes = any(value.get('gtfs') for value in source._route_evidence_by_key.values())
    has_osm_routes = bool(osm._node_routes or osm.name_dirs)
    if not (has_source_routes and has_osm_routes):
        output.diagnostics.append({'code': 'route_evidence_unavailable', 'stage': 'route_matching',
                                   'reason': 'Source or OSM route evidence is absent; route-dependent checks skipped.'})
    _detect(output, profile, route_state)
    output.metadata = {
        'profile': asdict(profile),
        'capabilities': [cap for cap in profile.capabilities if cap != 'routes' or (has_source_routes and has_osm_routes)],
        'summary': {'source_stops': len(output.all_source_nodes), 'osm_elements': len(output.all_osm_nodes),
                    'matches': len(output.matched), 'unmatched_source': len(output.unmatched_source),
                    'unmatched_osm': len(output.unmatched_osm), 'problems': len(output.problems)},
    }
    return output
