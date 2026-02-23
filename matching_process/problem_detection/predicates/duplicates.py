"""Duplicates problem predicate — flags redundant ATLAS or OSM entries."""

from __future__ import annotations

from matching_process.problem_detection.result import ProblemResult
from matching_process.problem_detection.context import ProblemContext


def duplicates_problem(ctx: ProblemContext, stop: dict) -> list[ProblemResult]:
    osm_node_id = stop.get('osm_node_id')
    sloid = stop.get('sloid')

    # Prefer OSM-side duplicates (P3) over ATLAS-side (P2) — only flag one
    if osm_node_id and str(osm_node_id) in ctx.duplicate_osm_node_ids:
        return [ProblemResult(
            problem_type='duplicates', priority=3, has_osm_duplicate=True,
        )]

    if sloid and str(sloid) in ctx.duplicate_sloid_map:
        return [ProblemResult(
            problem_type='duplicates', priority=2, has_atlas_duplicate=True,
        )]

    return []
