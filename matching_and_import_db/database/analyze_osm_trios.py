"""
Analyze strict OSM trio candidates and simulate a trio-aware matching strategy.

Definition used for an OSM trio UIC:
- Exactly 3 OSM nodes for one UIC
- Exactly 1 of those nodes has osm_node_type='stop_position'
- Exactly 2 ATLAS stops for that same UIC

Simulation used in this script:
- Group trios before predicates.
- For each trio UIC, match the 2 ATLAS stops to the 2 non-stop_position OSM nodes
  using minimum total distance assignment (2x2 exhaustive check).
- The stop_position node remains unmatched to ATLAS, but flagged as a trio partner.

Outputs are written to data/debug by default.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from matching_and_import_db.database.session import engine


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "data" / "debug"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two WGS84 points in meters."""
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def strict_trio_uics() -> pd.DataFrame:
    query = text(
        """
        WITH osm_by_uic AS (
          SELECT
            osm_uic_ref AS uic_ref,
            COUNT(*) AS osm_nodes,
            COUNT(*) FILTER (WHERE osm_node_type = 'stop_position') AS stop_position_nodes
          FROM osm_nodes
          WHERE osm_uic_ref IS NOT NULL AND btrim(osm_uic_ref) <> ''
          GROUP BY osm_uic_ref
        ),
        atlas_by_uic AS (
          SELECT
            uic_ref,
            COUNT(*) AS atlas_nodes
          FROM atlas_stops
          WHERE uic_ref IS NOT NULL AND btrim(uic_ref) <> ''
          GROUP BY uic_ref
        )
        SELECT o.uic_ref
        FROM osm_by_uic o
        JOIN atlas_by_uic a ON a.uic_ref = o.uic_ref
        WHERE o.osm_nodes = 3
          AND o.stop_position_nodes = 1
          AND a.atlas_nodes = 2
        ORDER BY o.uic_ref
        """
    )
    return pd.read_sql(query, engine)


def fetch_atlas_with_coords() -> pd.DataFrame:
    query = text(
        """
        SELECT DISTINCT ON (a.sloid)
          a.uic_ref,
          a.sloid,
          sm.atlas_lat,
          sm.atlas_lon
        FROM atlas_stops a
        LEFT JOIN stops_matched sm
          ON sm.sloid = a.sloid
         AND sm.atlas_lat IS NOT NULL
         AND sm.atlas_lon IS NOT NULL
        ORDER BY a.sloid, sm.id
        """
    )
    return pd.read_sql(query, engine)


def fetch_osm_with_coords() -> pd.DataFrame:
    query = text(
        """
        SELECT DISTINCT ON (o.osm_node_id)
          o.osm_uic_ref,
          o.osm_node_id,
          o.osm_node_type,
          sm.osm_lat,
          sm.osm_lon
        FROM osm_nodes o
        LEFT JOIN stops_matched sm
          ON sm.osm_node_id = o.osm_node_id
         AND sm.osm_lat IS NOT NULL
         AND sm.osm_lon IS NOT NULL
        ORDER BY o.osm_node_id, sm.id
        """
    )
    return pd.read_sql(query, engine)


def fetch_best_current_status_per_osm_node() -> pd.DataFrame:
    query = text(
        """
        SELECT
          id,
          osm_node_id,
          stop_type,
          match_type
        FROM stops_matched
        WHERE osm_node_id IS NOT NULL
        ORDER BY id
        """
    )
    df = pd.read_sql(query, engine)

    # If duplicated statuses exist for one OSM node, keep non-duplicate_propagation first.
    df["_priority"] = (df["match_type"] == "duplicate_propagation").astype(int)
    best = (
        df.sort_values(["osm_node_id", "_priority", "id"])
        .drop_duplicates(subset=["osm_node_id"], keep="first")
        .drop(columns=["_priority"])
    )
    return best


def bucket_from_status(stop_type: str | None, match_type: str | None) -> str:
    if match_type == "trio_distance_matching":
        return "matched_by_trio_distance"
    if match_type == "osm_trio_partner_unmatched":
        return "unmatched_trio_partner"
    if stop_type == "osm_unmatched":
        return "unmatched"
    if match_type in {"route_unified_gtfs", "route_unified_hrdf"}:
        return "matched_by_route"
    if match_type == "osm_group_propagation":
        return "matched_by_osm_group_propagation"
    if match_type == "exact":
        return "matched_exact"
    if match_type == "exact_postpass":
        return "matched_exact_postpass"
    if match_type == "name":
        return "matched_name"
    if match_type and match_type.startswith("distance_matching"):
        return "matched_distance"
    if match_type == "duplicate_propagation":
        return "matched_duplicate_propagation"
    if match_type is None:
        return "other_or_null"
    return "other_match_type"


def simulate_trio_distance(
    trio_uics: pd.DataFrame,
    atlas_coords: pd.DataFrame,
    osm_coords: pd.DataFrame,
    current_status: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    trio_set = set(trio_uics["uic_ref"].astype(str))

    atlas = atlas_coords.copy()
    atlas["uic_ref"] = atlas["uic_ref"].astype(str)
    atlas = atlas[atlas["uic_ref"].isin(trio_set)]

    osm = osm_coords.copy()
    osm["osm_uic_ref"] = osm["osm_uic_ref"].astype(str)
    osm = osm[osm["osm_uic_ref"].isin(trio_set)]

    current = current_status.copy()
    current["osm_node_id"] = current["osm_node_id"].astype(str)

    assignments: list[dict] = []
    failures: list[dict] = []

    for uic in sorted(trio_set):
        a = atlas[atlas["uic_ref"] == uic].copy()
        o = osm[osm["osm_uic_ref"] == uic].copy()

        if len(a) != 2 or len(o) != 3:
            failures.append({"uic_ref": uic, "reason": "invalid_cardinality"})
            continue

        stop_pos = o[o["osm_node_type"] == "stop_position"]
        sides = o[o["osm_node_type"] != "stop_position"]

        if len(stop_pos) != 1 or len(sides) != 2:
            failures.append({"uic_ref": uic, "reason": "invalid_node_types"})
            continue

        if (
            a[["atlas_lat", "atlas_lon"]].isna().any().any()
            or sides[["osm_lat", "osm_lon"]].isna().any().any()
        ):
            failures.append({"uic_ref": uic, "reason": "missing_coordinates"})
            continue

        a0 = a.iloc[0]
        a1 = a.iloc[1]
        s0 = sides.iloc[0]
        s1 = sides.iloc[1]

        d00 = haversine_m(float(a0["atlas_lat"]), float(a0["atlas_lon"]), float(s0["osm_lat"]), float(s0["osm_lon"]))
        d11 = haversine_m(float(a1["atlas_lat"]), float(a1["atlas_lon"]), float(s1["osm_lat"]), float(s1["osm_lon"]))
        d01 = haversine_m(float(a0["atlas_lat"]), float(a0["atlas_lon"]), float(s1["osm_lat"]), float(s1["osm_lon"]))
        d10 = haversine_m(float(a1["atlas_lat"]), float(a1["atlas_lon"]), float(s0["osm_lat"]), float(s0["osm_lon"]))

        if d00 + d11 <= d01 + d10:
            pairs = [(a0, s0, d00), (a1, s1, d11)]
        else:
            pairs = [(a0, s1, d01), (a1, s0, d10)]

        for atlas_row, osm_row, dist in pairs:
            assignments.append(
                {
                    "uic_ref": uic,
                    "atlas_sloid": str(atlas_row["sloid"]),
                    "osm_node_id": str(osm_row["osm_node_id"]),
                    "osm_node_type": osm_row["osm_node_type"],
                    "simulated_stop_type": "matched",
                    "simulated_match_type": "trio_distance_matching",
                    "simulated_distance_m": dist,
                }
            )

        middle = stop_pos.iloc[0]
        assignments.append(
            {
                "uic_ref": uic,
                "atlas_sloid": None,
                "osm_node_id": str(middle["osm_node_id"]),
                "osm_node_type": middle["osm_node_type"],
                "simulated_stop_type": "osm_unmatched",
                "simulated_match_type": "osm_trio_partner_unmatched",
                "simulated_distance_m": None,
            }
        )

    sim_df = pd.DataFrame(assignments)
    fail_df = pd.DataFrame(failures)

    if sim_df.empty:
        return sim_df, fail_df

    sim_df = sim_df.merge(
        current[["osm_node_id", "stop_type", "match_type"]],
        on="osm_node_id",
        how="left",
    )
    sim_df = sim_df.rename(columns={"stop_type": "current_stop_type", "match_type": "current_match_type"})
    sim_df["current_bucket"] = sim_df.apply(
        lambda r: bucket_from_status(r["current_stop_type"], r["current_match_type"]),
        axis=1,
    )
    sim_df["simulated_bucket"] = sim_df.apply(
        lambda r: bucket_from_status(r["simulated_stop_type"], r["simulated_match_type"]),
        axis=1,
    )

    return sim_df, fail_df


def build_full_list(trio_uics: pd.DataFrame, atlas_coords: pd.DataFrame, osm_coords: pd.DataFrame) -> pd.DataFrame:
    trio_set = set(trio_uics["uic_ref"].astype(str))

    atlas = atlas_coords.copy()
    atlas["uic_ref"] = atlas["uic_ref"].astype(str)
    atlas = atlas[atlas["uic_ref"].isin(trio_set)]

    osm = osm_coords.copy()
    osm["osm_uic_ref"] = osm["osm_uic_ref"].astype(str)
    osm = osm[osm["osm_uic_ref"].isin(trio_set)]

    rows: list[dict] = []
    for uic in sorted(trio_set):
        a = atlas[atlas["uic_ref"] == uic]
        o = osm[osm["osm_uic_ref"] == uic]

        sloids = sorted(a["sloid"].dropna().astype(str).tolist())
        node_ids = sorted(o["osm_node_id"].dropna().astype(str).tolist())

        stop_positions = sorted(
            o[o["osm_node_type"] == "stop_position"]["osm_node_id"].dropna().astype(str).tolist()
        )
        non_stop_positions = sorted(
            o[o["osm_node_type"] != "stop_position"]["osm_node_id"].dropna().astype(str).tolist()
        )

        rows.append(
            {
                "uic_ref": uic,
                "atlas_count": len(sloids),
                "atlas_sloids": ";".join(sloids),
                "osm_count": len(node_ids),
                "osm_node_ids": ";".join(node_ids),
                "stop_position_node_id": stop_positions[0] if len(stop_positions) == 1 else None,
                "non_stop_position_node_ids": ";".join(non_stop_positions),
            }
        )

    return pd.DataFrame(rows)


def write_outputs(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    trio_uics = strict_trio_uics()
    atlas_coords = fetch_atlas_with_coords()
    osm_coords = fetch_osm_with_coords()
    current_status = fetch_best_current_status_per_osm_node()

    full_list = build_full_list(trio_uics, atlas_coords, osm_coords)
    sim_df, fail_df = simulate_trio_distance(trio_uics, atlas_coords, osm_coords, current_status)

    current_trio_nodes = full_list[["uic_ref", "osm_node_ids"]].copy()
    current_trio_nodes = current_trio_nodes.assign(osm_node_id=current_trio_nodes["osm_node_ids"].str.split(";"))
    current_trio_nodes = current_trio_nodes.explode("osm_node_id").drop(columns=["osm_node_ids"])
    current_trio_nodes["osm_node_id"] = current_trio_nodes["osm_node_id"].astype(str)

    current_status_for_trios = current_trio_nodes.merge(
        current_status[["osm_node_id", "stop_type", "match_type"]],
        on="osm_node_id",
        how="left",
    )
    current_status_for_trios["bucket"] = current_status_for_trios.apply(
        lambda r: bucket_from_status(r["stop_type"], r["match_type"]),
        axis=1,
    )

    current_hist = (
        current_status_for_trios.groupby(["bucket", "match_type", "stop_type"], dropna=False)
        .size()
        .reset_index(name="node_count")
        .sort_values("node_count", ascending=False)
    )

    simulated_hist = (
        sim_df.groupby(["simulated_bucket", "simulated_match_type", "simulated_stop_type"], dropna=False)
        .size()
        .reset_index(name="node_count")
        .sort_values("node_count", ascending=False)
    )

    transitions = (
        sim_df.groupby(["current_bucket", "current_match_type", "simulated_match_type"], dropna=False)
        .size()
        .reset_index(name="node_count")
        .sort_values("node_count", ascending=False)
    )

    paths = {
        "full_list": out_dir / "osm_trio_uics_full_list.csv",
        "current_status": out_dir / "osm_trio_current_status_per_node.csv",
        "current_hist": out_dir / "osm_trio_current_histogram.csv",
        "simulated_assignments": out_dir / "osm_trio_simulated_assignments.csv",
        "simulated_hist": out_dir / "osm_trio_simulated_histogram.csv",
        "transitions": out_dir / "osm_trio_status_transition_histogram.csv",
        "simulation_failures": out_dir / "osm_trio_simulation_failures.csv",
    }

    full_list.to_csv(paths["full_list"], index=False)
    current_status_for_trios.to_csv(paths["current_status"], index=False)
    current_hist.to_csv(paths["current_hist"], index=False)
    sim_df.to_csv(paths["simulated_assignments"], index=False)
    simulated_hist.to_csv(paths["simulated_hist"], index=False)
    transitions.to_csv(paths["transitions"], index=False)
    fail_df.to_csv(paths["simulation_failures"], index=False)

    print(f"Trio UICs found: {len(full_list)}")
    print(f"Simulated assignments rows: {len(sim_df)}")
    print(f"Simulation failures: {len(fail_df)}")

    print("\nOutput files:")
    for name, path in paths.items():
        print(f"- {name}: {path}")

    if not simulated_hist.empty:
        print("\nSimulated histogram:")
        print(simulated_hist.to_string(index=False))

    if not transitions.empty:
        print("\nTop transitions (current -> simulated):")
        print(transitions.head(15).to_string(index=False))

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze and simulate OSM trio grouping outcomes.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Directory where CSV outputs are written (default: data/debug).",
    )
    args = parser.parse_args()

    write_outputs(Path(args.output_dir))


if __name__ == "__main__":
    main()
