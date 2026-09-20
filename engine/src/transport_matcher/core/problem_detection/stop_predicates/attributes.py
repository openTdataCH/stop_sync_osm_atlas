"""Attributes problem predicate — flags inconsistencies between matched source/OSM pairs."""

from __future__ import annotations

from typing import Optional

from transport_matcher.core.problem_detection.result import ProblemResult
from transport_matcher.core.problem_detection.context import (
    ProblemContext,
    ENABLE_OPERATOR_MISMATCH_CHECK,
    ENABLE_NAME_MISMATCH_CHECK,
    ENABLE_UIC_MISMATCH_CHECK,
    ENABLE_LOCAL_REF_MISMATCH_CHECK,
)


def _both_present(a: str, b: str) -> bool:
    return bool(a) and bool(b)


from transport_matcher.core.models import MatchRecord, SourceStop, OsmNode

def _compute_priority(record: MatchRecord, ctx: ProblemContext) -> Optional[int]:
    """Return highest-severity priority for attribute mismatches, or None."""

    # P1: UIC mismatch
    if ENABLE_UIC_MISMATCH_CHECK and ctx.profile.allows_station_reference(record.source_node):
        source_uic = str(record.source_node.station_ref or '').strip()
        osm_uic = str(record.osm_node.station_ref or '').strip()
        if _both_present(source_uic, osm_uic) and source_uic != osm_uic:
            return 1

    # P1: Name mismatch (name vs uic_name)
    if ENABLE_NAME_MISMATCH_CHECK:
        source_name = str(record.source_node.name or '').strip()
        osm_name = next((str(record.osm_node.tags.get(tag) or getattr(record.osm_node, tag, '') or '').strip()
                         for tag in ctx.profile.problem_name_tags
                         if record.osm_node.tags.get(tag) or getattr(record.osm_node, tag, '')), '')
        if _both_present(source_name, osm_name) and source_name.lower() != osm_name.lower():
            return 1

    # P2: Local ref mismatch
    if ENABLE_LOCAL_REF_MISMATCH_CHECK:
        source_ref = str(record.source_node.platform_code or '').strip()
        osm_ref = str(record.osm_node.local_ref or '').strip()
        if _both_present(source_ref, osm_ref) and source_ref.lower() != osm_ref.lower():
            return 2

    # P3: Operator mismatch
    if ENABLE_OPERATOR_MISMATCH_CHECK:
        source_op = str(record.source_node.operator or '').strip()
        osm_op = str(record.osm_node.operator or '').strip()
        if _both_present(source_op, osm_op) and source_op.lower() != osm_op.lower():
            return 3

    return None


def attributes_problem(ctx: ProblemContext, record: MatchRecord | SourceStop | OsmNode) -> list[ProblemResult]:
    if not isinstance(record, MatchRecord):
        return []

    priority = _compute_priority(record, ctx)
    if priority is None:
        return []

    return [ProblemResult(problem_type='attributes', priority=priority)]
