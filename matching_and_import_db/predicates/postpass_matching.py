"""
Post-pass matching predicates.

* **postpass_unique_uic** – match when only one unused OSM node remains for a UIC

Note: duplicate propagation is now handled automatically by ``commit()``
in ``MatchingContext`` via ATLAS pre-grouping (see ``AtlasState.build_duplicate_groups``).
"""
import logging

from typing import TYPE_CHECKING

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
            if len(entries) != 1:
                continue

            osm = available[0]
            if osm.local_ref:
                continue

            entry = entries[0]
            dist = haversine_distance(entry.lat, entry.lon, osm.lat, osm.lon)
            ctx.commit(
                atlas_node=entry,
                osm_node=osm,
                match_type='exact_postpass',
                distance_m=dist,
                notes="Post-pass: 1 ATLAS + 1 OSM (no local_ref) for UIC",
            )
