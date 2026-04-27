"""
Route-based matching predicate.

Matches ATLAS stops to OSM nodes by comparing GTFS route tokens.
Route data is provided by AtlasState (atlas_routes_gtfs.csv) and OsmState
(derived from the OSM XML relation pass) — no file I/O happens here.
"""
import logging

from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.route_state import RouteState

logger = logging.getLogger(__name__)


class RouteMatchPredicate(BasePredicate):
    """Match ATLAS stops to OSM nodes strictly by common transit routes/lines."""

    def run(self, ctx: MatchingContext) -> None:
        name_dirs = ctx.osm.name_dirs

        unmatched = ctx.atlas.get_unmatched_records()
        if not unmatched:
            return

        coords = [(e.lat, e.lon) for e in unmatched]
        batch_candidates = ctx.osm.batch_query_radius(coords, ctx.max_distance, include_stations=False)

        for i, entry in enumerate(unmatched):
            sloid = entry.sloid
            if not sloid:
                continue

            atlas_routes_data = ctx.atlas.get_routes(sloid)
            if not atlas_routes_data['gtfs']:
                continue

            # Find OSM candidates within max_distance
            candidates = [
                (node, dist)
                for node, dist in batch_candidates[i]
                if not ctx.osm.is_used(node.node_id)
            ]
            if not candidates:
                continue

            # Attach route entries from OsmState to each candidate
            candidate_list = [
                (node, dist, ctx.osm.get_node_routes(str(node.node_id)))
                for node, dist in candidates
            ]

            # Build GTFS tokens
            gtfs_tokens: set[tuple[str, str]] = set()
            for e in atlas_routes_data['gtfs']:
                if e.get('route_id_normalized') and e.get('direction_id'):
                    gtfs_tokens.add((e['route_id_normalized'], e['direction_id']))

            matched_node = None
            matched_dist = None
            match_source = None
            match_evidence = None

            # P1: GTFS tokens
            if gtfs_tokens:
                route_state = RouteState.get_instance()
                for node, dist, node_routes in candidate_list:
                    node_tokens: set[tuple[str, str]] = set()
                    for r in node_routes:
                        osm_rel_id = r.get('relation_id')
                        did = r.get('direction_id', '0')
                        
                        if osm_rel_id:
                            atlas_rid = route_state.get_atlas_route(osm_rel_id)
                            if atlas_rid:
                                # Match using the mapped atlas route ID
                                node_tokens.add((atlas_rid, did))
                                # Also add normalized version for flexibility
                                from matching_and_import_db.utils.route_id import normalize_route_id
                                norm = normalize_route_id(atlas_rid)
                                if norm:
                                    node_tokens.add((norm, did))
                        
                        gtfs_rid = r.get('gtfs_route_id')
                        if gtfs_rid:
                            node_tokens.add((gtfs_rid, did))
                            from matching_and_import_db.utils.route_id import normalize_route_id
                            norm = normalize_route_id(gtfs_rid)
                            if norm:
                                node_tokens.add((norm, did))

                    if gtfs_tokens & node_tokens:
                        matched_node, matched_dist = node, dist
                        match_source, match_evidence = 'gtfs', 'gtfs_tokens'
                        break

            # P2: name-based direction fallback
            if matched_node is None:
                dir_names: set[str] = set()
                for e in atlas_routes_data['gtfs']:
                    dn = e.get('direction_name')
                    if dn:
                        dir_names.add(dn)
                if dir_names:
                    for node, dist, _ in candidate_list:
                        nid = str(node.node_id)
                        if any(dn in name_dirs.get(nid, set()) for dn in dir_names):
                            matched_node, matched_dist = node, dist
                            match_source, match_evidence = 'gtfs', 'direction_name'
                            break

            if matched_node is not None:
                ctx.commit(
                    atlas_node=entry,
                    osm_node=matched_node,
                    match_type=f"route_gtfs_{match_source}",
                    distance_m=matched_dist,
                    notes=match_evidence,
                )
