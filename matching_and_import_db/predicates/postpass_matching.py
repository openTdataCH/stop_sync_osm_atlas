"""
Post-pass matching predicates.

* **postpass_unique_uic** – match when only one unused OSM node remains for a UIC
* **duplicate_propagation** – propagate matches across ATLAS duplicate groups
* **manual_match** – apply persistent manual matches from the user-input database
"""
import logging
import os

import pandas as pd

from matching_and_import_db.pipeline import MatchingContext, make_match

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Predicate – unique UIC post-pass
# ---------------------------------------------------------------------------

def postpass_unique_uic(ctx: MatchingContext) -> list[dict]:
    """Match when only one unused OSM node remains for a UIC reference."""
    matches: list[dict] = []

    unmatched = ctx.atlas.get_unmatched_records()
    unmatched_df = pd.DataFrame(unmatched)
    if unmatched_df.empty:
        return matches

    for uic, group_df in unmatched_df.groupby(
        unmatched_df['number'].astype(str)
    ):
        available = ctx.osm.get_by_uic(str(uic))
        if len(available) != 1:
            continue

        osm = available[0]
        for _, row in group_df.iterrows():
            matches.append(make_match(
                row.to_dict(), osm, 'exact_postpass',
                "Post-pass unique-by-UIC consolidation",
                pool_size=1,
            ))
        ctx.osm.mark_used(osm['node_id'])

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
        dup_group_sloids = ctx.atlas.duplicate_sloid_map.get(sloid)
        if not dup_group_sloids:
            continue

        # Is any target in the duplicated SLOID group matched?
        target_match = None
        target_sloid = None
        for cand_sloid in dup_group_sloids:
            if cand_sloid != sloid:
                m = sloid_to_match.get(cand_sloid)
                if m:
                    target_match = m
                    target_sloid = cand_sloid
                    break
                    
        if not target_match:
            continue

        target_row = all_rows_dict.get(target_sloid)
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

        new_matches.append(make_match(
            entry, osm_node, 'duplicate_propagation',
            f"Propagated from duplicated sloid: {target_sloid}"
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
