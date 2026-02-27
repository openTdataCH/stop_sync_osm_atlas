# matching_and_import_db/orchestrator.py
"""
Top-level orchestrator for the ATLAS ↔ OSM matching pipeline.

Loads data, builds indexes, runs the predicate pipeline, and performs
post-processing (isolation detection, summary reporting).
"""
import logging
import os
import time
import xml.etree.ElementTree as ET
from collections import defaultdict

import pandas as pd

from utils.timing import timed_phase

# Pipeline framework
from matching_and_import_db.pipeline import MatchingContext, run_pipeline
from matching_and_import_db.state import AtlasState, OsmState

# Predicates
from matching_and_import_db.predicates import (
    exact_uic,
    name_match,
    group_proximity,
    local_ref_distance,
    nearest_distance,
    route_match,
    postpass_unique_uic,
    duplicate_propagation,
    manual_match,
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default pipeline (sequential – matches current behaviour)
# ---------------------------------------------------------------------------
DEFAULT_PIPELINE = [
    exact_uic,
    name_match,
    group_proximity,
    local_ref_distance,
    nearest_distance,
    route_match,
    postpass_unique_uic,
    duplicate_propagation,
    manual_match,
]


# ---------------------------------------------------------------------------
# File resolution helpers
# ---------------------------------------------------------------------------

def _resolve_path(preferred: str, alternates: list) -> str:
    for p in [preferred] + [a for a in alternates if a]:
        if p and os.path.exists(p):
            return p
    return ""


def _wait_for_file(paths: list[str], timeout: int = 60) -> str:
    deadline = time.time() + timeout
    while True:
        for p in paths:
            if p and os.path.exists(p):
                return p
        if time.time() >= deadline:
            return ""
        time.sleep(1.0)

def _locate_file(env_key, default, label):
    """Locate a required data file, optionally waiting."""
    pref = os.getenv(env_key, default)
    alternates = [
        os.path.join('/app', pref) if not os.path.isabs(pref) else None,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), pref)
        if not os.path.isabs(pref) else None,
    ]
    path = _resolve_path(pref, alternates)
    if not path:
        wait_list = [pref] + [a for a in alternates if a]
        path = _wait_for_file(wait_list, timeout=int(os.getenv(f'WAIT_FOR_{label}_SECONDS', '60')))
    if not path:
        raise FileNotFoundError(
            f"Required {label} file not found. "
            f"Tried: {[pref] + [a for a in alternates if a]}"
        )
    return path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_matching():
    """
    Execute the complete matching pipeline and return data for DB import.

    The pipeline is defined by :data:`DEFAULT_PIPELINE`.

    Returns
    -------
    base_data : dict
        ``{"matched": [...], "unmatched_atlas": [...], "unmatched_osm": [...]}``
    duplicate_sloid_map : dict
        ``{sloid_str: [list_of_group_sloids]}``
    no_nearby_osm_sloids : set
        SLOIDs of unmatched ATLAS entries with no OSM node within 50 m.
    """

    # ── Load data ────────────────────────────────────────────────────────
    atlas_csv_file = _locate_file('ATLAS_STOPS_CSV', 'data/raw/stops_ATLAS.csv', 'ATLAS')
    osm_xml_file = _locate_file('OSM_XML_FILE', 'data/raw/osm_data.xml', 'OSM')

    with timed_phase("Matching: load ATLAS CSV"):
        atlas_df = pd.read_csv(atlas_csv_file, sep=";")

    with timed_phase("Matching: parse OSM XML"):
        osm_index = OsmState.from_xml_file(osm_xml_file)

    # ── Identify ATLAS duplicate groups ──────────────────────────────────
    dup_mask = atlas_df.duplicated(subset=['number', 'designation'], keep=False)
    non_empty = atlas_df['designation'].notna() & (atlas_df['designation'].astype(str).str.strip() != '')
    dup_mask = dup_mask & non_empty

    with timed_phase("Identifying ATLAS duplicate groups"):
        duplicate_sloid_map: dict[str, list[str]] = {}
        for _, group_df in atlas_df[dup_mask].groupby(['number', 'designation'], sort=False):
            if len(group_df) <= 1:
                continue
            sloids = sorted(group_df['sloid'].astype(str).tolist())
            for s in sloids:
                duplicate_sloid_map[s] = sloids

    atlas_state = AtlasState(
        atlas_df=atlas_df,
        duplicate_sloid_map=duplicate_sloid_map
    )

    with timed_phase("Context initialization"):
        ctx = MatchingContext(
            atlas=atlas_state,
            osm=osm_index,
            max_distance=50.0,
        )

    with timed_phase("Matching: predicate pipeline"):
        output = run_pipeline(DEFAULT_PIPELINE, ctx)

    # ── Build return value (same shape as before) ────────────────────────
    # NOTE: Isolation detection is now handled by ProblemContext in import_data_db.py
    base_data = {
        "matched": output.matched,
        "unmatched_atlas": output.unmatched_atlas,
        "unmatched_osm": output.unmatched_osm,
    }

    # ── Summary ──────────────────────────────────────────────────────────
    _print_summary(output, atlas_df, duplicate_sloid_map)

    return base_data, duplicate_sloid_map, output.no_nearby_osm_sloids


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_summary(output, atlas_df, duplicate_sloid_map):
    """Print a concise matching summary."""
    from collections import Counter
    types = Counter(m.get('match_type', '?') for m in output.matched)

    print("\n==== FINAL MATCHING SUMMARY ====")
    print(f"Total ATLAS entries: {len(atlas_df)}")
    for mt, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {mt}: {count}")
    print(f"Total matched: {len(output.matched)}")
    print(f"Unmatched ATLAS: {len(output.unmatched_atlas)}")
    print(f"  └─ No OSM within 50 m: {len(output.no_nearby_osm_sloids)}")
    print(f"Unmatched OSM: {len(output.unmatched_osm)}")

    matched_dups = sum(
        1 for m in output.matched
        if str(m.get('sloid', '')) in duplicate_sloid_map
    )
    print(f"Duplicate ATLAS sloids: {len(duplicate_sloid_map)} "
          f"(matched: {matched_dups})")
    print("Base data is ready for database import.")
