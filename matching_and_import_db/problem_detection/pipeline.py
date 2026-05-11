"""
Pipeline runner for problem detection on unmatched records.

Provides ``evaluate_unmatched_problems`` and ``STOP_PROBLEM_PIPELINE`` used by
``importer.py`` when evaluating problems for unmatched ATLAS / OSM stops
(matched records use ``MatchRecord.evaluate_matched_problems()`` instead).
"""

import logging

from matching_and_import_db.problem_detection.stop_predicates import (
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
