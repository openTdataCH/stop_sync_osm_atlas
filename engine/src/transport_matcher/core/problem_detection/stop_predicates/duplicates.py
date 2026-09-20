"""Duplicates problem predicate — flags redundant source or OSM entries."""

from __future__ import annotations

from transport_matcher.core.problem_detection.result import ProblemResult
from transport_matcher.core.problem_detection.context import ProblemContext


from transport_matcher.core.models import MatchRecord, SourceStop, OsmNode

def duplicates_problem(ctx: ProblemContext, record: MatchRecord | SourceStop | OsmNode) -> list[ProblemResult]:
    
    if isinstance(record, MatchRecord):
        osm_node_id = record.osm_node.node_id
        key = record.source_node.key
    elif isinstance(record, SourceStop):
        osm_node_id = None
        key = record.key
    else:
        osm_node_id = record.node_id
        key = None

    # Prefer OSM-side duplicates (P3) over source-side (P2) — only flag one
    if osm_node_id and str(osm_node_id) in ctx.duplicate_osm_node_ids:
        return [ProblemResult(
            problem_type='duplicates', priority=3, has_osm_duplicate=True,
        )]

    if key and str(key) in ctx.duplicate_key_map and str(key) not in ctx.handled_duplicate_keys:
        return [ProblemResult(
            problem_type='duplicates', priority=2, has_source_duplicate=True,
        )]

    return []
