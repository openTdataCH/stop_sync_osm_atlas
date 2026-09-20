"""
Pipeline runner for problem detection on unmatched records.

Provides ``STOP_PROBLEM_PIPELINE`` and the public
``evaluate_unmatched_problems`` convenience helper. The engine runtime in
``api.py`` iterates the pipeline directly so it can attach per-node evidence;
matched records use ``MatchRecord.evaluate_matched_problems()``.
"""

import logging

from transport_matcher.core.problem_detection.stop_predicates import (
    distance_problem,
    attributes_problem,
    contradicts_route_matching_problem,
    unmatched_problem,
    duplicates_problem,
)

logger = logging.getLogger(__name__)

STOP_PROBLEM_PIPELINE = [
    distance_problem,
    attributes_problem,
    contradicts_route_matching_problem,
    unmatched_problem,
    duplicates_problem,
]


def evaluate_unmatched_problems(predicates, ctx, stop_dict):
    """Run *predicates* sequentially, collecting ProblemResult lists."""
    results = []
    for predicate in predicates:
        try:
            results.extend(predicate(ctx, stop_dict))
        except Exception:
            logger.warning(
                f"Problem predicate {predicate.__name__} failed",
                exc_info=True,
            )
    return results
