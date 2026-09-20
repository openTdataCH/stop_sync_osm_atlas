"""
Name-based matching predicate.

Matches source ``name`` against OSM ``name`` / ``uic_name`` /
``gtfs:name``, with an optional refinement by ``platform_code`` == ``local_ref``.
"""
from transport_matcher.core.pipeline import MatchingContext
from transport_matcher.core.predicates import BasePredicate
from transport_matcher.core.utils.common import haversine_distance

class NameMatchPredicate(BasePredicate):
    """Match source name against OSM name index."""

    def run(self, ctx: MatchingContext) -> None:
        for entry in ctx.source.get_unmatched_records():
            name = (entry.name or '').strip()
            if not name:
                continue

            candidates = ctx.osm.get_by_name(name)
            if not candidates:
                continue

            osm = None
            if len(candidates) == 1:
                osm = candidates[0]
            else:
                # Refine by platform_code == local_ref
                desig = (entry.platform_code or '').strip().lower()
                if desig:
                    for c in candidates:
                        if (c.local_ref or '').strip().lower() == desig:
                            osm = c
                            break

            if osm:
                dist = haversine_distance(
                    entry.lat, entry.lon,
                    osm.lat, osm.lon
                )
                if ctx.profile.name_match_max_distance is not None and dist > ctx.profile.name_match_max_distance:
                    continue
                ctx.commit(
                    source_node=entry,
                    osm_node=osm,
                    match_type='name',
                    distance_m=dist,
                    notes=f"Name index match ({len(candidates)} candidates)",
                    evidence={'source_name': name, 'candidate_count': len(candidates), 'platform_code': entry.platform_code},
                )
