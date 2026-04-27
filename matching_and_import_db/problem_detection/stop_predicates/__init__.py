"""Stop problem predicates — each function has signature (ctx, stop) -> list[ProblemResult]."""

from matching_and_import_db.problem_detection.stop_predicates.distance import distance_problem
from matching_and_import_db.problem_detection.stop_predicates.attributes import attributes_problem
from matching_and_import_db.problem_detection.stop_predicates.unmatched import unmatched_problem
from matching_and_import_db.problem_detection.stop_predicates.duplicates import duplicates_problem

__all__ = [
    "distance_problem",
    "attributes_problem",
    "unmatched_problem",
    "duplicates_problem",
]
