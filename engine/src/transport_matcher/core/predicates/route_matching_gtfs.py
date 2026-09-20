"""
Route-based matching predicate.

Matches source stops to OSM nodes by comparing GTFS route tokens.
Route data is provided by SourceState (loaded from normalized GTFS route CSVs) and OsmState
(derived from the OSM XML relation pass) — no file I/O happens here.
"""
import logging
from collections import defaultdict

from transport_matcher.core.pipeline import MatchingContext
from transport_matcher.core.predicates import BasePredicate
from transport_matcher.core.utils.route_matching import (
    build_source_direction_names,
    build_source_gtfs_tokens,
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

    source_best = _collect_unique_best_edges(edges, 'source_key', score_name)
    osm_best = _collect_unique_best_edges(edges, 'osm_node_id', score_name)

    committed_pairs: list[dict] = []
    for source_key, edge in source_best.items():
        osm_node_id = edge['osm_node_id']
        if osm_best.get(osm_node_id) is edge:
            committed_pairs.append(edge)

    committed_pairs.sort(
        key=lambda edge: (-edge[score_name], edge['distance_m'], edge['source_key'], edge['osm_node_id'])
    )

    matched_keys: set[str] = set()
    for edge in committed_pairs:
        source_entry = edge['source_entry']
        osm_node = edge['osm_node']
        if source_entry.key in matched_keys or ctx.osm.is_used(osm_node.node_id):
            continue
        ctx.commit(
            source_node=source_entry,
            osm_node=osm_node,
            match_type=edge['match_type'],
            distance_m=edge['distance_m'],
            notes=edge['notes'],
            evidence=edge.get('evidence', {}),
        )
        matched_keys.add(source_entry.key)

    return matched_keys


class RouteMatchPredicate(BasePredicate):
    """Match source stops to OSM nodes strictly by common transit routes/lines."""

    def run(self, ctx: MatchingContext) -> None:
        name_dirs = ctx.osm.name_dirs

        unmatched = ctx.source.get_unmatched_records()
        if not unmatched:
            return

        coords = [(e.lat, e.lon) for e in unmatched]
        batch_candidates = ctx.osm.batch_query_radius(coords, ctx.max_distance, include_stations=False)
        token_edges: list[dict] = []
        direction_edges: list[dict] = []

        for i, entry in enumerate(unmatched):
            key = entry.key
            if not key:
                continue

            source_route_evidence = ctx.source.get_route_evidence(key)
            if not source_route_evidence['gtfs']:
                continue

            source_tokens = build_source_gtfs_tokens(source_route_evidence)
            source_direction_names = build_source_direction_names(source_route_evidence)

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
                osm_tokens = build_osm_gtfs_tokens(node_routes, route_state=ctx.route_state)
                token_overlap = source_tokens & osm_tokens
                if token_overlap:
                    token_edges.append({
                        'source_key': str(entry.key),
                        'osm_node_id': str(node.node_id),
                        'source_entry': entry,
                        'osm_node': node,
                        'distance_m': dist,
                        'score': len(token_overlap),
                        'match_type': 'route_gtfs_tokens',
                        'notes': 'gtfs_tokens',
                        'evidence': {'shared_route_tokens': sorted(token_overlap), 'score': len(token_overlap)},
                    })
                    continue

                if source_direction_names and (source_direction_names & set(name_dirs.get(str(node.node_id), set()))):
                    direction_edges.append({
                        'source_key': str(entry.key),
                        'osm_node_id': str(node.node_id),
                        'source_entry': entry,
                        'osm_node': node,
                        'distance_m': dist,
                        'score': 1,
                        'match_type': 'route_gtfs_direction',
                        'notes': 'direction_name',
                        'evidence': {'shared_direction_names': sorted(source_direction_names & set(name_dirs.get(str(node.node_id), set())))},
                    })

        matched_keys = _commit_mutual_unique_edges(ctx, token_edges, 'score')
        remaining_direction_edges = [
            edge for edge in direction_edges
            if edge['source_key'] not in matched_keys and not ctx.osm.is_used(edge['osm_node_id'])
        ]
        _commit_mutual_unique_edges(ctx, remaining_direction_edges, 'score')
