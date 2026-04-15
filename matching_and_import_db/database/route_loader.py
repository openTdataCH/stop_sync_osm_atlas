"""
Route data loaders for the database import pipeline.

Loads and builds all route mappings (GTFS routes, OSM routes,
GTFS direction groupings) needed by ``import_to_database``.
"""
import os

import pandas as pd

from matching_and_import_db.utils.route_id import normalize_route_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_direction_id(val):
    """Convert direction_id to a clean string ('0' or '1'), or None."""
    try:
        if pd.isna(val):
            return None
        return str(int(float(val)))
    except (ValueError, TypeError):
        return None


def _nan_to_none(val):
    """Convert pandas NaN/NaT to None."""
    if pd.isna(val):
        return None
    return val


# ---------------------------------------------------------------------------
# GTFS ATLAS routes
# ---------------------------------------------------------------------------

def _load_gtfs_routes_df():
    """Read atlas_routes_gtfs.csv once and return the DataFrame (or empty)."""
    gtfs_path = "data/processed/atlas_routes_gtfs.csv"
    try:
        return pd.read_csv(gtfs_path, low_memory=False, dtype=str)
    except FileNotFoundError:
        print("INFO: GTFS routes file (atlas_routes_gtfs.csv) not found.")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error loading GTFS routes: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# OSM routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GTFS helpers
# ---------------------------------------------------------------------------

def _build_route_name_to_id(gtfs_df: pd.DataFrame) -> dict:
    """Build fallback mapping from route names to route_id using GTFS route data."""
    if gtfs_df is None or gtfs_df.empty:
        return {}
    
    mapping = {}
    try:
        df = gtfs_df.copy()
        
        for col in ('route_name_short', 'route_name_long'):
            if col in df.columns:
                mask = df[col].notna() & df['route_id'].notna()
                for name, rid in zip(df.loc[mask, col].astype(str).str.strip(), df.loc[mask, 'route_id'].astype(str).str.strip()):
                    if name:
                        mapping[name] = rid
                        
        return mapping
    except Exception as e:
        print(f"Warning: Failed to build route name mapping from GTFS data: {e}")
        return {}


def _build_osm_route_dir_to_nodes(osm_routes_df: pd.DataFrame, route_name_to_id: dict) -> dict:
    """Build (route_id, direction_id) -> {nodes, route_name} from OSM routes (vectorized)."""
    if osm_routes_df is None or osm_routes_df.empty:
        return {}
    df = osm_routes_df.copy()
    df = df[df['node_id'].notna() & (df['gtfs_route_id'].notna() | df['route_name'].notna())].copy()
    # Resolve route_id with fallback
    df['resolved_route_id'] = df['gtfs_route_id'].where(
        df['gtfs_route_id'].notna() & (df['gtfs_route_id'].astype(str).str.strip() != ''),
        df['route_name'].map(route_name_to_id)
    )
    df = df[df['resolved_route_id'].notna()].copy()
    df['resolved_route_id'] = df['resolved_route_id'].astype(str).str.strip()
    df['dir_clean'] = df['direction_id'].apply(_safe_direction_id)
    # Keep missing directions as unspecified instead of cloning to both directions,
    # which creates synthetic mirrored route stop lists in the UI.
    df['dir_clean'] = df['dir_clean'].fillna('')
    all_rows = df[['node_id', 'resolved_route_id', 'dir_clean', 'route_name']].copy()
    if all_rows.empty:
        return {}

    result = {}
    for (route_id, direction_id), grp in all_rows.groupby(['resolved_route_id', 'dir_clean'], sort=False):
        result[(route_id, direction_id)] = {
            'nodes': grp['node_id'].astype(str).tolist(),
            'route_name': _nan_to_none(grp['route_name'].iloc[0]) if grp['route_name'].notna().any() else None,
        }
    return result


# ---------------------------------------------------------------------------
# ATLAS direction groupings
# ---------------------------------------------------------------------------

def _build_atlas_route_dir_mappings(gtfs_df: pd.DataFrame):
    """Build GTFS route-direction groupings from GTFS DataFrame.

    Returns atlas_route_dir_to_sloids.
    """
    atlas_route_dir_to_sloids = {}
    if gtfs_df.empty:
        return atlas_route_dir_to_sloids

    df = gtfs_df.dropna(subset=['sloid']).copy()
    if df.empty:
        return atlas_route_dir_to_sloids
    df['direction_id_clean'] = df['direction_id'].apply(_safe_direction_id)

    gtfs = df[df['route_id'].notna() & df['direction_id_clean'].notna()]
    for (route_id, direction_id), grp in gtfs.groupby(['route_id', 'direction_id_clean'], sort=False):
        first = grp.iloc[0]
        atlas_route_dir_to_sloids[(str(route_id), str(direction_id))] = {
            'sloids': grp['sloid'].astype(str).tolist(),
            'route_short_name': _nan_to_none(first.get('route_name_short')),
            'route_long_name': _nan_to_none(first.get('route_name_long')),
            'route_id_normalized': _nan_to_none(first.get('route_id_normalized')),
        }

    return atlas_route_dir_to_sloids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all_route_data(osm_routes_df: pd.DataFrame = None):
    """Load all route data in a single pass over each CSV.

    Returns a dict with all route mappings needed for the import:
      - osm_route_dir_to_nodes: (route_id, dir) -> {nodes, route_name}
      - atlas_route_dir_to_sloids: (route_id, dir) -> {sloids, ...}
    """
    # 1. Read atlas_routes_gtfs.csv ONCE
    gtfs_df = _load_gtfs_routes_df()
    atlas_route_dir_to_sloids = _build_atlas_route_dir_mappings(gtfs_df)
    print(f"Built GTFS route+direction to sloids mapping for {len(atlas_route_dir_to_sloids)} ATLAS routes")

    # 2. Read osm_nodes_with_routes.csv ONCE
    if osm_routes_df is None:
        try:
            osm_routes_df = pd.read_csv("data/processed/osm_nodes_with_routes.csv")
        except Exception:
            osm_routes_df = pd.DataFrame()

    route_name_to_id = _build_route_name_to_id(gtfs_df)
    osm_route_dir_to_nodes = _build_osm_route_dir_to_nodes(osm_routes_df, route_name_to_id)
    print(f"Built route+direction to nodes mapping for {len(osm_route_dir_to_nodes)} OSM routes")

    return {
        'osm_route_dir_to_nodes': osm_route_dir_to_nodes,
        'atlas_route_dir_to_sloids': atlas_route_dir_to_sloids,
    }


def build_route_write_payload(all_route_data: dict, known_sloids: set[str]) -> dict:
    """Prepare route table rows for later bulk DB insert.

    This is intentionally DB-free so it can run in a non-blocking scheduler
    phase before the maintenance window starts.
    """
    atlas_route_dir_to_sloids = all_route_data.get('atlas_route_dir_to_sloids', {})
    osm_route_dir_to_nodes = all_route_data.get('osm_route_dir_to_nodes', {})

    atlas_normalized_to_original = {}
    for (atlas_route_id, atlas_direction_id), atlas_info in atlas_route_dir_to_sloids.items():
        norm_id = normalize_route_id(atlas_route_id)
        if norm_id:
            atlas_normalized_to_original.setdefault((norm_id, atlas_direction_id), []).append(
                (atlas_route_id, atlas_info)
            )

    route_osm_rows: list[tuple[str, str, str, int]] = []
    route_atlas_rows: list[tuple[str, str, str, int]] = []
    routes_matched_rows: list[tuple[str, str, str]] = []

    seen_route_matches = set()
    matched_routes = 0

    for (osm_route_id, direction_id), osm_data in osm_route_dir_to_nodes.items():
        for i, node_id in enumerate(osm_data.get('nodes', [])):
            route_osm_rows.append((str(osm_route_id), str(direction_id), str(node_id), i))

        atlas_data = atlas_route_dir_to_sloids.get((osm_route_id, direction_id))
        atlas_matched_route_id = None

        if atlas_data:
            atlas_matched_route_id = osm_route_id
        else:
            osm_route_normalized = normalize_route_id(osm_route_id)
            if osm_route_normalized:
                matches = atlas_normalized_to_original.get((osm_route_normalized, direction_id))
                if matches:
                    atlas_matched_route_id, atlas_data = matches[0]

        if atlas_matched_route_id and (atlas_matched_route_id, osm_route_id) not in seen_route_matches:
            seen_route_matches.add((atlas_matched_route_id, osm_route_id))
            routes_matched_rows.append((str(atlas_matched_route_id), str(osm_route_id), 'matched'))
            matched_routes += 1

    skipped_sloids = 0
    for (atlas_route_id, direction_id), atlas_data in atlas_route_dir_to_sloids.items():
        for i, sloid in enumerate(atlas_data.get('sloids', [])):
            sloid_str = str(sloid)
            if sloid_str not in known_sloids:
                skipped_sloids += 1
                continue
            route_atlas_rows.append((str(atlas_route_id), str(direction_id), sloid_str, i))

    return {
        'route_osm_rows': route_osm_rows,
        'route_atlas_rows': route_atlas_rows,
        'routes_matched_rows': routes_matched_rows,
        'matched_routes': matched_routes,
        'skipped_sloids': skipped_sloids,
    }
