"""Distance problem predicate — flags matched pairs where physical distance exceeds tolerance."""

from __future__ import annotations

from typing import Optional

from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.problem_detection.context import (
    ProblemContext,
    DISTANCE_THRESHOLD_P1,
    DISTANCE_THRESHOLD_P2,
    DISTANCE_THRESHOLD_P3,
)


def _is_sbb(operator: Optional[str]) -> bool:
    if not operator:
        return False
    return str(operator).strip().upper() == 'SBB'


def _compute_priority(distance_m: float, atlas_operator: Optional[str]) -> Optional[int]:
    """Return P1/P2/P3 or None if below all thresholds."""
    is_sbb = _is_sbb(atlas_operator)

    if distance_m > DISTANCE_THRESHOLD_P1 and not is_sbb:
        return 1
    if distance_m > DISTANCE_THRESHOLD_P2 and distance_m <= DISTANCE_THRESHOLD_P1 and not is_sbb:
        return 2
    if distance_m > DISTANCE_THRESHOLD_P2 and is_sbb:
        return 3
    if distance_m > DISTANCE_THRESHOLD_P3 and distance_m <= DISTANCE_THRESHOLD_P2:
        return 3
    return None


from matching_and_import_db.models import MatchRecord, AtlasNode, OsmNode

def distance_problem(ctx: ProblemContext, record: MatchRecord | AtlasNode | OsmNode) -> list[ProblemResult]:
    if not isinstance(record, MatchRecord):
        return []

    if record.distance_m is None:
        return []

    try:
        d = float(record.distance_m)
    except (ValueError, TypeError):
        return []

    # get atlas operator alias from atlas_node
    operator = record.atlas_node.business_org_abbr
    priority = _compute_priority(d, operator)
    if priority is None:
        return []

    return [ProblemResult(problem_type='distance', priority=priority)]
