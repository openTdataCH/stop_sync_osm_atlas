"""Route contradiction predicate for matched source↔OSM stop pairs."""

from __future__ import annotations

from transport_matcher.core.models import MatchRecord, SourceStop, OsmNode
from transport_matcher.core.problem_detection.context import ProblemContext
from transport_matcher.core.problem_detection.result import ProblemResult
from transport_matcher.core.utils.route_matching import classify_route_alignment


def contradicts_route_matching_problem(
    ctx: ProblemContext,
    record: MatchRecord | SourceStop | OsmNode,
) -> list[ProblemResult]:
    if not isinstance(record, MatchRecord):
        return []

    source_route_evidence = ctx.source_route_evidence_by_key.get(str(record.source_node.key), {'gtfs': []})
    osm_node_routes = ctx.osm_node_routes.get(str(record.osm_node.node_id), [])
    osm_direction_names = ctx.osm_name_dirs.get(str(record.osm_node.node_id), set())

    alignment = classify_route_alignment(
        source_route_evidence,
        osm_node_routes,
        osm_direction_names,
        route_state=ctx.route_state,
    )
    if alignment in {'token_contradiction', 'direction_contradiction'}:
        return [ProblemResult(problem_type='contradicts_route_matching', priority=2)]
    return []