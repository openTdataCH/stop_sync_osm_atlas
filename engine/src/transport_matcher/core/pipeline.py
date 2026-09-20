"""
Pipeline framework for the matching process.

Defines MatchingContext (shared state), PipelineOutput, the sequential runner,
and the make_match() helper used by all predicates.
"""
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING
from transport_matcher.profiles import MatchingProfile
from transport_matcher.core.route_state import RouteState

from transport_matcher.core.utils.common import haversine_distance
from transport_matcher.core.models import MatchRecord, PipelineResult

if TYPE_CHECKING:
    from transport_matcher.core.state import SourceState, OsmState
    from transport_matcher.core.predicates import BasePredicate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass
class MatchingContext:
    """Robust, shared context referencing state managers for the pipeline run."""

    # Encapsulated state managers
    source: 'SourceState'
    osm: 'OsmState'
    
    # Internal Tracking
    all_matches: list['MatchRecord'] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    # Config
    max_distance: float = 50.0
    profile: MatchingProfile = field(default_factory=MatchingProfile)
    route_state: RouteState = field(default_factory=RouteState)

    def commit(self,
               source_node,
               osm_node,
               match_type: str,
               distance_m: float,
               notes: str,
               evidence: dict | None = None) -> None:
        """
        Atomically records a match and immediately mutates locks in the State managers
        to prevent subsequent iterations within the same predicate from double-booking nodes.

        Handles group expansion symmetrically for both source and OSM sides:
        - source group siblings get ``duplicate_propagation`` records
        - OSM group siblings get ``osm_group_propagation`` records
        """
        # Keep original references for group expansion checks
        source_entry = source_node
        osm_entry = osm_node
        # Extract raw nodes (works for both entities and raw nodes)
        source_node = getattr(source_entry, 'representative', source_entry)
        osm_node = getattr(osm_entry, 'representative', osm_entry)

        # 1. Primary match record
        record = MatchRecord(
            source_node=source_node,
            osm_node=osm_node,
            match_type=match_type,
            distance_m=distance_m,
            notes=notes,
            evidence={'rule': match_type, 'distance_m': distance_m, **(evidence or {})},
        )
        self.all_matches.append(record)

        # 2. Secure locks immediately
        self.source.add_matched_key(source_node.key)
        if osm_node.node_id and osm_node.node_id != 'NA':
            self.osm.mark_used(osm_node.node_id)

        # 3. source group expansion (duplicate_propagation)
        if hasattr(source_entry, 'is_group') and source_entry.is_group:
            for member in source_entry.get_members():
                if member.key == source_node.key:
                    continue
                if member.key in self.source.matched_ids:
                    continue
                sib_dist = haversine_distance(member.lat, member.lon,
                                              osm_node.lat, osm_node.lon)
                sib_record = MatchRecord(
                    source_node=member,
                    osm_node=osm_node,
                    match_type='duplicate_propagation',
                    distance_m=sib_dist,
                    notes=f"Propagated from representative: {source_node.key}",
                    evidence={'representative_source_key': source_node.key},
                )
                self.all_matches.append(sib_record)
                self.source.add_matched_key(member.key)

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
                osm_dist = haversine_distance(source_node.lat, source_node.lon,
                                              member.lat, member.lon)
                osm_record = MatchRecord(
                    source_node=source_node,
                    osm_node=member,
                    match_type='osm_group_propagation',
                    distance_m=osm_dist,
                    notes=f"OSM group partner of: {osm_node.node_id}",
                    evidence={'representative_osm_id': osm_node.node_id},
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
        unmatched = ctx.source.get_unmatched_records()

        logger.info(
            f"  Running {predicate.name} "
            f"({len(unmatched)} unmatched source entries)…"
        )

        matches_before = len(ctx.all_matches)
        
        # The predicate algorithm directly interacts with ctx.commit(...) now
        predicate.run(ctx)

        matches_after = len(ctx.all_matches)
        logger.info(f"    → {predicate.name}: {matches_after - matches_before} matches")

    # ----- Build output -----
    unmatched_source = ctx.source.get_unmatched_nodes()
    unmatched_osm = ctx.osm.get_unmatched_nodes()

    return PipelineResult(
        matched=ctx.all_matches,
        unmatched_source=unmatched_source,
        unmatched_osm=unmatched_osm,
    )
