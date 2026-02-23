"""
Name-based matching predicate.

Matches ATLAS ``designationOfficial`` against OSM ``name`` / ``uic_name`` /
``gtfs:name``, with an optional refinement by ``designation`` == ``local_ref``.
"""
import pandas as pd

from matching_process.pipeline import MatchingContext, make_match


def name_match(ctx: MatchingContext) -> list[dict]:
    """Match ATLAS designationOfficial against OSM name index."""
    matches: list[dict] = []

    for entry in ctx.atlas.get_unmatched_records():
        name = (
            str(entry.get('designationOfficial', '')).strip()
            if pd.notna(entry.get('designationOfficial')) else ''
        )
        if not name:
            continue

        candidates = ctx.osm.get_by_name(name)
        if not candidates:
            continue

        osm = None
        if len(candidates) == 1:
            osm = candidates[0]
        else:
            # Refine by designation == local_ref
            desig = (
                str(entry.get('designation', '')).strip().lower()
                if pd.notna(entry.get('designation')) else ''
            )
            if desig:
                for c in candidates:
                    if (c.get('local_ref') or '').strip().lower() == desig:
                        osm = c
                        break

        if osm:
            matches.append(make_match(
                entry, osm, 'name',
                f"Name index match ({len(candidates)} candidates)",
                pool_size=len(candidates),
            ))
            ctx.osm.mark_used(osm['node_id'])

    return matches
