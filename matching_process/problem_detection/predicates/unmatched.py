"""Unmatched problem predicate — prioritizes stops that failed to match."""

from __future__ import annotations

from matching_process.problem_detection.result import ProblemResult
from matching_process.problem_detection.context import ProblemContext, _safe


def _atlas_priority(ctx: ProblemContext, stop: dict) -> int:
    uic = _safe(stop.get('number'))
    lat = _safe(stop.get('wgs84North'))
    lon = _safe(stop.get('wgs84East'))

    nearest = ctx.nearest_osm_distance(lat, lon) if lat is not None and lon is not None else None

    # P1: no OSM nodes carry this UIC at all
    if uic is not None and ctx.osm_count_by_uic.get(str(uic), 0) == 0:
        return 1
    # P1: nearest OSM > 80 m (or no OSM data at all)
    if nearest is None or nearest > 80:
        return 1
    # P2: nearest OSM > 50 m
    if nearest > 50:
        return 2
    # P2: platform count mismatch for this UIC
    if uic is not None:
        key = str(uic)
        if ctx.osm_platform_count_by_uic.get(key, 0) != ctx.atlas_count_by_uic.get(key, 0):
            return 2
    # P3: has nearby candidates
    return 3


def _osm_priority(ctx: ProblemContext, stop: dict) -> int:
    tags = stop.get('tags', {}) if isinstance(stop.get('tags', {}), dict) else {}
    uic = _safe(tags.get('uic_ref'))
    lat = _safe(stop.get('lat'))
    lon = _safe(stop.get('lon'))

    nearest = ctx.nearest_atlas_distance(lat, lon) if lat is not None and lon is not None else None

    # P1: no ATLAS stops carry this UIC
    if uic is not None and ctx.atlas_count_by_uic.get(str(uic), 0) == 0:
        return 1
    # P2: nearest ATLAS > 50 m (or none)
    if nearest is None or nearest > 50:
        return 2
    # P2: platform count mismatch
    if uic is not None:
        key = str(uic)
        if ctx.osm_platform_count_by_uic.get(key, 0) != ctx.atlas_count_by_uic.get(key, 0):
            return 2
    # P3
    return 3


def unmatched_problem(ctx: ProblemContext, stop: dict) -> list[ProblemResult]:
    stop_type = stop.get('stop_type')

    if stop_type == 'atlas_unmatched':
        return [ProblemResult(problem_type='unmatched', priority=_atlas_priority(ctx, stop))]
    if stop_type == 'osm_unmatched':
        return [ProblemResult(problem_type='unmatched', priority=_osm_priority(ctx, stop))]

    return []
