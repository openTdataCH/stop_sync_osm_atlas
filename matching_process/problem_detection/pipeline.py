"""
Problem detection pipeline runner.

Mirrors the matching pipeline pattern: a list of predicates is executed
sequentially, each returning zero or more ProblemResult objects that the
caller converts into ORM Problem objects.
"""

from __future__ import annotations

import logging
from typing import Callable

from matching_process.problem_detection.context import ProblemContext
from matching_process.problem_detection.result import ProblemResult
from matching_process.problem_detection.predicates import (
    distance_problem,
    attributes_problem,
    unmatched_problem,
    duplicates_problem,
)

logger = logging.getLogger(__name__)

# Type alias for predicate signature
ProblemPredicate = Callable[[ProblemContext, dict], list[ProblemResult]]


def run_problem_pipeline(
    predicates: list[ProblemPredicate],
    ctx: ProblemContext,
    stop: dict,
) -> list[ProblemResult]:
    """Run every predicate against a single stop record, collecting results."""
    results: list[ProblemResult] = []
    for predicate in predicates:
        try:
            results.extend(predicate(ctx, stop))
        except Exception:
            logger.warning("Predicate %s failed for stop %s",
                           predicate.__name__, stop.get('sloid') or stop.get('osm_node_id'),
                           exc_info=True)
    return results


# Default pipeline — order doesn't matter since predicates are independent
STOP_PROBLEM_PIPELINE: list[ProblemPredicate] = [
    distance_problem,
    attributes_problem,
    unmatched_problem,
    duplicates_problem,
]
