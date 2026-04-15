from flask import current_app as app
from backend.extensions import db
from sqlalchemy import text

from matching_and_import_db.utils.route_id import normalize_route_id

def get_atlas_routes_for_sloid(sloid):
    """Return all ATLAS routes that contain this SLOID."""
    if not sloid:
        return []
    try:
        rows = db.session.execute(
            text("SELECT DISTINCT atlas_route_id, direction_id FROM route_atlas_stops WHERE sloid = :sloid"),
            {"sloid": sloid}
        ).fetchall()
        return [{"route_id": r[0], "direction_id": r[1]} for r in rows]
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
        return [{"route_id": r[0], "direction_id": r[1]} for r in rows]
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


