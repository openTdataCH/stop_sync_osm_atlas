"""
Name-based matching predicate.

Matches ATLAS ``designationOfficial`` against OSM ``name`` / ``uic_name`` /
``gtfs:name``, with an optional refinement by ``designation`` == ``local_ref``.
"""
from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.utils.common import haversine_distance

class NameMatchPredicate(BasePredicate):
    """Match ATLAS designationOfficial against OSM name index."""

    def run(self, ctx: MatchingContext) -> None:
        for entry in ctx.atlas.get_unmatched_records():
            name = (entry.designation_official or '').strip()
            if not name:
                continue

            candidates = ctx.osm.get_by_name(name)
            if not candidates:
                continue

            osm = None
            if len(candidates) == 1:
                osm = candidates[0]
            else:
                # Refine by designation == local_ref
                desig = (entry.designation or '').strip().lower()
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
                ctx.commit(
                    atlas_node=entry,
                    osm_node=osm,
                    match_type='name',
                    distance_m=dist,
                    notes=f"Name index match ({len(candidates)} candidates)",
                )
