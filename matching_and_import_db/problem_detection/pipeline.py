"""
Pipeline runner for problem detection on unmatched records.

Provides ``run_problem_pipeline`` and ``STOP_PROBLEM_PIPELINE`` used by
``importer.py`` when evaluating problems for unmatched ATLAS / OSM stops
(matched records use ``MatchRecord.evaluate_problems()`` instead).
"""

import logging

from matching_and_import_db.problem_detection.predicates import (
    distance_problem,
    attributes_problem,
    unmatched_problem,
    duplicates_problem,
)

logger = logging.getLogger(__name__)

STOP_PROBLEM_PIPELINE = [
    distance_problem,
    attributes_problem,
    unmatched_problem,
    duplicates_problem,
]


def run_problem_pipeline(predicates, ctx, stop_dict):
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
