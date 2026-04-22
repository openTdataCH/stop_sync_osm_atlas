"""
Route data loaders for the database import pipeline.

Loads and builds all route mappings (GTFS routes, OSM routes,
GTFS direction groupings) needed by ``import_to_database``.
"""
import pandas as pd
from typing import Dict, Any


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == '' or text.lower() == 'nan'


def _to_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value).strip()


def _to_int(value: Any, default: int = 0) -> int:
    if _is_missing(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def load_all_route_data(osm_routes_df: pd.DataFrame = None) -> Dict[str, pd.DataFrame]:
    """Load the entity-first route CSVs."""
    data = {}
    try:
        data['atlas_routes'] = pd.read_csv("data/processed/atlas_routes.csv", dtype=str)
        data['atlas_route_directions'] = pd.read_csv("data/processed/atlas_route_directions.csv", dtype=str)
        data['atlas_route_stops'] = pd.read_csv("data/processed/atlas_route_stops.csv", dtype=str)
    except Exception as e:
        print(f"Warning: Failed to load ATLAS route data: {e}")
        
    try:
        data['osm_routes'] = pd.read_csv("data/processed/osm_routes.csv", dtype=str)
        data['osm_route_tags'] = pd.read_csv("data/processed/osm_route_tags.csv", dtype=str)
        data['osm_route_members'] = pd.read_csv("data/processed/osm_route_members.csv", dtype=str)
    except Exception as e:
        print(f"Warning: Failed to load OSM route data: {e}")
        
    return data

def build_route_write_payload(all_route_data: Dict[str, pd.DataFrame], known_sloids: set[str]) -> Dict[str, Any]:
    """Prepare entity-first route table rows for DB insertion."""
    
    # 1. Atlas Routes
    atlas_routes_df = all_route_data.get('atlas_routes')
    atlas_route_rows = []
    if atlas_routes_df is not None and not atlas_routes_df.empty:
        for r in atlas_routes_df.to_dict(orient='records'):
            route_id = _to_text(r.get('route_id'))
            if not route_id:
                continue
            atlas_route_rows.append({
                'route_id': route_id,
                'route_id_normalized': _to_text(r.get('route_id_normalized')),
                'agency_id': _to_text(r.get('agency_id')),
                'route_short_name': _to_text(r.get('route_short_name')),
                'route_long_name': _to_text(r.get('route_long_name')),
                'route_desc': _to_text(r.get('route_desc')),
                'route_type': _to_text(r.get('route_type'))
            })
            
    # 2. Atlas Route Directions
    atlas_dirs_df = all_route_data.get('atlas_route_directions')
    atlas_dir_rows = []
    if atlas_dirs_df is not None and not atlas_dirs_df.empty:
        for r in atlas_dirs_df.to_dict(orient='records'):
            route_id = _to_text(r.get('route_id'))
            if not route_id:
                continue
            atlas_dir_rows.append({
                'route_id': route_id,
                'direction_id': _to_text(r.get('direction_id')),
                'direction_label': _to_text(r.get('direction_label')),
                'representative_headsign': _to_text(r.get('representative_headsign'))
            })

    # 3. Atlas Route Stops
    atlas_stops_df = all_route_data.get('atlas_route_stops')
    atlas_stop_rows = []
    skipped_sloids = 0
    if atlas_stops_df is not None and not atlas_stops_df.empty:
        for r in atlas_stops_df.to_dict(orient='records'):
            sloid = _to_text(r.get('sloid'))
            if sloid not in known_sloids:
                skipped_sloids += 1
                continue
            atlas_route_id = _to_text(r.get('route_id'))
            if not atlas_route_id:
                continue
            atlas_stop_rows.append({
                'atlas_route_id': atlas_route_id,
                'direction_id': _to_text(r.get('direction_id')),
                'sloid': sloid,
                'stop_sequence': _to_int(r.get('stop_sequence', 0))
            })

    # 4. OSM Routes
    osm_routes_df = all_route_data.get('osm_routes')
    osm_route_rows = []
    if osm_routes_df is not None and not osm_routes_df.empty:
        for r in osm_routes_df.to_dict(orient='records'):
            relation_id = _to_text(r.get('relation_id'))
            if not relation_id:
                continue
            osm_route_rows.append({
                'relation_id': relation_id,
                'route': _to_text(r.get('route')),
                'name': _to_text(r.get('name')),
                'ref': _to_text(r.get('ref')),
                'operator': _to_text(r.get('operator')),
                'network': _to_text(r.get('network')),
                'gtfs_route_id': _to_text(r.get('gtfs_route_id'))
            })

    # 5. OSM Route Tags
    osm_tags_df = all_route_data.get('osm_route_tags')
    osm_tag_rows = []
    if osm_tags_df is not None and not osm_tags_df.empty:
        for r in osm_tags_df.to_dict(orient='records'):
            relation_id = _to_text(r.get('relation_id'))
            if not relation_id:
                continue
            osm_tag_rows.append({
                'relation_id': relation_id,
                'tag_key': _to_text(r.get('tag_key')),
                'tag_value': _to_text(r.get('tag_value'))
            })

    # 6. OSM Route Stops (members)
    osm_members_df = all_route_data.get('osm_route_members')
    osm_stop_rows = []
    if osm_members_df is not None and not osm_members_df.empty:
        for r in osm_members_df.to_dict(orient='records'):
            osm_route_id = _to_text(r.get('relation_id'))
            osm_node_id = _to_text(r.get('resolved_node_id'))
            if not osm_route_id or not osm_node_id:
                continue
            osm_stop_rows.append({
                'osm_route_id': osm_route_id,
                'direction_id': _to_text(r.get('direction_id_derived')),
                'osm_node_id': osm_node_id,
                'stop_sequence': _to_int(r.get('member_sequence', 0))
            })

    # 7. Precompute Matchings using RouteState
    routes_matched_rows = []
    matched_routes = 0
    from matching_and_import_db.route_state import RouteState
    route_state = RouteState.get_instance()
    route_state.load_and_match()
    
    for osm_rel_id, atlas_id in route_state.osm_route_to_atlas_route.items():
        routes_matched_rows.append({
            'atlas_route_id': atlas_id,
            'osm_route_id': osm_rel_id,
            'match_type': 'matched',
            'match_confidence': 1.0,
            'match_reason': 'RouteState equivalency'
        })
        matched_routes += 1

    from matching_and_import_db.database.route_problems import detect_route_problems
    route_problems = detect_route_problems(atlas_route_rows, osm_route_rows, routes_matched_rows)

    return {
        'atlas_routes': atlas_route_rows,
        'atlas_route_directions': atlas_dir_rows,
        'route_atlas_stops': atlas_stop_rows,
        'osm_routes': osm_route_rows,
        'osm_route_tags': osm_tag_rows,
        'route_osm_stops': osm_stop_rows,
        'routes_matched': routes_matched_rows,
        'route_problems': route_problems,
        'matched_routes': matched_routes,
        'skipped_sloids': skipped_sloids,
    }
