"""
Problem Detection Package

Predicate-based pipeline for detecting and prioritizing data quality issues
in matched/unmatched ATLAS↔OSM stop data.

Usage:
    from matching_process.problem_detection import ProblemContext, run_problem_pipeline, STOP_PROBLEM_PIPELINE

    ctx = ProblemContext.build(base_data, duplicate_sloid_map)
    problems = run_problem_pipeline(STOP_PROBLEM_PIPELINE, ctx, stop_record)
"""

from matching_process.problem_detection.context import ProblemContext
from matching_process.problem_detection.pipeline import run_problem_pipeline, STOP_PROBLEM_PIPELINE

__all__ = [
    "ProblemContext",
    "run_problem_pipeline",
    "STOP_PROBLEM_PIPELINE",
]
