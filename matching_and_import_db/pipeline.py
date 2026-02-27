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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass
class MatchingContext:
    """Robust, immutable context referencing state managers for the pipeline run."""

    # Encapsulated state managers
    atlas: 'AtlasState'
    osm: 'OsmState'
    
    # Internal Tracking
    all_matches: list = field(default_factory=list)

    # Config
    max_distance: float = 50.0


@dataclass
class PipelineOutput:
    """Immutable result returned by ``run_pipeline``."""
    matched: list
    unmatched_atlas: list
    unmatched_osm: list


# ---------------------------------------------------------------------------
# Helper used by every predicate
# ---------------------------------------------------------------------------

def make_match(atlas_entry: dict, osm_node: dict, match_type: str,
               notes: str, pool_size: int = 0) -> dict:
    """Create a MatchRecord dict from an ATLAS entry and an OSM node."""
    dist = haversine_distance(
        atlas_entry['wgs84North'], atlas_entry['wgs84East'],
        osm_node['lat'], osm_node['lon'],
    )
    return create_match_record(
        sloid=atlas_entry['sloid'],
        csv_lat=atlas_entry['wgs84North'],
        csv_lon=atlas_entry['wgs84East'],
        osm_node=osm_node,
        distance_m=dist,
        match_type=match_type,
        matching_notes=notes,
        number=atlas_entry.get('number'),
        candidate_pool_size=pool_size,
        **extract_atlas_fields(atlas_entry),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(predicates: list, ctx: MatchingContext) -> PipelineOutput:
    """
    Run *predicates* sequentially.
    """
    for predicate in predicates:
        unmatched = ctx.atlas.get_unmatched_records()

        logger.info(
            f"  Running {predicate.__name__} "
            f"({len(unmatched)} unmatched ATLAS entries)…"
        )

        matches = predicate(ctx)

        # --- Book-keeping ---
        for m in matches:
            ctx.all_matches.append(m)
            sloid = m.get('sloid')
            if sloid:
                ctx.atlas.add_matched_sloid(sloid)
            osm_id = m.get('osm_node_id')
            if osm_id and osm_id != 'NA':
                ctx.osm.mark_used(osm_id)

        logger.info(f"    → {predicate.__name__}: {len(matches)} matches")

    # ----- Build output -----
    unmatched_atlas = ctx.atlas.get_unmatched_records()
    unmatched_osm = ctx.osm.get_unmatched_nodes()

    return PipelineOutput(
        matched=ctx.all_matches,
        unmatched_atlas=unmatched_atlas,
        unmatched_osm=unmatched_osm,
    )
