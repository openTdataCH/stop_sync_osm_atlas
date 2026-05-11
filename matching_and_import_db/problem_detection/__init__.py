"""
Problem Detection Package

Predicate-based pipeline for detecting and prioritizing data quality issues
in matched/unmatched ATLAS↔OSM stop data.

Usage:
    from matching_and_import_db.problem_detection import ProblemContext, evaluate_unmatched_problems, STOP_PROBLEM_PIPELINE

    ctx = ProblemContext.build(base_data)
    problems = evaluate_unmatched_problems(STOP_PROBLEM_PIPELINE, ctx, stop_record)
"""

from matching_and_import_db.problem_detection.context import ProblemContext
from matching_and_import_db.problem_detection.pipeline import evaluate_unmatched_problems, STOP_PROBLEM_PIPELINE

__all__ = [
    "ProblemContext",
    "evaluate_unmatched_problems",
    "STOP_PROBLEM_PIPELINE",
]
