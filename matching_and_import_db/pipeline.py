"""
Pipeline framework for the matching process.

Defines MatchingContext (shared state), PipelineOutput, the sequential runner,
and the make_match() helper used by all predicates.
"""
from dataclasses import dataclass, field
import pandas as pd
import logging

from utils.common import haversine_distance
from utils.match_record import create_match_record, extract_atlas_fields
from utils.spatial_index import (
    build_kdtree_from_nodes, meters_to_unit_chord_radius, batch_to_xyz,
)

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
    duplicate_sloid_map: dict
    no_nearby_osm_sloids: set


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
        if not unmatched:
            logger.info(f"  Skipping {predicate.__name__}: no unmatched ATLAS entries")
            continue

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

    no_nearby = compute_no_nearby_osm(
        unmatched_atlas, ctx.osm._all_nodes, radius=ctx.max_distance,
    )

    return PipelineOutput(
        matched=ctx.all_matches,
        unmatched_atlas=unmatched_atlas,
        unmatched_osm=unmatched_osm,
        duplicate_sloid_map=ctx.atlas.duplicate_sloid_map,
        no_nearby_osm_sloids=no_nearby,
    )


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------

def compute_no_nearby_osm(unmatched_atlas: list, osm_nodes: dict,
                          radius: float = 50) -> set:
    """Return SLOIDs of unmatched ATLAS entries with no OSM node within *radius* m."""
    tree, _points, nodes_list = build_kdtree_from_nodes(osm_nodes)
    if tree is None:
        return {e.get('sloid') for e in unmatched_atlas if e.get('sloid')}

    # Collect valid entries with coordinates
    valid_entries = []
    coords = []
    for entry in unmatched_atlas:
        lat = entry.get('wgs84North')
        lon = entry.get('wgs84East')
        if lat is not None and lon is not None:
            valid_entries.append(entry)
            coords.append((float(lat), float(lon)))

    if not coords:
        return set()

    kd_radius = meters_to_unit_chord_radius(radius)
    points = batch_to_xyz(coords)
    
    # Batch query all points at once
    indices_list = tree.query_ball_point(points, r=kd_radius, workers=-1)

    no_nearby: set = set()
    for i, entry in enumerate(valid_entries):
        lat, lon = coords[i]
        has_nearby = False
        for idx in indices_list[i]:
            (olat, olon), _ = nodes_list[idx]
            d = haversine_distance(lat, lon, olat, olon)
            if d is not None and d <= radius:
                has_nearby = True
                break
        if not has_nearby:
            sloid = entry.get('sloid')
            if sloid:
                no_nearby.add(sloid)

    return no_nearby
