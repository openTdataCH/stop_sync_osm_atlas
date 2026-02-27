"""
Exact UIC matching predicate.

Matches ATLAS entries to OSM nodes when ATLAS ``number`` == OSM ``uic_ref``,
refining by ``designation`` == ``local_ref`` when multiple candidates exist.
"""
from collections import defaultdict
import pandas as pd

from matching_and_import_db.pipeline import MatchingContext, make_match

def exact_uic(ctx: MatchingContext) -> list[dict]:
    """Match by ATLAS number == OSM uic_ref, refine by designation == local_ref."""
    matches: list[dict] = []

    # Group ATLAS entries by UIC number
    atlas_by_uic: dict[str, list[dict]] = {}
    for rec in ctx.atlas.get_unmatched_records():
        atlas_by_uic.setdefault(str(rec.get("number")), []).append(rec)

    for uic, entries in sorted(atlas_by_uic.items()):
        available = ctx.osm.get_by_uic(uic)
        if not available:
            continue

        # --- Case 1: single OSM node → match all ATLAS entries to it ---
        if len(available) == 1:
            osm = available[0]
            for entry in entries:
                matches.append(make_match(
                    entry, osm, 'exact',
                    "Single OSM node for this UIC reference",
                    pool_size=1,
                ))
            ctx.osm.mark_used(osm['node_id'])
            continue

        # --- Case 2: single ATLAS entry → match to all OSM nodes ---
        if len(entries) == 1:
            for osm in available:
                matches.append(make_match(
                    entries[0], osm, 'exact',
                    "Single ATLAS entry matched to multiple OSM nodes",
                    pool_size=len(available),
                ))
                ctx.osm.mark_used(osm['node_id'])
            continue

        # --- Case 3: many-to-many → refine by designation == local_ref ---
        ref_lookup: dict[str, list[dict]] = defaultdict(list)
        for c in available:
            lr = (c.get('local_ref') or '').strip().lower()
            if lr:
                ref_lookup[lr].append(c)

        for entry in entries:
            desig = (
                str(entry.get('designation', '')).strip().lower()
                if pd.notna(entry.get('designation')) else ''
            )
            if not desig:
                continue
            for osm in ref_lookup.get(desig, []):
                if ctx.osm.is_used(osm['node_id']):
                    continue
                matches.append(make_match(
                    entry, osm, 'exact',
                    "Exact local_ref/designation match",
                    pool_size=len(available),
                ))
                ctx.osm.mark_used(osm['node_id'])
                break  # one match per ATLAS entry

    return matches
