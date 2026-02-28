"""
Pipeline framework for the matching process.

Defines MatchingContext (shared state), PipelineOutput, the sequential runner,
and the make_match() helper used by all predicates.
"""
from dataclasses import dataclass, field
import pandas as pd
import logging

from matching_and_import_db.utils.common import haversine_distance
from matching_and_import_db.utils.match_record import create_match_record, extract_atlas_fields
from matching_and_import_db.models import MatchRecord, PipelineResult

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
               atlas_node: 'AtlasNode', 
               osm_node: 'OsmNode', 
               match_type: str, 
               distance_m: float, 
               notes: str, 
               candidate_pool_size: int = 0) -> None:
        """
        Atomically records a match and immediately mutates locks in the State managers
        to prevent subsequent iterations within the same predicate from double-booking nodes.
        """
        # 1. Instantiate Match Record Domain Entity
        record = MatchRecord(
            atlas_node=atlas_node,
            osm_node=osm_node,
            match_type=match_type,
            distance_m=distance_m,
            notes=notes,
            candidate_pool_size=candidate_pool_size
        )
        
        # 2. Add to global tracking
        self.all_matches.append(record)
        
        # 3. Secure locks immediately
        self.atlas.add_matched_sloid(atlas_node.sloid)
        if osm_node.node_id and osm_node.node_id != 'NA':
            self.osm.mark_used(osm_node.node_id)


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
    unmatched_atlas = ctx.atlas.get_unmatched_records()
    unmatched_osm = ctx.osm.get_unmatched_nodes()

    return PipelineResult(
        matched=ctx.all_matches,
        unmatched_atlas=unmatched_atlas,
        unmatched_osm=unmatched_osm,
        duplicate_sloid_map=ctx.atlas.duplicate_sloid_map, # We pull this directly from State
        no_nearby_osm_sloids=set() # Calculated later in orchestrator/importer
    )
