# matching_process/matching_script.py
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
from matching_process.pipeline import MatchingContext, run_pipeline
from matching_process.state import AtlasState, OsmIndex

# Predicates
from matching_process.exact_matching import exact_uic
from matching_process.name_matching import name_match
from matching_process.distance_matching import (
    group_proximity, local_ref_distance, nearest_distance,
)
from matching_process.route_matching_unified import route_match
from matching_process.postpass_matching import (
    postpass_unique_uic, duplicate_propagation, manual_match,
)

# Utilities
from matching_process.org_standardization import standardize_operator

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
# OSM XML parser (builds the three indexes all predicates share)
# ---------------------------------------------------------------------------

def parse_osm_xml(xml_file):
    """
    Parse OSM XML → (all_nodes, uic_ref_dict, name_index, name_dirs, uic_dirs).

    * all_nodes:    {(lat, lon): node_entry}
    * uic_ref_dict: {uic_ref_str: [node_entry, …]}
    * name_index:   {name_str: [node_entry, …]}
    * name_dirs:    {node_id: set of "FirstName → LastName" direction strings}
    * uic_dirs:     {node_id: set of "FirstUIC → LastUIC" direction strings}
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()

    all_nodes: dict[tuple, dict] = {}
    uic_ref_dict: dict[str, list] = defaultdict(list)
    name_index: dict[str, list] = defaultdict(list)

    # Also collect per-node name/UIC for direction extraction from relations
    node_id_to_name: dict[str, str] = {}
    node_id_to_uic: dict[str, str] = {}

    for node in root.iter("node"):
        node_id = node.get("id")
        try:
            lat = float(node.get("lat"))
            lon = float(node.get("lon"))
        except (ValueError, TypeError):
            continue

        local_ref = None
        tags: dict[str, str] = {}

        for tag in node.findall("tag"):
            k, v = tag.get("k"), tag.get("v")
            if k == "operator":
                original = v
                v, changed = standardize_operator(v)
                if changed:
                    tags['original_operator'] = original
            tags[k] = v
            if k == "local_ref":
                local_ref = v
            elif k == "ref" and not local_ref:
                local_ref = v

        entry = {
            'node_id': node_id,
            'lat': lat,
            'lon': lon,
            'local_ref': local_ref,
            'tags': tags,
        }
        all_nodes[(lat, lon)] = entry

        if "uic_ref" in tags:
            uic_ref_dict[tags["uic_ref"]].append(entry)
            node_id_to_uic[node_id] = tags["uic_ref"]

        if "name" in tags:
            node_id_to_name[node_id] = tags["name"]

        for key in ('name', 'uic_name', 'gtfs:name'):
            if key in tags:
                name_index[tags[key]].append(entry)

    # Extract per-node direction strings from route relations (single pass)
    name_dirs: dict[str, set] = defaultdict(set)
    uic_dirs: dict[str, set] = defaultdict(set)

    # Use sidecar CSV for directions instead of re-parsing relations from the XML
    dir_csv_path = "data/processed/osm_directions.csv"
    loaded_from_csv = False
    
    if os.path.exists(dir_csv_path):
        try:
            df = pd.read_csv(dir_csv_path, dtype=str)
            df = df.where(pd.notna(df), None)
            for r in df.to_dict(orient='records'):
                nid = str(r.get('node_id'))
                ds = str(r.get('direction_string'))
                dtype = str(r.get('dir_type'))
                if not ds or ds == 'None' or not nid or nid == 'None': continue
                if dtype == 'name':
                    name_dirs[nid].add(ds)
                elif dtype == 'uic':
                    uic_dirs[nid].add(ds)
            loaded_from_csv = True
        except Exception as e:
            logger.warning(f"Error reading {dir_csv_path}: {e}")
            
    if not loaded_from_csv:
        for relation in root.iter("relation"):
            is_route = any(
                t.get('k') == 'type' and t.get('v') == 'route'
                for t in relation.findall('./tag')
            )
            if not is_route:
                continue
            members = [m.get('ref') for m in relation.findall("./member[@type='node']")]
            if len(members) < 2:
                continue
            first, last = members[0], members[-1]
            fn = node_id_to_name.get(first)
            ln = node_id_to_name.get(last)
            if fn and ln:
                ds = f"{fn} → {ln}"
                for nid in members:
                    name_dirs[nid].add(ds)
            fu = node_id_to_uic.get(first)
            lu = node_id_to_uic.get(last)
            if fu and lu:
                ds = f"{fu} → {lu}"
                for nid in members:
                    uic_dirs[nid].add(ds)

    logger.info(
        f"Parsed OSM XML: {len(all_nodes)} nodes, "
        f"{len(uic_ref_dict)} uic_ref entries, "
        f"{len(name_dirs)} nodes with direction strings"
    )
    return all_nodes, uic_ref_dict, name_index, dict(name_dirs), dict(uic_dirs)


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


def _auto_download_atlas(path):
    try:
        from Download_and_process_data.get_atlas_data import get_atlas_stops
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        url = os.getenv('ATLAS_DOWNLOAD_URL',
                        "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink")
        logger.info("ATLAS CSV missing – auto-downloading…")
        get_atlas_stops(path, url)
    except Exception as e:
        logger.warning(f"Automatic ATLAS download failed: {e}")


def _auto_download_osm(path):
    try:
        from Download_and_process_data.get_osm_data import query_overpass
        logger.info("OSM XML missing – querying Overpass…")
        xml_text = query_overpass()
        if xml_text:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(xml_text)
    except Exception as e:
        logger.warning(f"Automatic OSM download failed: {e}")


def _locate_file(env_key, default, label):
    """Locate a required data file, optionally waiting / downloading."""
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
    if not path and os.getenv('DOWNLOAD_IF_MISSING', '1').lower() in ('1', 'true', 'yes'):
        if label == 'ATLAS':
            _auto_download_atlas(pref)
        else:
            _auto_download_osm(pref)
        path = _resolve_path(pref, alternates)
    if not path:
        raise FileNotFoundError(
            f"Required {label} file not found. "
            f"Tried: {[pref] + [a for a in alternates if a]}"
        )
    return path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def final_pipeline(route_matching_strategy='unified'):
    """
    Execute the complete matching pipeline and return data for DB import.

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
        all_osm_nodes, uic_ref_dict, name_index, osm_name_dirs, osm_uic_dirs = parse_osm_xml(osm_xml_file)

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

    osm_index = OsmIndex(
        xml_nodes=all_osm_nodes,
        uic_ref_dict=uic_ref_dict,
        name_index=name_index,
        name_dirs=osm_name_dirs,
        uic_dirs=osm_uic_dirs,
    )

    with timed_phase("Context initialization"):
        ctx = MatchingContext(
            atlas=atlas_state,
            osm=osm_index,
            max_distance=50.0,
            osm_xml_file=osm_xml_file,
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
