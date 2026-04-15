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
from matching_and_import_db.models import MatchingOutput, OsmStopUnitRecord, OsmStopMemberRecord
from matching_and_import_db.utils.common import haversine_distance

from matching_and_import_db.predicates.exact_matching import ExactUicPredicate
from matching_and_import_db.predicates.name_matching import NameMatchPredicate
from matching_and_import_db.predicates.trio_distance_matching import TrioDistanceMatchingPredicate
from matching_and_import_db.predicates.distance_matching import GroupProximityPredicate, LocalRefDistancePredicate, NearestDistancePredicate
from matching_and_import_db.predicates.route_matching_gtfs import RouteMatchPredicate
from matching_and_import_db.predicates.postpass_matching import PostpassUniqueUicPredicate

DEFAULT_PIPELINE = [
    TrioDistanceMatchingPredicate(),
    ExactUicPredicate(),
    NameMatchPredicate(),
    GroupProximityPredicate(),
    LocalRefDistancePredicate(),
    NearestDistancePredicate(),
    RouteMatchPredicate(),
    PostpassUniqueUicPredicate(),
]


def _build_atlas_uic_nearest_osm_distances(
    atlas_df: pd.DataFrame,
    osm_index: OsmState,
) -> dict[str, list[float]]:
    """Return per-UIC nearest OSM distances for ATLAS rows.

    Distances are measured from each ATLAS row to the nearest OSM node sharing
    the same UIC. Rows with invalid coordinates or UICs without OSM entries are
    skipped.
    """
    distances_by_uic: dict[str, list[float]] = defaultdict(list)

    for _, row in atlas_df.iterrows():
        uic = str(row.get('number', '')).strip()
        if not uic:
            continue

        osm_entries = osm_index._uic_ref_dict.get(uic, [])
        if not osm_entries:
            continue

        try:
            lat = float(row['wgs84North'])
            lon = float(row['wgs84East'])
        except (TypeError, ValueError, KeyError):
            continue

        nearest_distance = None
        for entry in osm_entries:
            distance = haversine_distance(lat, lon, entry['lat'], entry['lon'])
            if distance is None:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance

        if nearest_distance is not None:
            distances_by_uic[uic].append(nearest_distance)

    return dict(distances_by_uic)


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

def run_matching() -> MatchingOutput:
    """
    Execute the complete matching pipeline and return data for DB import.

    Returns
    -------
    output : MatchingOutput
        Pipeline results combined with pre-pipeline state (duplicate groups,
        OSM sibling groups, all OSM nodes).
    """

    # ── Load data ────────────────────────────────────────────────────────
    atlas_csv_file = _locate_file('ATLAS_STOPS_CSV', 'data/raw/stops_ATLAS.csv', 'ATLAS')
    osm_xml_file = _locate_file('OSM_XML_FILE', 'data/raw/osm_data.xml', 'OSM')

    atlas_df = pd.read_csv(atlas_csv_file, sep=";")

    osm_index = OsmState.from_xml_file(osm_xml_file)

    # ── Identify ATLAS duplicate groups & init State ─────────────────────
    atlas_state = AtlasState.from_dataframe(
        atlas_df,
        routes_csv_path='data/processed/atlas_routes_gtfs.csv',
    )

    # ── Pre-group platform ↔ stop_position pairs ─────────────────────────
    atlas_uic_counts = {str(k): v for k, v in atlas_df.groupby('number').size().items()}
    atlas_uic_nearest_osm_distances = _build_atlas_uic_nearest_osm_distances(atlas_df, osm_index)

    # Build designationOfficial → UIC mapping for name-based group anchoring
    atlas_designation_to_uic: dict[str, str] = {}
    for _, row in atlas_df.iterrows():
        desig = str(row.get('designationOfficial', '')).strip()
        uic = str(row.get('number', '')).strip()
        if desig and uic:
            atlas_designation_to_uic[desig] = uic

    osm_index.build_groups(
        atlas_uic_counts,
        atlas_designation_to_uic,
        atlas_uic_nearest_osm_distances,
    )

    # ATLAS duplicate grouping now happens automatically in AtlasState.__init__

    ctx = MatchingContext(
        atlas=atlas_state,
        osm=osm_index,
        max_distance=50.0,
    )

    pipeline = DEFAULT_PIPELINE

    pipeline_result = run_pipeline(pipeline, ctx)

    # Build canonical OSM stop units (single / pair / trio).
    all_osm_nodes = osm_index.get_all_nodes()
    stop_units: list[OsmStopUnitRecord] = []
    grouped_node_ids: set[str] = set()

    for rep_id, (group_type, siblings) in osm_index._group_siblings.items():
        rep_node_id = str(rep_id)

        if group_type.startswith('osm_pair_'):
            if not siblings:
                continue
            partner_id = str(siblings[0].node_id)
            stop_units.append(OsmStopUnitRecord(
                stop_kind='pair',
                group_kind=group_type,
                representative_node_id=rep_node_id,
                members=[
                    OsmStopMemberRecord(node_id=rep_node_id, member_role='pair_a'),
                    OsmStopMemberRecord(node_id=partner_id, member_role='pair_b'),
                ],
            ))
            grouped_node_ids.update([rep_node_id, partner_id])
            continue

        if group_type == 'osm_trio':
            trio = osm_index.get_trio_for_representative(rep_node_id)
            if trio is None:
                continue
            middle_node_id, side_node_id_1, side_node_id_2 = trio
            middle_node_id = str(middle_node_id)
            side_node_id_1 = str(side_node_id_1)
            side_node_id_2 = str(side_node_id_2)
            stop_units.append(OsmStopUnitRecord(
                stop_kind='trio',
                group_kind='osm_trio',
                representative_node_id=rep_node_id,
                members=[
                    OsmStopMemberRecord(node_id=middle_node_id, member_role='trio_middle'),
                    OsmStopMemberRecord(node_id=side_node_id_1, member_role='trio_side'),
                    OsmStopMemberRecord(node_id=side_node_id_2, member_role='trio_side'),
                ],
            ))
            grouped_node_ids.update([middle_node_id, side_node_id_1, side_node_id_2])

    for node in all_osm_nodes:
        node_id = str(node.node_id)
        if node_id in grouped_node_ids:
            continue
        stop_units.append(OsmStopUnitRecord(
            stop_kind='single',
            group_kind=None,
            representative_node_id=node_id,
            members=[OsmStopMemberRecord(node_id=node_id, member_role='single')],
        ))

    output = MatchingOutput(
        matched=pipeline_result.matched,
        unmatched_atlas=pipeline_result.unmatched_atlas,
        unmatched_osm=pipeline_result.unmatched_osm,
        duplicate_sloid_map=atlas_state.duplicate_sloid_map,
        osm_stop_units=stop_units,
        all_osm_nodes=all_osm_nodes,
    )

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
