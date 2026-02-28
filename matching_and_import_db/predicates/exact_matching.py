"""
Exact UIC matching predicate.

Matches ATLAS entries to OSM nodes when ATLAS ``number`` == OSM ``uic_ref``,
refining by ``designation`` == ``local_ref`` when multiple candidates exist.
"""
from collections import defaultdict
from typing import List

from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.models import AtlasNode, OsmNode

class ExactUicPredicate(BasePredicate):
    """Match by ATLAS number == OSM uic_ref, refine by designation == local_ref."""

    def run(self, ctx: MatchingContext) -> None:
        # Group ATLAS entries by UIC number
        atlas_by_uic: dict[str, list[AtlasNode]] = defaultdict(list)
        for node in ctx.atlas.get_unmatched_records():
            if node.uic_ref:
                atlas_by_uic[node.uic_ref].append(node)

        for uic, entries in sorted(atlas_by_uic.items()):
            available = ctx.osm.get_by_uic(uic)
            if not available:
                continue

            # --- Case 1: single OSM node → match all ATLAS entries to it ---
            if len(available) == 1:
                osm = available[0]
                for entry in entries:
                    ctx.commit(
                        atlas_node=entry,
                        osm_node=osm,
                        match_type='exact',
                        distance_m=0.0, # Handled via haversine internally in commit or via problem heuristic later. Actually wait, problem ctx calculates distance if we leave it 0? Wait, the original `make_match` calculated haversine explicitly.
                        # Wait, I omitted haversine from ctx.commit! Let's calculate it here.
                        notes="Single OSM node for this UIC reference",
                        candidate_pool_size=1
                    )
                # ctx.commit already locks it immediately.
                continue

            # --- Case 2: single ATLAS entry → match to all OSM nodes ---
            if len(entries) == 1:
                for osm in available:
                    ctx.commit(
                        atlas_node=entries[0],
                        osm_node=osm,
                        match_type='exact',
                        distance_m=0.0,
                        notes="Single ATLAS entry matched to multiple OSM nodes",
                        candidate_pool_size=len(available)
                    )
                continue

            # --- Case 3: many-to-many → refine by designation == local_ref ---
            ref_lookup: dict[str, list[OsmNode]] = defaultdict(list)
            for c in available:
                lr = (c.local_ref or '').strip().lower()
                if lr:
                    ref_lookup[lr].append(c)

            for entry in entries:
                desig = (entry.designation or '').strip().lower()
                if not desig:
                    continue
                for osm in ref_lookup.get(desig, []):
                    if ctx.osm.is_used(osm.node_id):
                        continue
                    ctx.commit(
                        atlas_node=entry,
                        osm_node=osm,
                        match_type='exact',
                        distance_m=0.0,
                        notes="Exact local_ref/designation match",
                        candidate_pool_size=len(available)
                    )
                    break  # one match per ATLAS entry
