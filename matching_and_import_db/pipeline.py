"""
Pipeline framework for the matching process.

Defines MatchingContext (shared state), PipelineOutput, the sequential runner,
and the make_match() helper used by all predicates.
"""
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

from matching_and_import_db.utils.common import haversine_distance
from matching_and_import_db.models import MatchRecord, PipelineResult

if TYPE_CHECKING:
    from matching_and_import_db.state import AtlasState, OsmState
    from matching_and_import_db.predicates import BasePredicate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass
class MatchingContext:
    """Robust, shared context referencing state managers for the pipeline run."""

    # Encapsulated state managers
    atlas: 'AtlasState'
    osm: 'OsmState'
    
    # Internal Tracking
    all_matches: list['MatchRecord'] = field(default_factory=list)

    # Config
    max_distance: float = 50.0

    def commit(self,
               atlas_node,
               osm_node,
               match_type: str,
               distance_m: float,
               notes: str) -> None:
        """
        Atomically records a match and immediately mutates locks in the State managers
        to prevent subsequent iterations within the same predicate from double-booking nodes.

        Handles group expansion symmetrically for both ATLAS and OSM sides:
        - ATLAS group siblings get ``duplicate_propagation`` records
        - OSM group siblings get ``osm_group_propagation`` records
        """
        # Keep original references for group expansion checks
        atlas_entry = atlas_node
        osm_entry = osm_node
        # Extract raw nodes (works for both entities and raw nodes)
        atlas_node = getattr(atlas_entry, 'representative', atlas_entry)
        osm_node = getattr(osm_entry, 'representative', osm_entry)

        # 1. Primary match record
        record = MatchRecord(
            atlas_node=atlas_node,
            osm_node=osm_node,
            match_type=match_type,
            distance_m=distance_m,
            notes=notes,
        )
        self.all_matches.append(record)

        # 2. Secure locks immediately
        self.atlas.add_matched_sloid(atlas_node.sloid)
        if osm_node.node_id and osm_node.node_id != 'NA':
            self.osm.mark_used(osm_node.node_id)

        # 3. ATLAS group expansion (duplicate_propagation)
        if hasattr(atlas_entry, 'is_group') and atlas_entry.is_group:
            for member in atlas_entry.get_members():
                if member.sloid == atlas_node.sloid:
                    continue
                if member.sloid in self.atlas.matched_ids:
                    continue
                sib_dist = haversine_distance(member.lat, member.lon,
                                              osm_node.lat, osm_node.lon)
                sib_record = MatchRecord(
                    atlas_node=member,
                    osm_node=osm_node,
                    match_type='duplicate_propagation',
                    distance_m=sib_dist,
                    notes=f"Propagated from representative: {atlas_node.sloid}",
                )
                self.all_matches.append(sib_record)
                self.atlas.add_matched_sloid(member.sloid)

        # 4. OSM group expansion (osm_group_propagation)
        if hasattr(osm_entry, 'is_group') and osm_entry.is_group:
            # Trio groups are handled explicitly by TrioDistanceMatchingPredicate.
            # Never auto-propagate trio siblings here, otherwise the middle node
            # would be incorrectly marked as matched.
            if getattr(osm_entry, 'group_type', None) == 'osm_trio':
                return
            for member in osm_entry.get_members():
                if member.node_id == osm_node.node_id:
                    continue
                if self.osm.is_used(member.node_id):
                    continue
                osm_dist = haversine_distance(atlas_node.lat, atlas_node.lon,
                                              member.lat, member.lon)
                osm_record = MatchRecord(
                    atlas_node=atlas_node,
                    osm_node=member,
                    match_type='osm_group_propagation',
                    distance_m=osm_dist,
                    notes=f"OSM group partner of: {osm_node.node_id}",
                )
                self.all_matches.append(osm_record)
                self.osm.mark_used(member.node_id)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(predicates: list['BasePredicate'], ctx: MatchingContext) -> 'PipelineResult':
    """
    Run *predicates* sequentially.
    """
    for predicate in predicates:
        unmatched = ctx.atlas.get_unmatched_records()

        logger.info(
            f"  Running {predicate.name} "
            f"({len(unmatched)} unmatched ATLAS entries)…"
        )

        matches_before = len(ctx.all_matches)
        
        # The predicate algorithm directly interacts with ctx.commit(...) now
        predicate.run(ctx)

        matches_after = len(ctx.all_matches)
        logger.info(f"    → {predicate.name}: {matches_after - matches_before} matches")

    # ----- Build output -----
    unmatched_atlas = ctx.atlas.get_unmatched_nodes()
    unmatched_osm = ctx.osm.get_unmatched_nodes()

    return PipelineResult(
        matched=ctx.all_matches,
        unmatched_atlas=unmatched_atlas,
        unmatched_osm=unmatched_osm,
    )
