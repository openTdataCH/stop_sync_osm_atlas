"""
Post-pass matching predicates.

* **postpass_unique_uic** – match when only one unused OSM node remains for a UIC
* **duplicate_propagation** – propagate matches across ATLAS duplicate groups
* **manual_match** – apply persistent manual matches from the user-input database
"""
import logging
import os

import pandas as pd

from matching_process.pipeline import MatchingContext, make_match
from matching_process.utils import is_osm_station, haversine_distance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Predicate – unique UIC post-pass
# ---------------------------------------------------------------------------

def postpass_unique_uic(ctx: MatchingContext) -> list[dict]:
    """Match when only one unused OSM node remains for a UIC reference."""
    matches: list[dict] = []

    for uic, group_df in ctx.atlas_unmatched.groupby(
        ctx.atlas_unmatched['number'].astype(str)
    ):
        available = [
            c for c in ctx.uic_ref_dict.get(str(uic), [])
            if c['node_id'] not in ctx.used_osm_ids and not is_osm_station(c)
        ]
        if len(available) != 1:
            continue

        osm = available[0]
        for _, row in group_df.iterrows():
            matches.append(make_match(
                row.to_dict(), osm, 'exact_postpass',
                "Post-pass unique-by-UIC consolidation",
                pool_size=1,
            ))
        ctx.used_osm_ids.add(osm['node_id'])

    return matches


# ---------------------------------------------------------------------------
# Predicate – duplicate propagation
# ---------------------------------------------------------------------------

def duplicate_propagation(ctx: MatchingContext) -> list[dict]:
    """
    If one sloid in a duplicate group matched, spread that match to the rest.
    """
    new_matches: list[dict] = []
    logger.info("  Running duplicate_propagation…")

    unmatched = ctx.atlas.get_unmatched_records()

    # Fast ID lookups for completed matches
    sloid_to_match = {m['sloid']: m for m in ctx.all_matches}
    all_rows_dict = ctx.atlas.get_all_rows_as_dict()

    for entry in unmatched:
        sloid = str(entry.get('sloid', ''))
        atlas_dup_id = ctx.atlas.duplicate_sloid_map.get(sloid)
        if not atlas_dup_id:
            continue

        # Is the target duplicated SLOID matched?
        target_match = sloid_to_match.get(atlas_dup_id)
        if not target_match:
            continue

        target_row = all_rows_dict.get(atlas_dup_id)
        if not target_row:
            continue

        # Propagate match
        osm_node = {
            'node_id': target_match.get('osm_node_id'),
            'lat': target_match.get('osm_lat'),
            'lon': target_match.get('osm_lon'),
            'local_ref': target_match.get('osm_local_ref'),
            'tags': {
                'network': target_match.get('osm_network'),
                'operator': target_match.get('osm_operator'),
                'original_operator': target_match.get('osm_original_operator'),
                'amenity': target_match.get('osm_amenity'),
                'railway': target_match.get('osm_railway'),
                'aerialway': target_match.get('osm_aerialway'),
                'name': target_match.get('osm_name'),
                'uic_name': target_match.get('osm_uic_name'),
                'uic_ref': target_match.get('osm_uic_ref'),
                'public_transport': target_match.get('osm_public_transport'),
            }
        }

        dist = target_match.get('distance_m')
        if dist is None:
            # Fallback calculation if target lacked distance
            dist = haversine_distance(
                float(entry['wgs84North']),
                float(entry['wgs84East']),
                osm_node.get('lat') or 0.0,
                osm_node.get('lon') or 0.0
            )

        new_matches.append(make_match(
            entry, osm_node, 'duplicate_propagation',
            f"Propagated from duplicated sloid: {atlas_dup_id}",
            distance_m=dist,
        ))

    return new_matches


# ---------------------------------------------------------------------------
# Predicate – persistent manual matches
# ---------------------------------------------------------------------------

def manual_match(ctx: MatchingContext) -> list[dict]:
    """Apply persistent manual matches stored in the user-input database."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models import PersistentData

        db_uri = os.getenv(
            'USER_INPUT_DATABASE_URI',
            'postgresql+psycopg://stops_user:1234@localhost:5432/user_input_db',
        )
        engine = create_engine(db_uri)
        Session = sessionmaker(bind=engine)
        session = Session()

        pairs: set[tuple[str, str]] = set()
        for pm in session.query(PersistentData).filter(
            PersistentData.problem_type == 'unmatched',
            PersistentData.solution == 'manual',
        ).all():
            if pm.sloid and pm.osm_node_id:
                pairs.add((str(pm.sloid), str(pm.osm_node_id)))
        session.close()
    except Exception as exc:
        logger.debug(f"Could not load persistent manual matches (non-critical): {exc}")
        return []

    if not pairs:
        return []

    all_rows_dict = ctx.atlas.get_all_rows_as_dict()

    matches: list[dict] = []
    for sloid, node_id in pairs:
        if sloid in ctx.atlas.matched_ids or ctx.osm.is_used(node_id):
            continue
        
        a = all_rows_dict.get(sloid)
        o = ctx.osm._all_nodes.get(node_id)
        
        if a and o:
            matches.append(make_match(a, o, 'manual', "Persistent manual match"))
            ctx.osm.mark_used(node_id)
            ctx.atlas.add_matched_sloid(sloid)

    return matches
