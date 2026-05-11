"""
Route-based matching predicate.

Matches ATLAS stops to OSM nodes by comparing GTFS route tokens.
Route data is provided by AtlasState (loaded from normalized GTFS route CSVs) and OsmState
(derived from the OSM XML relation pass) — no file I/O happens here.
"""
import logging
from collections import defaultdict

from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.utils.route_matching import (
    build_atlas_direction_names,
    build_atlas_gtfs_tokens,
    build_osm_gtfs_tokens,
)

logger = logging.getLogger(__name__)


def _collect_unique_best_edges(edges: list[dict], key_name: str, score_name: str) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        grouped[str(edge[key_name])].append(edge)

    unique_best: dict[str, dict] = {}
    for key, grouped_edges in grouped.items():
        best_score = max(edge[score_name] for edge in grouped_edges)
        best_edges = [edge for edge in grouped_edges if edge[score_name] == best_score]
        if len(best_edges) == 1:
            unique_best[key] = best_edges[0]

    return unique_best


def _commit_mutual_unique_edges(ctx: MatchingContext, edges: list[dict], score_name: str) -> set[str]:
    if not edges:
        return set()

    atlas_best = _collect_unique_best_edges(edges, 'atlas_sloid', score_name)
    osm_best = _collect_unique_best_edges(edges, 'osm_node_id', score_name)

    committed_pairs: list[dict] = []
    for atlas_sloid, edge in atlas_best.items():
        osm_node_id = edge['osm_node_id']
        if osm_best.get(osm_node_id) is edge:
            committed_pairs.append(edge)

    committed_pairs.sort(
        key=lambda edge: (-edge[score_name], edge['distance_m'], edge['atlas_sloid'], edge['osm_node_id'])
    )

    matched_sloids: set[str] = set()
    for edge in committed_pairs:
        atlas_entry = edge['atlas_entry']
        osm_node = edge['osm_node']
        if atlas_entry.sloid in matched_sloids or ctx.osm.is_used(osm_node.node_id):
            continue
        ctx.commit(
            atlas_node=atlas_entry,
            osm_node=osm_node,
            match_type=edge['match_type'],
            distance_m=edge['distance_m'],
            notes=edge['notes'],
        )
        matched_sloids.add(atlas_entry.sloid)

    return matched_sloids


class RouteMatchPredicate(BasePredicate):
    """Match ATLAS stops to OSM nodes strictly by common transit routes/lines."""

    def run(self, ctx: MatchingContext) -> None:
        name_dirs = ctx.osm.name_dirs

        unmatched = ctx.atlas.get_unmatched_records()
        if not unmatched:
            return

        coords = [(e.lat, e.lon) for e in unmatched]
        batch_candidates = ctx.osm.batch_query_radius(coords, ctx.max_distance, include_stations=False)
        token_edges: list[dict] = []
        direction_edges: list[dict] = []

        for i, entry in enumerate(unmatched):
            sloid = entry.sloid
            if not sloid:
                continue

            atlas_routes_data = ctx.atlas.get_routes(sloid)
            if not atlas_routes_data['gtfs']:
                continue

            atlas_tokens = build_atlas_gtfs_tokens(atlas_routes_data)
            atlas_direction_names = build_atlas_direction_names(atlas_routes_data)

            # Find OSM candidates within max_distance
            candidates = [
                (node, dist)
                for node, dist in batch_candidates[i]
                if not ctx.osm.is_used(node.node_id)
            ]
            if not candidates:
                continue

            for node, dist in candidates:
                node_routes = ctx.osm.get_node_routes(str(node.node_id))
                osm_tokens = build_osm_gtfs_tokens(node_routes)
                token_overlap = atlas_tokens & osm_tokens
                if token_overlap:
                    token_edges.append({
                        'atlas_sloid': str(entry.sloid),
                        'osm_node_id': str(node.node_id),
                        'atlas_entry': entry,
                        'osm_node': node,
                        'distance_m': dist,
                        'score': len(token_overlap),
                        'match_type': 'route_gtfs_tokens',
                        'notes': 'gtfs_tokens',
                    })
                    continue

                if atlas_direction_names and (atlas_direction_names & set(name_dirs.get(str(node.node_id), set()))):
                    direction_edges.append({
                        'atlas_sloid': str(entry.sloid),
                        'osm_node_id': str(node.node_id),
                        'atlas_entry': entry,
                        'osm_node': node,
                        'distance_m': dist,
                        'score': 1,
                        'match_type': 'route_gtfs_direction',
                        'notes': 'direction_name',
                    })

        matched_sloids = _commit_mutual_unique_edges(ctx, token_edges, 'score')
        remaining_direction_edges = [
            edge for edge in direction_edges
            if edge['atlas_sloid'] not in matched_sloids and not ctx.osm.is_used(edge['osm_node_id'])
        ]
        _commit_mutual_unique_edges(ctx, remaining_direction_edges, 'score')
