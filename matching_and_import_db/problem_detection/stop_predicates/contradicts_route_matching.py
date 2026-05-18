"""Route contradiction predicate for matched ATLAS↔OSM stop pairs."""

from __future__ import annotations

from matching_and_import_db.models import MatchRecord, AtlasNode, OsmNode
from matching_and_import_db.problem_detection.context import ProblemContext
from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.utils.route_matching import classify_route_alignment


def contradicts_route_matching_problem(
    ctx: ProblemContext,
    record: MatchRecord | AtlasNode | OsmNode,
) -> list[ProblemResult]:
    if not isinstance(record, MatchRecord):
        return []

    atlas_route_evidence = ctx.atlas_route_evidence_by_sloid.get(str(record.atlas_node.sloid), {'gtfs': []})
    osm_node_routes = ctx.osm_node_routes.get(str(record.osm_node.node_id), [])
    osm_direction_names = ctx.osm_name_dirs.get(str(record.osm_node.node_id), set())

    alignment = classify_route_alignment(
        atlas_route_evidence,
        osm_node_routes,
        osm_direction_names,
    )
    if alignment in {'token_contradiction', 'direction_contradiction'}:
        return [ProblemResult(problem_type='contradicts_route_matching', priority=2)]
    return []