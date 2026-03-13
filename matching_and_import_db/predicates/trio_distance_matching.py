"""
Trio-first distance matching.

Runs before other distance predicates. For each detected OSM trio, match the two
non-middle side nodes to the closest unmatched ATLAS nodes sharing the same UIC.
The middle node (stop_position) is intentionally left unmatched.
"""
from __future__ import annotations

from matching_and_import_db.pipeline import MatchingContext
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.utils.common import haversine_distance


class TrioDistanceMatchingPredicate(BasePredicate):
    """Pair two trio side nodes with the two closest unmatched ATLAS nodes for the same UIC."""

    def run(self, ctx: MatchingContext) -> None:
        trio_reps = ctx.osm.get_trio_representatives()
        if not trio_reps:
            return

        unmatched_atlas = ctx.atlas.get_unmatched_records()
        atlas_by_uic: dict[str, list] = {}
        for entry in unmatched_atlas:
            uic = (entry.uic_ref or "").strip()
            if not uic:
                continue
            atlas_by_uic.setdefault(uic, []).append(entry)

        for rep_id in trio_reps:
            trio = ctx.osm.get_trio_for_representative(rep_id)
            if trio is None:
                continue

            middle_node_id, side_node_id_1, side_node_id_2 = trio
            side_nodes = []
            for node_id in (side_node_id_1, side_node_id_2):
                node_entity = ctx.osm.get_by_node_id(node_id)
                if node_entity is None:
                    continue
                node = getattr(node_entity, 'representative', node_entity)
                if node.node_id == middle_node_id:
                    continue
                if ctx.osm.is_used(node.node_id):
                    continue
                side_nodes.append(node)

            if len(side_nodes) != 2:
                continue

            uic = (side_nodes[0].uic_ref or "").strip()
            if not uic:
                continue

            candidates = [entry for entry in atlas_by_uic.get(uic, []) if entry.sloid not in ctx.atlas.matched_ids]
            if len(candidates) != 2:
                continue

            atlas_a, atlas_b = candidates[0], candidates[1]
            side_a, side_b = side_nodes[0], side_nodes[1]

            d_aa = haversine_distance(atlas_a.lat, atlas_a.lon, side_a.lat, side_a.lon)
            d_ab = haversine_distance(atlas_a.lat, atlas_a.lon, side_b.lat, side_b.lon)
            d_ba = haversine_distance(atlas_b.lat, atlas_b.lon, side_a.lat, side_a.lon)
            d_bb = haversine_distance(atlas_b.lat, atlas_b.lon, side_b.lat, side_b.lon)

            if None in (d_aa, d_ab, d_ba, d_bb):
                continue

            # Evaluate both 2x2 assignments and pick the smaller total distance.
            direct_total = d_aa + d_bb
            cross_total = d_ab + d_ba
            if direct_total <= cross_total:
                chosen_pairs = ((atlas_a, side_a, d_aa), (atlas_b, side_b, d_bb))
            else:
                chosen_pairs = ((atlas_a, side_b, d_ab), (atlas_b, side_a, d_ba))

            for atlas_entry, side_node, dist in chosen_pairs:
                if atlas_entry.sloid in ctx.atlas.matched_ids:
                    continue
                if ctx.osm.is_used(side_node.node_id):
                    continue
                if side_node.node_id == middle_node_id:
                    continue

                ctx.commit(
                    atlas_node=atlas_entry,
                    osm_node=side_node,
                    match_type='distance_matching_trio',
                    distance_m=dist,
                    notes=f"Trio side matched (middle node {middle_node_id})",
                )
