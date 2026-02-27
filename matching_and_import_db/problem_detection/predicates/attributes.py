"""Attributes problem predicate — flags inconsistencies between matched ATLAS/OSM pairs."""

from __future__ import annotations

from typing import Optional

from matching_and_import_db.problem_detection.result import ProblemResult
from matching_and_import_db.problem_detection.context import (
    ProblemContext,
    ENABLE_OPERATOR_MISMATCH_CHECK,
    ENABLE_NAME_MISMATCH_CHECK,
    ENABLE_UIC_MISMATCH_CHECK,
    ENABLE_LOCAL_REF_MISMATCH_CHECK,
)


def _both_present(a: str, b: str) -> bool:
    return bool(a) and bool(b)


def _compute_priority(stop: dict) -> Optional[int]:
    """Return highest-severity priority for attribute mismatches, or None."""

    # P1: UIC mismatch
    if ENABLE_UIC_MISMATCH_CHECK:
        atlas_uic = str(stop.get('number', '') or '').strip()
        osm_uic = str(stop.get('osm_uic_ref', '') or '').strip()
        if _both_present(atlas_uic, osm_uic) and atlas_uic != osm_uic:
            return 1

    # P1: Name mismatch (designation_official vs uic_name)
    if ENABLE_NAME_MISMATCH_CHECK:
        atlas_name = str(
            stop.get('csv_designation_official', '') or
            stop.get('designationOfficial', '') or ''
        ).strip()
        osm_name = str(stop.get('osm_uic_name', '') or '').strip()
        if _both_present(atlas_name, osm_name) and atlas_name.lower() != osm_name.lower():
            return 1

    # P2: Local ref mismatch
    if ENABLE_LOCAL_REF_MISMATCH_CHECK:
        atlas_ref = str(
            stop.get('csv_designation', '') or
            stop.get('designation', '') or ''
        ).strip()
        osm_ref = str(stop.get('osm_local_ref', '') or '').strip()
        if _both_present(atlas_ref, osm_ref) and atlas_ref.lower() != osm_ref.lower():
            return 2

    # P3: Operator mismatch
    if ENABLE_OPERATOR_MISMATCH_CHECK:
        atlas_op = str(stop.get('csv_business_org_abbr', '') or '').strip()
        osm_op = str(stop.get('osm_operator', '') or '').strip()
        if _both_present(atlas_op, osm_op) and atlas_op.lower() != osm_op.lower():
            return 3

    return None


def attributes_problem(ctx: ProblemContext, stop: dict) -> list[ProblemResult]:
    if stop.get('stop_type') != 'matched':
        return []

    priority = _compute_priority(stop)
    if priority is None:
        return []

    return [ProblemResult(problem_type='attributes', priority=priority)]
