"""Duplicates problem predicate — flags redundant ATLAS or OSM entries."""

from __future__ import annotations

from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.problem_detection.context import ProblemContext


from matching_and_import_db.models import MatchRecord, AtlasNode, OsmNode

def duplicates_problem(ctx: ProblemContext, record: MatchRecord | AtlasNode | OsmNode) -> list[ProblemResult]:
    
    if isinstance(record, MatchRecord):
        osm_node_id = record.osm_node.node_id
        sloid = record.atlas_node.sloid
    elif isinstance(record, AtlasNode):
        osm_node_id = None
        sloid = record.sloid
    else:
        osm_node_id = record.node_id
        sloid = None

    # Prefer OSM-side duplicates (P3) over ATLAS-side (P2) — only flag one
    if osm_node_id and str(osm_node_id) in ctx.duplicate_osm_node_ids:
        return [ProblemResult(
            problem_type='duplicates', priority=3, has_osm_duplicate=True,
        )]

    if sloid and str(sloid) in ctx.duplicate_sloid_map and str(sloid) not in ctx.handled_duplicate_sloids:
        return [ProblemResult(
            problem_type='duplicates', priority=2, has_atlas_duplicate=True,
        )]

    return []
