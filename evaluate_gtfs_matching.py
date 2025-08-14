#!/usr/bin/env python3
"""
Evaluate effectiveness of two GTFS→ATLAS matching approaches using data/raw:

- Strict match: (uic_number, normalized_local_ref) == (number, designation)
- Fallback match: strict OR
    * if a given number has exactly one ATLAS row, use that sloid
    * else if any candidate sloid (same number) has last token == normalized_local_ref, use that sloid

Reports counts and deltas.
"""
import os
import sys
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ATLAS_CSV = os.path.join(PROJECT_ROOT, "data", "raw", "stops_ATLAS.csv")
GTFS_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "gtfs")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    # ATLAS
    if not os.path.exists(ATLAS_CSV):
        print(f"Missing ATLAS CSV at {ATLAS_CSV}")
        sys.exit(1)
    atlas = pd.read_csv(ATLAS_CSV, sep=';')
    needed_cols = {'sloid', 'number', 'designation'}
    missing = needed_cols - set(atlas.columns)
    if missing:
        print(f"ATLAS CSV missing columns: {missing}")
        sys.exit(1)
    atlas['number'] = atlas['number'].astype(str)
    # GTFS stops
    stops_txt = os.path.join(GTFS_DIR, 'stops.txt')
    if not os.path.exists(stops_txt):
        print(f"Missing GTFS stops at {stops_txt}")
        sys.exit(1)
    gtfs_stops = pd.read_csv(stops_txt, usecols=['stop_id', 'stop_name'], dtype={'stop_id': str, 'stop_name': str})
    # Swiss filter (stop_id starts with 85)
    gtfs_stops = gtfs_stops[gtfs_stops['stop_id'].str.startswith('85')].copy()
    return atlas, gtfs_stops


def parse_and_normalize_gtfs(gtfs_stops: pd.DataFrame) -> pd.DataFrame:
    def parse_stop_id(stop_id: str) -> tuple[str, str | None]:
        parts = stop_id.split(':')
        uic_number = parts[0]
        local_ref = parts[2] if len(parts) >= 3 else None
        return uic_number, local_ref

    def normalize_local_ref(ref: str | None) -> str | None:
        if ref is None:
            return None
        if ref == '10000':
            return '1'
        if ref == '10001':
            return '2'
        return ref

    uic_local = gtfs_stops['stop_id'].apply(parse_stop_id)
    gtfs_stops = gtfs_stops.copy()
    gtfs_stops['uic_number'] = [x[0] for x in uic_local]
    gtfs_stops['local_ref'] = [x[1] for x in uic_local]
    gtfs_stops['normalized_local_ref'] = gtfs_stops['local_ref'].apply(normalize_local_ref)
    gtfs_stops['uic_number'] = gtfs_stops['uic_number'].astype(str)
    return gtfs_stops


def strict_match(gtfs_stops: pd.DataFrame, atlas: pd.DataFrame) -> pd.DataFrame:
    matches = pd.merge(
        gtfs_stops[['stop_id', 'uic_number', 'normalized_local_ref']],
        atlas[['sloid', 'number', 'designation']],
        left_on=['uic_number', 'normalized_local_ref'],
        right_on=['number', 'designation'],
        how='inner'
    )[['stop_id', 'sloid']]
    return matches.drop_duplicates()


def fallback_match(gtfs_stops: pd.DataFrame, atlas: pd.DataFrame, strict_matches: pd.DataFrame) -> pd.DataFrame:
    # Prepare fast lookups
    matched_stop_ids = set(strict_matches['stop_id'])
    remaining = gtfs_stops[~gtfs_stops['stop_id'].isin(matched_stop_ids)].copy()
    if remaining.empty:
        return strict_matches.copy()

    # Map number -> subset of atlas rows
    atlas_by_number = {num: sub[['sloid', 'designation']].copy() for num, sub in atlas.groupby('number', sort=False)}

    def last_token_of_sloid(sloid: str) -> str:
        return sloid.split(':')[-1]

    fallback_rows: list[tuple[str, str]] = []  # (stop_id, sloid)
    for row in remaining.itertuples(index=False):
        uic = row.uic_number
        nref = row.normalized_local_ref
        stop_id = row.stop_id
        candidates = atlas_by_number.get(uic)
        if candidates is None or candidates.empty:
            continue
        # Rule 1: unique entry for this number
        if len(candidates) == 1:
            fallback_rows.append((stop_id, candidates.iloc[0]['sloid']))
            continue
        # Rule 2: match by sloid last token
        if nref is not None:
            token_matches = candidates[candidates['sloid'].apply(last_token_of_sloid) == nref]
            if not token_matches.empty:
                fallback_rows.append((stop_id, token_matches.iloc[0]['sloid']))

    if not fallback_rows:
        return strict_matches.copy()

    fb_df = pd.DataFrame(fallback_rows, columns=['stop_id', 'sloid']).drop_duplicates()
    combined = pd.concat([strict_matches[['stop_id', 'sloid']], fb_df], ignore_index=True).drop_duplicates()
    return combined


def main():
    atlas, gtfs_stops = load_inputs()
    gtfs_stops = parse_and_normalize_gtfs(gtfs_stops)

    print("Running strict match…")
    strict = strict_match(gtfs_stops, atlas)
    print(f"Strict: matched GTFS stops = {strict['stop_id'].nunique():,}; unique SLOIDs = {strict['sloid'].nunique():,}")

    print("Running fallback match…")
    combined = fallback_match(gtfs_stops, atlas, strict)
    print(f"Strict+Fallback: matched GTFS stops = {combined['stop_id'].nunique():,}; unique SLOIDs = {combined['sloid'].nunique():,}")

    # Deltas
    extra_stops = combined['stop_id'].nunique() - strict['stop_id'].nunique()
    extra_sloids = combined['sloid'].nunique() - strict['sloid'].nunique()
    print(f"Delta (added by fallback): +{extra_stops} GTFS stops, +{extra_sloids} SLOIDs")

    # Optional diagnostics: where fallback contributed
    strict_set = set(map(tuple, strict[['stop_id', 'sloid']].itertuples(index=False, name=None)))
    combined_set = set(map(tuple, combined[['stop_id', 'sloid']].itertuples(index=False, name=None)))
    added_pairs = combined_set - strict_set
    print(f"Added stop–sloid pairs by fallback: {len(added_pairs):,}")

    # Save quick CSVs
    out_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    os.makedirs(out_dir, exist_ok=True)
    strict.to_csv(os.path.join(out_dir, 'gtfs_atlas_matches_strict.csv'), index=False)
    pd.DataFrame(list(added_pairs), columns=['stop_id', 'sloid']).to_csv(
        os.path.join(out_dir, 'gtfs_atlas_matches_fallback_only.csv'), index=False
    )
    pd.DataFrame({
        'metric': ['matched_gtfs_stops', 'unique_sloids'],
        'strict': [strict['stop_id'].nunique(), strict['sloid'].nunique()],
        'strict_plus_fallback': [combined['stop_id'].nunique(), combined['sloid'].nunique()],
        'delta': [extra_stops, extra_sloids],
    }).to_csv(os.path.join(out_dir, 'gtfs_atlas_matching_summary.csv'), index=False)


if __name__ == '__main__':
    main()


