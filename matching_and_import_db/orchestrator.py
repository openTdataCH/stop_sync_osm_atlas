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

# Pipeline framework
from matching_and_import_db.pipeline import MatchingContext, run_pipeline
from matching_and_import_db.state import AtlasState, OsmState

from matching_and_import_db.predicates.exact_matching import ExactUicPredicate
from matching_and_import_db.predicates.name_matching import NameMatchPredicate
from matching_and_import_db.predicates.distance_matching import GroupProximityPredicate, LocalRefDistancePredicate, NearestDistancePredicate
from matching_and_import_db.predicates.route_matching_unified import RouteMatchPredicate
from matching_and_import_db.predicates.postpass_matching import PostpassUniqueUicPredicate, DuplicatePropagationPredicate, ManualMatchPredicate

DEFAULT_PIPELINE = [
    ExactUicPredicate(),
    NameMatchPredicate(),
    GroupProximityPredicate(),
    LocalRefDistancePredicate(),
    NearestDistancePredicate(),
    RouteMatchPredicate(),
    PostpassUniqueUicPredicate(),
    DuplicatePropagationPredicate(),
    ManualMatchPredicate(),
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

    Returns
    -------
    output : PipelineResult
        Strongly typed result containing matched, unmatched, and state mappings.
    """

    # ── Load data ────────────────────────────────────────────────────────
    atlas_csv_file = _locate_file('ATLAS_STOPS_CSV', 'data/raw/stops_ATLAS.csv', 'ATLAS')
    osm_xml_file = _locate_file('OSM_XML_FILE', 'data/raw/osm_data.xml', 'OSM')

    atlas_df = pd.read_csv(atlas_csv_file, sep=";")

    osm_index = OsmState.from_xml_file(osm_xml_file)

    # ── Identify ATLAS duplicate groups & init State ─────────────────────
    atlas_state = AtlasState.from_dataframe(atlas_df)

    ctx = MatchingContext(
        atlas=atlas_state,
        osm=osm_index,
        max_distance=50.0,
    )

    pipeline = DEFAULT_PIPELINE

    output = run_pipeline(pipeline, ctx)

    # ── Summary ──────────────────────────────────────────────────────────
    _print_summary(output, atlas_df)

    return output


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_summary(output, atlas_df):
    """Print a concise matching summary."""
    from collections import Counter
    types = Counter(m.match_type for m in output.matched)

    print("\n==== FINAL MATCHING SUMMARY ====")
    print(f"Total ATLAS entries: {len(atlas_df)}")
    for mt, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {mt}: {count}")
    print(f"Total matched: {len(output.matched)}")
    print(f"Unmatched ATLAS: {len(output.unmatched_atlas)}")
    print(f"Unmatched OSM: {len(output.unmatched_osm)}")

    matched_dups = sum(
        1 for m in output.matched
        if m.atlas_node.sloid in output.duplicate_sloid_map
    )
    print(f"Duplicate ATLAS sloids: {len(output.duplicate_sloid_map)} "
          f"(matched: {matched_dups})")
    print("Base data is ready for database import.")
