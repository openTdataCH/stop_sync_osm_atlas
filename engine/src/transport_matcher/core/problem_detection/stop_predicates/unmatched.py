"""Unmatched problem predicate — prioritizes stops that failed to match."""

from __future__ import annotations

from transport_matcher.core.problem_detection.result import ProblemResult
from transport_matcher.core.problem_detection.context import ProblemContext, _safe


from transport_matcher.core.models import MatchRecord, SourceStop, OsmNode

def _source_priority(ctx: ProblemContext, record: SourceStop) -> int:
    uic = (_safe(record.station_ref) or None) if ctx.profile.allows_station_reference(record) else None
    lat = _safe(record.lat)
    lon = _safe(record.lon)

    nearest = ctx.nearest_osm_distance(lat, lon) if lat is not None and lon is not None else None

    # P1: no OSM nodes carry this UIC at all
    if uic is not None and ctx.osm_count_by_uic.get(str(uic), 0) == 0:
        return 1
    # P1: nearest OSM > 80 m (or no OSM data at all)
    if nearest is None or nearest > ctx.profile.distance_priorities[0]:
        return 1
    # P2: nearest OSM > 50 m
    if nearest > ctx.profile.isolation_radius:
        return 2
    # P2: platform count mismatch for this UIC
    if uic is not None:
        key = str(uic)
        if ctx.osm_platform_count_by_uic.get(key, 0) != ctx.source_count_by_uic.get(key, 0):
            return 2
    # P3: has nearby candidates
    return 3


def _osm_priority(ctx: ProblemContext, record: OsmNode) -> int:
    tags = record.tags or {}
    uic = (_safe(record.station_ref) or None) if ctx.profile.station_reference_matching else None
    lat = _safe(record.lat)
    lon = _safe(record.lon)

    nearest = ctx.nearest_source_distance(lat, lon) if lat is not None and lon is not None else None

    # P1: no source stops carry this UIC
    if uic is not None and ctx.source_count_by_uic.get(str(uic), 0) == 0:
        return 1
    # P2: nearest source > 50 m (or none)
    if nearest is None or nearest > ctx.profile.isolation_radius:
        return 2
    # P2: platform count mismatch
    if uic is not None:
        key = str(uic)
        if ctx.osm_platform_count_by_uic.get(key, 0) != ctx.source_count_by_uic.get(key, 0):
            return 2
    # P3
    return 3


def unmatched_problem(ctx: ProblemContext, record: MatchRecord | SourceStop | OsmNode) -> list[ProblemResult]:
    
    if isinstance(record, SourceStop):
        return [ProblemResult(problem_type='unmatched', priority=_source_priority(ctx, record))]
    if isinstance(record, OsmNode):
        return [ProblemResult(problem_type='unmatched', priority=_osm_priority(ctx, record))]

    return []
