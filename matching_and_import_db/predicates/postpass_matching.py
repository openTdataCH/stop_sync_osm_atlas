"""
Post-pass matching predicates.

* **postpass_unique_uic** – match when only one unused OSM node remains for a UIC
* **duplicate_propagation** – propagate matches across ATLAS duplicate groups
"""
import logging

from typing import TYPE_CHECKING
import pandas as pd

from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.utils.common import haversine_distance

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from matching_and_import_db.pipeline import MatchingContext

# ---------------------------------------------------------------------------
# Predicate – unique UIC post-pass
# ---------------------------------------------------------------------------

class PostpassUniqueUicPredicate(BasePredicate):
    """Match when only one unused OSM node remains for a UIC reference."""

    def run(self, ctx: 'MatchingContext') -> None:
        unmatched = ctx.atlas.get_unmatched_records()
        if not unmatched:
            return

        # Group unmatched by UIC using a dict
        from collections import defaultdict
        unmatched_by_uic = defaultdict(list)
        for node in unmatched:
            if node.uic_ref:
                unmatched_by_uic[node.uic_ref].append(node)

        for uic, entries in unmatched_by_uic.items():
            available = ctx.osm.get_by_uic(uic)
            if len(available) != 1:
                continue

            osm = available[0]
            for entry in entries:
                dist = haversine_distance(entry.lat, entry.lon, osm.lat, osm.lon)
                ctx.commit(
                    atlas_node=entry,
                    osm_node=osm,
                    match_type='exact_postpass',
                    distance_m=dist,
                    notes="Post-pass unique-by-UIC consolidation",
                )


# ---------------------------------------------------------------------------
# Predicate – duplicate propagation
# ---------------------------------------------------------------------------

class DuplicatePropagationPredicate(BasePredicate):
    """
    If one sloid in a duplicate group matched, spread that match to the rest.
    """

    def run(self, ctx: 'MatchingContext') -> None:
        logger.info("  Running duplicate_propagation…")

        unmatched = ctx.atlas.get_unmatched_records()

        # Fast ID lookups for completed matches
        sloid_to_match = {m.atlas_node.sloid: m for m in ctx.all_matches}
        all_rows_dict = ctx.atlas.get_all_rows_as_dict()

        for entry in unmatched:
            sloid = entry.sloid
            dup_group_sloids = ctx.atlas.duplicate_sloid_map.get(sloid)
            if not dup_group_sloids:
                continue

            # Is any target in the duplicated SLOID group matched?
            target_match = None
            target_sloid = None
            for cand_sloid in dup_group_sloids:
                if cand_sloid != sloid:
                    m = sloid_to_match.get(cand_sloid)
                    if m:
                        target_match = m
                        target_sloid = cand_sloid
                        break
                        
            if not target_match:
                continue

            # Target is matched! Let's replicate it. Note that `entry` is ALREADY fully hydrated as AtlasNode.
            osm_node = target_match.osm_node

            dist = haversine_distance(entry.lat, entry.lon, osm_node.lat, osm_node.lon)
            ctx.commit(
                atlas_node=entry,
                osm_node=osm_node,
                match_type='duplicate_propagation',
                distance_m=dist,
                notes=f"Propagated from duplicated sloid: {target_sloid}",
            )
