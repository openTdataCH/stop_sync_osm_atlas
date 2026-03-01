"""
OSM Node Grouping Experiment — Phase 1 Validation

Loads baseline match data from the existing import_db (no pipeline re-run),
then applies both grouping strategies (Option A and Option B) as a pure
analysis pass over the OSM XML. Cross-references proposed groups against
the DB matches to classify each group as:

  - Concordant: both members matched to the same ATLAS stop
  - Rescue:     one matched, one unmatched (the case we want to fix)
  - Neutral:    both unmatched
  - Conflict:   matched to DIFFERENT ATLAS stops (red flag)

Outputs:
  - Console summary with stats per option
  - data/debug/grouping_option_a.csv   — all proposed groups with classification
  - data/debug/grouping_option_b.csv   — all proposed groups with classification
  - data/debug/grouping_conflicts.csv  — conflict groups only (both options)

Run:
    python -m tests.matching_pipeline.test_osm_grouping_experiment

Requires:
  - PostgreSQL import_db running locally (default connection)
  - data/raw/osm_data.xml present
"""

import csv
import os
import sys
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from matching_and_import_db.state import OsmState
from matching_and_import_db.models import OsmNode
from matching_and_import_db.utils.common import haversine_distance

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_GROUP_DISTANCE_M = 12.0
RATIO_TEST_FACTOR = 1.5


# ---------------------------------------------------------------------------
# Domain types for the experiment
# ---------------------------------------------------------------------------

@dataclass
class ProposedGroup:
    node_a_id: str
    node_b_id: str
    distance_m: float
    shared_key: str        # what identity they share: 'uic_ref', 'name', etc.
    shared_value: str      # the actual shared value
    role_a: str            # public_transport value of node A
    role_b: str            # public_transport value of node B
    option: str            # 'A' or 'B'
    # Filled after cross-referencing with baseline
    category: str = ""     # Concordant / Rescue / Neutral / Conflict
    atlas_a: str = ""      # ATLAS sloid matched to node A (or "")
    atlas_b: str = ""      # ATLAS sloid matched to node B (or "")


# ---------------------------------------------------------------------------
# Helper: get the public_transport role of a node
# ---------------------------------------------------------------------------

def _pt_role(node: OsmNode) -> str:
    """Return a normalized role string for grouping purposes."""
    pt = node.public_transport or ""
    if pt in ("platform", "stop_position", "station", "halt", "stop"):
        return pt
    # Fallback: check highway/railway tags
    if node.tags.get("highway") == "bus_stop":
        return "platform"  # bus_stop is functionally a platform
    if node.railway in ("tram_stop", "halt"):
        return "stop_position"
    return pt or "unknown"


def _is_platform_role(role: str) -> bool:
    return role in ("platform",)


def _is_stop_position_role(role: str) -> bool:
    return role in ("stop_position",)


def _roles_are_complementary(role_a: str, role_b: str) -> bool:
    """True when one is platform-like and the other is stop_position-like."""
    return (
        (_is_platform_role(role_a) and _is_stop_position_role(role_b)) or
        (_is_stop_position_role(role_a) and _is_platform_role(role_b))
    )


# ---------------------------------------------------------------------------
# Load baseline from database
# ---------------------------------------------------------------------------

def load_baseline_from_db() -> dict[str, set[str]]:
    """
    Query stops_matched for all matched rows.
    Returns {osm_node_id: {sloid, ...}} mapping.
    """
    from sqlalchemy import create_engine, text

    db_uri = os.getenv(
        "DATABASE_URI",
        "postgresql+psycopg://stops_user:1234@localhost:5432/import_db",
    )
    engine = create_engine(db_uri)

    osm_to_atlas: dict[str, set[str]] = defaultdict(set)
    match_types: Counter = Counter()
    total_rows = 0

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT sloid, osm_node_id, match_type "
            "FROM stops_matched "
            "WHERE stop_type = 'matched'"
        ))
        for sloid, osm_node_id, match_type in rows:
            osm_to_atlas[osm_node_id].add(sloid)
            match_types[match_type] += 1
            total_rows += 1

    distinct_atlas = len({s for sloids in osm_to_atlas.values() for s in sloids})
    distinct_osm = len(osm_to_atlas)

    print(f"  Loaded {total_rows} match records from DB")
    print(f"  {distinct_atlas} distinct ATLAS sloids, {distinct_osm} distinct OSM nodes")
    print(f"  Match types: {dict(sorted(match_types.items(), key=lambda x: -x[1]))}")

    return osm_to_atlas


def load_osm_stats_from_db() -> dict[str, str]:
    """
    Load osm_node_id → osm_public_transport from DB for stats.
    Returns {osm_node_id: public_transport_value}.
    """
    from sqlalchemy import create_engine, text

    db_uri = os.getenv(
        "DATABASE_URI",
        "postgresql+psycopg://stops_user:1234@localhost:5432/import_db",
    )
    engine = create_engine(db_uri)

    result = {}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT osm_node_id, osm_public_transport FROM osm_nodes"
        ))
        for node_id, pt in rows:
            result[node_id] = pt or ""

    return result


# ---------------------------------------------------------------------------
# Grouping Option A: Proximity + Identity + Complementary Roles + Ratio Test
# ---------------------------------------------------------------------------

def compute_groups_option_a(osm_state: OsmState) -> list[ProposedGroup]:
    """
    For every stop_position node, find the nearest platform node within 12m
    that shares an identity (uic_ref or name). Apply ratio test if ambiguous.
    """
    all_nodes: list[OsmNode] = []
    for entry in osm_state._all_nodes.values():
        node = osm_state._to_osm_node(entry)
        if node.is_station:
            continue
        all_nodes.append(node)

    # Partition by role
    stop_positions = [n for n in all_nodes if _is_stop_position_role(_pt_role(n))]
    platforms = [n for n in all_nodes if _is_platform_role(_pt_role(n))]

    logger.info(f"Option A: {len(stop_positions)} stop_positions, {len(platforms)} platforms")

    # Build identity indexes for platforms
    platform_by_uic: dict[str, list[OsmNode]] = defaultdict(list)
    platform_by_name: dict[str, list[OsmNode]] = defaultdict(list)
    for p in platforms:
        if p.uic_ref:
            platform_by_uic[p.uic_ref].append(p)
        for key in ("name", "uic_name"):
            val = p.tags.get(key)
            if val:
                platform_by_name[val].append(p)

    groups: list[ProposedGroup] = []
    used_sp: set[str] = set()
    used_plat: set[str] = set()

    for sp in stop_positions:
        if sp.node_id in used_sp:
            continue

        # Collect candidate platforms sharing an identity
        candidates: list[tuple[OsmNode, float, str, str]] = []  # (node, dist, key, value)

        # Check uic_ref
        if sp.uic_ref:
            for p in platform_by_uic.get(sp.uic_ref, []):
                if p.node_id in used_plat:
                    continue
                d = haversine_distance(sp.lat, sp.lon, p.lat, p.lon)
                if d is not None and d <= MAX_GROUP_DISTANCE_M:
                    candidates.append((p, d, "uic_ref", sp.uic_ref))

        # Check name / uic_name
        for name_key in ("name", "uic_name"):
            sp_name = sp.tags.get(name_key)
            if not sp_name:
                continue
            for p in platform_by_name.get(sp_name, []):
                if p.node_id in used_plat:
                    continue
                # Avoid duplicates if already found via UIC
                if any(c[0].node_id == p.node_id for c in candidates):
                    continue
                d = haversine_distance(sp.lat, sp.lon, p.lat, p.lon)
                if d is not None and d <= MAX_GROUP_DISTANCE_M:
                    candidates.append((p, d, name_key, sp_name))

        if not candidates:
            continue

        # Sort by distance
        candidates.sort(key=lambda x: x[1])

        # Ratio test: if >1 candidate, second must be 1.5x farther
        if len(candidates) > 1:
            d1 = candidates[0][1]
            d2 = candidates[1][1]
            if d1 == 0:
                pass  # d1=0 means exact overlap, always accept
            elif d2 / d1 < RATIO_TEST_FACTOR:
                continue  # Ambiguous, skip

        best_plat, best_dist, shared_key, shared_val = candidates[0]

        groups.append(ProposedGroup(
            node_a_id=sp.node_id,
            node_b_id=best_plat.node_id,
            distance_m=round(best_dist, 2),
            shared_key=shared_key,
            shared_value=shared_val,
            role_a=_pt_role(sp),
            role_b=_pt_role(best_plat),
            option="A",
        ))
        used_sp.add(sp.node_id)
        used_plat.add(best_plat.node_id)

    return groups


# ---------------------------------------------------------------------------
# Grouping Option B: UIC-Scoped Conflict-Free Pairing
# ---------------------------------------------------------------------------

def compute_groups_option_b(osm_state: OsmState) -> list[ProposedGroup]:
    """
    Within each UIC group, attempt conflict-free 1:1 pairing between
    stop_positions and platforms. If any ambiguity, skip the entire UIC group.
    """
    all_nodes: list[OsmNode] = []
    for entry in osm_state._all_nodes.values():
        node = osm_state._to_osm_node(entry)
        if node.is_station:
            continue
        all_nodes.append(node)

    # Group by UIC
    by_uic: dict[str, list[OsmNode]] = defaultdict(list)
    for n in all_nodes:
        if n.uic_ref:
            by_uic[n.uic_ref].append(n)

    groups: list[ProposedGroup] = []

    for uic, nodes in by_uic.items():
        sps = [n for n in nodes if _is_stop_position_role(_pt_role(n))]
        plats = [n for n in nodes if _is_platform_role(_pt_role(n))]

        if not sps or not plats:
            continue

        # Attempt 1:1 conflict-free nearest-neighbour pairing
        pairs: list[tuple[OsmNode, OsmNode, float]] = []
        used_plat_ids: set[str] = set()
        failed = False

        # Sort stop_positions for determinism
        for sp in sorted(sps, key=lambda n: n.node_id):
            # Find nearest platform within 12m
            best: OsmNode | None = None
            best_dist = float("inf")
            for p in plats:
                if p.node_id in used_plat_ids:
                    continue
                d = haversine_distance(sp.lat, sp.lon, p.lat, p.lon)
                if d is not None and d <= MAX_GROUP_DISTANCE_M and d < best_dist:
                    best = p
                    best_dist = d

            if best is None:
                # This stop_position has no platform partner — that's fine, skip it
                continue

            # Check reciprocal: is this stop_position also the nearest SP for this platform?
            reciprocal_best_dist = float("inf")
            reciprocal_best_sp: OsmNode | None = None
            for sp2 in sps:
                if any(sp2.node_id == pair[0].node_id for pair in pairs):
                    continue  # already paired
                d2 = haversine_distance(best.lat, best.lon, sp2.lat, sp2.lon)
                if d2 is not None and d2 < reciprocal_best_dist:
                    reciprocal_best_sp = sp2
                    reciprocal_best_dist = d2

            if reciprocal_best_sp is None or reciprocal_best_sp.node_id != sp.node_id:
                # Conflict: the platform's nearest SP is a different one
                failed = True
                break

            pairs.append((sp, best, best_dist))
            used_plat_ids.add(best.node_id)

        if failed:
            continue  # Skip entire UIC group on any conflict

        for sp, plat, dist in pairs:
            groups.append(ProposedGroup(
                node_a_id=sp.node_id,
                node_b_id=plat.node_id,
                distance_m=round(dist, 2),
                shared_key="uic_ref",
                shared_value=uic,
                role_a=_pt_role(sp),
                role_b=_pt_role(plat),
                option="B",
            ))

    return groups


# ---------------------------------------------------------------------------
# Cross-reference groups against baseline matches
# ---------------------------------------------------------------------------

def classify_groups(
    groups: list[ProposedGroup],
    osm_to_atlas: dict[str, set[str]],
) -> list[ProposedGroup]:
    """
    For each proposed group, look up whether its members are matched
    in the baseline and classify as Concordant/Rescue/Neutral/Conflict.
    """
    for g in groups:
        atlas_a = osm_to_atlas.get(g.node_a_id, set())
        atlas_b = osm_to_atlas.get(g.node_b_id, set())

        g.atlas_a = ";".join(sorted(atlas_a)) if atlas_a else ""
        g.atlas_b = ";".join(sorted(atlas_b)) if atlas_b else ""

        if atlas_a and atlas_b:
            if atlas_a & atlas_b:
                g.category = "Concordant"
            else:
                g.category = "Conflict"
        elif atlas_a or atlas_b:
            g.category = "Rescue"
        else:
            g.category = "Neutral"

    return groups


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def compute_osm_match_stats(
    osm_to_atlas: dict[str, set[str]],
    groups: list[ProposedGroup],
    osm_state: OsmState,
) -> dict:
    """
    Compute how many OSM nodes are matched/unmatched, broken down by role,
    with and without the grouping strategy applied.
    """
    # All non-station OSM nodes
    all_nodes: list[OsmNode] = []
    for entry in osm_state._all_nodes.values():
        node = osm_state._to_osm_node(entry)
        if not node.is_station:
            all_nodes.append(node)

    platforms = [n for n in all_nodes if _is_platform_role(_pt_role(n))]
    stop_positions = [n for n in all_nodes if _is_stop_position_role(_pt_role(n))]
    other_role = [n for n in all_nodes
                  if not _is_platform_role(_pt_role(n))
                  and not _is_stop_position_role(_pt_role(n))]

    # Baseline: which OSM node_ids are matched?
    baseline_matched_ids: set[str] = set(osm_to_atlas.keys())

    # With grouping: siblings would also be consumed
    sibling_ids: set[str] = set()
    for g in groups:
        if g.category != "Conflict":
            if g.node_a_id in baseline_matched_ids:
                sibling_ids.add(g.node_b_id)
            elif g.node_b_id in baseline_matched_ids:
                sibling_ids.add(g.node_a_id)

    grouped_matched_ids = baseline_matched_ids | sibling_ids

    def _stats(nodes, matched_ids):
        matched = sum(1 for n in nodes if n.node_id in matched_ids)
        return matched, len(nodes) - matched, len(nodes)

    return {
        "baseline": {
            "total":          _stats(all_nodes, baseline_matched_ids),
            "platforms":      _stats(platforms, baseline_matched_ids),
            "stop_positions": _stats(stop_positions, baseline_matched_ids),
            "other":          _stats(other_role, baseline_matched_ids),
        },
        "with_grouping": {
            "total":          _stats(all_nodes, grouped_matched_ids),
            "platforms":      _stats(platforms, grouped_matched_ids),
            "stop_positions": _stats(stop_positions, grouped_matched_ids),
            "other":          _stats(other_role, grouped_matched_ids),
        },
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_groups_csv(groups: list[ProposedGroup], path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "option", "category", "node_a_id", "role_a",
            "node_b_id", "role_b", "distance_m",
            "shared_key", "shared_value", "atlas_a", "atlas_b",
        ])
        for g in sorted(groups, key=lambda g: (g.category, g.distance_m)):
            w.writerow([
                g.option, g.category, g.node_a_id, g.role_a,
                g.node_b_id, g.role_b, g.distance_m,
                g.shared_key, g.shared_value, g.atlas_a, g.atlas_b,
            ])
    logger.info(f"Wrote {len(groups)} groups to {path}")


def print_stats_table(label: str, stats: dict):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'Role':<20} {'Matched':>10} {'Unmatched':>10} {'Total':>10} {'Match %':>10}")
    print(f"  {'-'*60}")
    for role in ("total", "platforms", "stop_positions", "other"):
        matched, unmatched, total = stats[role]
        pct = f"{matched/total*100:.1f}%" if total > 0 else "N/A"
        print(f"  {role:<20} {matched:>10} {unmatched:>10} {total:>10} {pct:>10}")


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def run_experiment():
    # ── 1. Load baseline from DB ─────────────────────────────────────────
    print("\n[Step 1] Loading baseline matches from import_db...")
    osm_to_atlas = load_baseline_from_db()

    # ── 2. Load OsmState from XML for grouping analysis ──────────────────
    osm_xml = os.getenv("OSM_XML_FILE", "data/raw/osm_data.xml")
    print(f"\n[Step 2] Parsing OSM XML from {osm_xml}...")
    osm_state = OsmState.from_xml_file(osm_xml)

    # ── 3. Compute groups for both options ───────────────────────────────
    print("\n[Step 3] Computing proposed groups...")
    groups_a = compute_groups_option_a(osm_state)
    groups_b = compute_groups_option_b(osm_state)

    # ── 4. Classify groups against baseline ──────────────────────────────
    print("\n[Step 4] Classifying groups against baseline matches...")
    classify_groups(groups_a, osm_to_atlas)
    classify_groups(groups_b, osm_to_atlas)

    # ── 5. Print classification summary ──────────────────────────────────
    for label, groups in [("Option A", groups_a), ("Option B", groups_b)]:
        cats = Counter(g.category for g in groups)
        print(f"\n  {label}: {len(groups)} groups total")
        for cat in ("Concordant", "Rescue", "Neutral", "Conflict"):
            print(f"    {cat:<15} {cats.get(cat, 0):>6}")

    # ── 6. OSM match stats (baseline vs with-grouping) ───────────────────
    for label, groups in [("Option A", groups_a), ("Option B", groups_b)]:
        stats = compute_osm_match_stats(osm_to_atlas, groups, osm_state)
        print_stats_table(f"Baseline (no grouping)", stats["baseline"])
        print_stats_table(f"With {label} grouping (projected)", stats["with_grouping"])

    # ── 7. Write CSVs ────────────────────────────────────────────────────
    print("\n[Step 7] Writing output files...")
    write_groups_csv(groups_a, "data/debug/grouping_option_a.csv")
    write_groups_csv(groups_b, "data/debug/grouping_option_b.csv")

    # Conflicts from both options combined
    conflicts = [g for g in groups_a + groups_b if g.category == "Conflict"]
    write_groups_csv(conflicts, "data/debug/grouping_conflicts.csv")

    # ── 8. Final verdict ─────────────────────────────────────────────────
    conflicts_a = sum(1 for g in groups_a if g.category == "Conflict")
    conflicts_b = sum(1 for g in groups_b if g.category == "Conflict")

    print(f"\n{'='*70}")
    print(f"  VERDICT")
    print(f"{'='*70}")
    print(f"  Option A conflicts: {conflicts_a}")
    print(f"  Option B conflicts: {conflicts_b}")
    if conflicts_a == 0 and conflicts_b == 0:
        print("  Both options pass Phase 1 (zero conflicts). Safe to proceed to Phase 2.")
    else:
        print("  Review data/debug/grouping_conflicts.csv before proceeding.")
    print()


if __name__ == "__main__":
    run_experiment()
