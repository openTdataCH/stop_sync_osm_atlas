import os
import json
import math
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


DATA_RAW_XML_PATH = "data/raw/osm_data.xml"
NODES_ROUTES_CSV_PATH = "data/processed/osm_nodes_with_routes.csv"
ROUTES_WITH_NODES_CSV_PATH = "data/processed/osm_routes_with_nodes.csv"
PLOTS_DIR = "memoire/figures/plots"


def ensure_directories() -> None:
    os.makedirs(os.path.dirname(DATA_RAW_XML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(NODES_ROUTES_CSV_PATH), exist_ok=True)
    os.makedirs(PLOTS_DIR, exist_ok=True)


def load_or_fetch_xml() -> Optional[str]:
    """Return OSM XML as text. If missing locally, fetch via Overpass using project helper."""
    if os.path.exists(DATA_RAW_XML_PATH):
        with open(DATA_RAW_XML_PATH, "r", encoding="utf-8") as f:
            return f.read()

    # Fallback: fetch using the project's helper (network call)
    try:
        from get_osm_data import query_overpass  # type: ignore

        xml = query_overpass()
        return xml
    except Exception as exc:  # pragma: no cover - best-effort fallback
        print(f"Could not fetch OSM data automatically: {exc}")
        return None


def ensure_processed_csv(xml_text: str) -> Optional[pd.DataFrame]:
    """Ensure we have the nodes-with-routes CSV; build it if missing, then return as DataFrame."""
    if os.path.exists(NODES_ROUTES_CSV_PATH):
        try:
            return pd.read_csv(NODES_ROUTES_CSV_PATH)
        except Exception as exc:
            print(f"Failed to read {NODES_ROUTES_CSV_PATH}: {exc}")

    try:
        from get_osm_data import process_osm_data_to_csv  # type: ignore

        process_osm_data_to_csv(xml_text, NODES_ROUTES_CSV_PATH)
        return pd.read_csv(NODES_ROUTES_CSV_PATH)
    except Exception as exc:  # pragma: no cover - best-effort fallback
        print(f"Could not create processed CSV automatically: {exc}")
        return None


def parse_nodes_from_xml(xml_text: str) -> pd.DataFrame:
    """Parse nodes and selected tags from OSM XML into a DataFrame."""
    root = ET.fromstring(xml_text)

    records: List[Dict[str, Optional[str]]] = []
    for node in root.findall(".//node"):
        node_id = node.get("id")
        lat = node.get("lat")
        lon = node.get("lon")

        tags: Dict[str, Optional[str]] = {
            "public_transport": None,
            "highway": None,
            "railway": None,
            "amenity": None,
            "aerialway": None,
            "uic_ref": None,
            "ref": None,
            "local_ref": None,
            "name": None,
            "network": None,
            "operator": None,
            "uic_name": None,
        }

        for tag in node.findall("./tag"):
            k = tag.get("k")
            v = tag.get("v")
            if k in tags:
                tags[k] = v

        # Derive a consolidated node_type similar to the extractor used in get_osm_data.py
        node_type: Optional[str] = None
        if tags["public_transport"]:
            node_type = tags["public_transport"]
        elif tags["highway"] == "bus_stop":
            node_type = "bus_stop"
        elif tags["railway"] in {"station", "halt", "tram_stop"}:
            node_type = tags["railway"]
        elif tags["amenity"] in {"bus_station", "ferry_terminal"}:
            node_type = tags["amenity"]
        elif tags["aerialway"] == "station":
            node_type = "aerialway_station"

        record = {
            "node_id": node_id,
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "node_type": node_type,
            **tags,
        }
        records.append(record)

    df = pd.DataFrame.from_records(records)
    return df


def extract_node_to_route_ids_from_xml(xml_text: str) -> Dict[str, Set[str]]:
    """Build a mapping node_id -> set(route_relation_id) from XML relations."""
    root = ET.fromstring(xml_text)
    node_to_routes: Dict[str, Set[str]] = {}

    for relation in root.findall(".//relation"):
        is_route = False
        for tag in relation.findall("./tag"):
            if tag.get("k") == "type" and tag.get("v") == "route":
                is_route = True
                break
        if not is_route:
            continue

        rid = relation.get("id") or ""
        for member in relation.findall("./member[@type='node']"):
            node_ref = member.get("ref")
            if not node_ref:
                continue
            node_to_routes.setdefault(node_ref, set()).add(rid)

    return node_to_routes


def compute_routes_per_node_counts(
    nodes_routes_df: Optional[pd.DataFrame], xml_text: Optional[str]
) -> pd.Series:
    """
    Return a Series indexed by node_id with the number of distinct routes per node.
    Prefer the CSV (faster, already processed). Fallback to relation parsing from XML.
    """
    if nodes_routes_df is not None and not nodes_routes_df.empty:
        df = nodes_routes_df.copy()

        # Build a route key that is reasonably distinct
        def route_key(row: pd.Series) -> str:
            route_id = str(row.get("gtfs_route_id") or "").strip()
            name = str(row.get("route_name") or "").strip()
            # Prefer gtfs_route_id; fallback to name; ensure non-empty
            return route_id if route_id else (name if name else "__unnamed__")

        df["route_key"] = df.apply(route_key, axis=1)
        counts = (
            df.groupby("node_id")["route_key"].nunique().sort_values(ascending=False)
        )
        return counts

    # Fallback: derive from XML relations
    if xml_text:
        mapping = extract_node_to_route_ids_from_xml(xml_text)
        counts_map = {nid: len(rids) for nid, rids in mapping.items()}
        counts = pd.Series(counts_map, name="routes_per_node").sort_values(
            ascending=False
        )
        return counts

    # As last resort, return empty
    return pd.Series(dtype=int)


def plot_node_types_distribution(nodes_df: pd.DataFrame) -> str:
    plt.figure(figsize=(8, 5))
    types_counts = nodes_df["node_type"].fillna("(non classé)").value_counts()
    types_counts.plot(kind="bar", color="#5B8FA8")
    plt.title("OSM Suisse — Répartition des types de nœuds de transport public")
    plt.xlabel("Type de nœud")
    plt.ylabel("Nombre de nœuds")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    out_path = os.path.join(PLOTS_DIR, "osm_node_types.png")
    plt.savefig(out_path, dpi=180)
    plt.close()
    return out_path


def plot_tag_presence(nodes_df: pd.DataFrame) -> str:
    tags_of_interest = [
        "uic_ref",
        "ref",
        "local_ref",
        "name",
        "network",
        "operator",
        "uic_name",
    ]

    counts = {
        tag: int(nodes_df[tag].notna().sum()) if tag in nodes_df.columns else 0
        for tag in tags_of_interest
    }
    plt.figure(figsize=(8, 5))
    plt.bar(list(counts.keys()), list(counts.values()), color="#8FB996")
    plt.title("OSM Suisse — Présence des balises clés sur les nœuds")
    plt.xlabel("Balise")
    plt.ylabel("Nombre de nœuds avec la balise")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    out_path = os.path.join(PLOTS_DIR, "osm_tag_presence.png")
    plt.savefig(out_path, dpi=180)
    plt.close()
    return out_path


def plot_routes_per_node_hist(counts: pd.Series) -> str:
    if counts.empty:
        return ""

    plt.figure(figsize=(8, 5))
    # Limit long tail for readability
    upper = int(counts.quantile(0.99)) if len(counts) > 0 else 50
    upper = max(upper, 10)
    clipped = counts.clip(upper=upper)
    plt.hist(clipped, bins=min(30, upper), color="#E6A57E", edgecolor="#333333")
    plt.title("OSM Suisse — Distribution du nombre d'itinéraires par nœud")
    plt.xlabel("Itinéraires par nœud (censuré au 99e centile)")
    plt.ylabel("Nombre de nœuds")
    plt.tight_layout()

    out_path = os.path.join(PLOTS_DIR, "osm_routes_per_node_hist.png")
    plt.savefig(out_path, dpi=180)
    plt.close()
    return out_path


def plot_top_nodes_by_routes(counts: pd.Series, nodes_df: pd.DataFrame, top_k: int = 20) -> str:
    if counts.empty:
        return ""

    top = counts.head(top_k)
    # Map node_id -> readable label (prefer name)
    id_to_name = (
        nodes_df.set_index("node_id")["name"].fillna("").to_dict()
        if "name" in nodes_df.columns
        else {}
    )
    labels = [f"{id_to_name.get(str(nid), '').strip() or str(nid)}" for nid in top.index]

    plt.figure(figsize=(9, 7))
    plt.barh(range(len(top)), list(top.values), color="#BFD7EA")
    plt.yticks(range(len(top)), labels)
    plt.gca().invert_yaxis()
    plt.title("OSM Suisse — Top nœuds par nombre d'itinéraires")
    plt.xlabel("Nombre d'itinéraires (distincts)")
    plt.tight_layout()

    out_path = os.path.join(PLOTS_DIR, "osm_top_nodes_by_routes.png")
    plt.savefig(out_path, dpi=180)
    plt.close()
    return out_path


def plot_direction_known_ratio(nodes_routes_df: Optional[pd.DataFrame]) -> str:
    if nodes_routes_df is None or nodes_routes_df.empty:
        return ""

    series = nodes_routes_df.get("direction_id")
    if series is None:
        return ""

    known = int(series.fillna("").astype(str).str.len().gt(0).sum())
    total = int(len(series))
    unknown = max(total - known, 0)

    plt.figure(figsize=(6, 4))
    plt.bar(["connexions avec direction", "connexions sans direction"], [known, unknown], color=["#6CAE75", "#D9534F"])
    plt.title("OSM Suisse — Direction GTFS (H/R) disponible ou non")
    plt.ylabel("Nombre de connexions nœud–itinéraire")
    plt.xticks(rotation=10, ha="right")
    plt.tight_layout()

    out_path = os.path.join(PLOTS_DIR, "osm_direction_known_ratio.png")
    plt.savefig(out_path, dpi=180)
    plt.close()
    return out_path


def main() -> None:
    ensure_directories()

    # Load or fetch OSM XML
    xml_text = load_or_fetch_xml()
    if not xml_text:
        print("No OSM XML available; aborting plot generation.")
        return

    # Ensure nodes-with-routes CSV exists and read it if possible
    nodes_routes_df = ensure_processed_csv(xml_text)

    # Parse nodes with tags
    nodes_df = parse_nodes_from_xml(xml_text)

    # Compute routes-per-node counts
    counts = compute_routes_per_node_counts(nodes_routes_df, xml_text)

    # Plot 1: node types distribution
    p1 = plot_node_types_distribution(nodes_df)
    print(f"Saved: {p1}")

    # Plot 2: tag presence counts
    p2 = plot_tag_presence(nodes_df)
    print(f"Saved: {p2}")

    # Plot 3: histogram of routes per node
    p3 = plot_routes_per_node_hist(counts)
    if p3:
        print(f"Saved: {p3}")
    else:
        print("Skipped routes-per-node histogram (no data)")

    # Plot 4: top nodes by routes
    p4 = plot_top_nodes_by_routes(counts, nodes_df, top_k=20)
    if p4:
        print(f"Saved: {p4}")
    else:
        print("Skipped top-nodes plot (no data)")

    # Plot 5: direction known vs unknown (from CSV only)
    p5 = plot_direction_known_ratio(nodes_routes_df)
    if p5:
        print(f"Saved: {p5}")
    else:
        print("Skipped direction-known plot (no data)")


if __name__ == "__main__":
    main()


