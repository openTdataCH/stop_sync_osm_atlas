"""Problem predicates — each function has signature (ctx, stop) -> list[ProblemResult]."""

from matching_process.problem_detection.predicates.distance import distance_problem
from matching_process.problem_detection.predicates.attributes import attributes_problem
from matching_process.problem_detection.predicates.unmatched import unmatched_problem
from matching_process.problem_detection.predicates.duplicates import duplicates_problem

__all__ = [
    "distance_problem",
    "attributes_problem",
    "unmatched_problem",
    "duplicates_problem",
]
