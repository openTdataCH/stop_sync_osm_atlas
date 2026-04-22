import csv
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from flask import current_app as app
from backend.extensions import db
from backend.models import OsmRoute
from sqlalchemy import text

from matching_and_import_db.utils.route_id import normalize_route_id


def _iter_candidate_paths(relative_path: str):
    rel = Path(relative_path)
    yield rel
    yield Path('/app') / rel
    # backend/services/transport_routes.py -> repo root is two parents up.
    yield Path(__file__).resolve().parents[2] / rel


def _resolve_existing_path(relative_path: str) -> Path | None:
    for candidate in _iter_candidate_paths(relative_path):
        if candidate.exists():
            return candidate
    return None


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def get_osm_route_metadata(route_id: str | None) -> dict[str, str | None]:
    """Return OSM route metadata for an internal OSM relation id."""
    if not route_id:
        return {
            'relation_id': None,
            'gtfs_route_id': None,
            'name': None,
            'ref': None,
        }

    try:
        row = (
            db.session.query(OsmRoute.gtfs_route_id, OsmRoute.name, OsmRoute.ref)
            .filter(OsmRoute.relation_id == route_id)
            .first()
        )
    except Exception as exc:
        app.logger.error(f"Error fetching OSM route metadata for {route_id}: {exc}")
        return {
            'relation_id': route_id,
            'gtfs_route_id': None,
            'name': None,
            'ref': None,
        }

    if row is None:
        return {
            'relation_id': route_id,
            'gtfs_route_id': None,
            'name': None,
            'ref': None,
        }

    return {
        'relation_id': route_id,
        'gtfs_route_id': _clean_text(row.gtfs_route_id),
        'name': _clean_text(row.name),
        'ref': _clean_text(row.ref),
    }


@lru_cache(maxsize=1)
def _atlas_route_name_map() -> dict[str, dict[str, str | None]]:
    path = _resolve_existing_path('data/processed/atlas_routes_gtfs.csv')
    if path is None:
        return {}

    mapping: dict[str, dict[str, str | None]] = {}
    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                route_id = _clean_text(row.get('route_id'))
                if not route_id:
                    continue

                short_name = _clean_text(row.get('route_name_short'))
                long_name = _clean_text(row.get('route_name_long'))
                existing = mapping.get(route_id)

                if existing is None:
                    mapping[route_id] = {
                        'route_name_short': short_name,
                        'route_name_long': long_name,
                    }
                    continue

                if not existing.get('route_name_short') and short_name:
                    existing['route_name_short'] = short_name
                if not existing.get('route_name_long') and long_name:
                    existing['route_name_long'] = long_name
    except Exception as exc:
        app.logger.error(f"Error loading ATLAS route names from {path}: {exc}")
        return {}

    return mapping


@lru_cache(maxsize=1)
def _osm_route_name_map() -> dict[str, str]:
    path = _resolve_existing_path('data/processed/osm_nodes_with_routes.csv')
    if path is None:
        return {}

    counters: dict[str, Counter] = defaultdict(Counter)
    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                route_id = _clean_text(row.get('gtfs_route_id'))
                route_name = _clean_text(row.get('route_name'))
                if route_id and route_name:
                    counters[route_id][route_name] += 1
    except Exception as exc:
        app.logger.error(f"Error loading OSM route names from {path}: {exc}")
        return {}

    mapping = {}
    for route_id, name_counter in counters.items():
        if not name_counter:
            continue
        mapping[route_id] = name_counter.most_common(1)[0][0]

    return mapping


def get_atlas_route_metadata(route_id: str | None) -> dict[str, str | None]:
    """Return ATLAS route metadata for a route id."""
    if not route_id:
        return {'route_name_short': None, 'route_name_long': None}
    return _atlas_route_name_map().get(
        route_id,
        {'route_name_short': None, 'route_name_long': None},
    )


def get_atlas_route_display_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    metadata = get_atlas_route_metadata(route_id)
    return metadata.get('route_name_short') or metadata.get('route_name_long') or route_id


def get_osm_route_display_id(route_id: str | None) -> str | None:
    if not route_id:
        return None
    return get_osm_route_metadata(route_id).get('gtfs_route_id')


def get_osm_route_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    metadata = get_osm_route_metadata(route_id)
    return metadata.get('name') or metadata.get('ref') or metadata.get('gtfs_route_id')


def get_osm_route_display_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    return get_osm_route_name(route_id)

def get_atlas_routes_for_sloid(sloid):
    """Return all ATLAS routes that contain this SLOID."""
    if not sloid:
        return []
    try:
        rows = db.session.execute(
            text("SELECT DISTINCT atlas_route_id, direction_id FROM route_atlas_stops WHERE sloid = :sloid"),
            {"sloid": sloid}
        ).fetchall()
        result = []
        for route_id, direction_id in rows:
            metadata = get_atlas_route_metadata(route_id)
            result.append(
                {
                    "route_id": route_id,
                    "direction_id": direction_id,
                    "route_name_short": metadata.get('route_name_short'),
                    "route_name_long": metadata.get('route_name_long'),
                }
            )
        return result
    except Exception as e:
        app.logger.error(f"Error fetching routes for sloid {sloid}: {e}")
        return []


def get_osm_routes_for_node(osm_node_id):
    """Return all OSM routes that contain this OSM node."""
    if not osm_node_id:
        return []
    try:
        rows = db.session.execute(
            text("SELECT DISTINCT osm_route_id, direction_id FROM route_osm_stops WHERE osm_node_id = :node_id"),
            {"node_id": str(osm_node_id)}
        ).fetchall()
        result = []
        for route_id, direction_id in rows:
            metadata = get_osm_route_metadata(route_id)
            result.append(
                {
                    "route_id": metadata.get('gtfs_route_id'),
                    "display_route_id": metadata.get('gtfs_route_id'),
                    "internal_route_id": route_id,
                    "direction_id": direction_id,
                    "route_name": metadata.get('name') or metadata.get('ref') or metadata.get('gtfs_route_id'),
                }
            )
        return result
    except Exception as e:
        app.logger.error(f"Error fetching routes for osm_node_id {osm_node_id}: {e}")
        return []


def get_stops_for_route(route_id, direction=None):
    try:
        # Exact route-id lookup first for correctness and index-friendly execution.
        atlas_query = """
            SELECT sloid FROM route_atlas_stops 
            WHERE atlas_route_id = :route_id
        """
        atlas_params = {"route_id": route_id}
        if direction:
            atlas_query += " AND direction_id = :direction"
            atlas_params["direction"] = direction
            
        atlas_rows = db.session.execute(text(atlas_query), atlas_params).fetchall()
        
        # OSM exact route-id lookup.
        osm_query = """
            SELECT osm_node_id FROM route_osm_stops 
            WHERE osm_route_id = :route_id
        """
        osm_params = {"route_id": route_id}
        if direction:
            osm_query += " AND direction_id = :direction"
            osm_params["direction"] = direction
            
        osm_rows = db.session.execute(text(osm_query), osm_params).fetchall()
        
        # Fallback to normalized route-id matching when suffix variants exist.
        if not atlas_rows and not osm_rows:
            app.logger.info(f"No exact matches for {route_id}, trying normalized matching")
            normalized_input = normalize_route_id(route_id)
            if normalized_input and normalized_input != route_id:
                atlas_query_norm = """
                    SELECT sloid FROM route_atlas_stops 
                    WHERE REGEXP_REPLACE(atlas_route_id, '-j[0-9]+', '-jXX') = :normalized_route_id
                """
                atlas_params_norm = {"normalized_route_id": normalized_input}
                if direction:
                    atlas_query_norm += " AND direction_id = :direction"
                    atlas_params_norm["direction"] = direction
                atlas_rows = db.session.execute(text(atlas_query_norm), atlas_params_norm).fetchall()
                
                osm_query_norm = """
                    SELECT osm_node_id FROM route_osm_stops 
                    WHERE REGEXP_REPLACE(osm_route_id, '-j[0-9]+', '-jXX') = :normalized_route_id
                """
                osm_params_norm = {"normalized_route_id": normalized_input}
                if direction:
                    osm_query_norm += " AND direction_id = :direction"
                    osm_params_norm["direction"] = direction
                osm_rows = db.session.execute(text(osm_query_norm), osm_params_norm).fetchall()

        osm_nodes = [row[0] for row in osm_rows]
        atlas_sloids = [row[0] for row in atlas_rows]

        app.logger.info(f"Found {len(osm_nodes)} OSM nodes and {len(atlas_sloids)} ATLAS sloids for route {route_id}" + 
                        (f" with direction {direction}" if direction else ""))
        return {
            'osm_nodes': list(set(osm_nodes)),
            'atlas_sloids': list(set(atlas_sloids))
        }
    except Exception as e:
        app.logger.error(f"Error retrieving stops for route {route_id}: {e}")
        return {'osm_nodes': [], 'atlas_sloids': []}


