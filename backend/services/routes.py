import json
from flask import current_app as app
from backend.extensions import db
from sqlalchemy import text


def _normalize_route_id_for_matching(route_id):
    if not route_id:
        return None
    import re
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def get_stops_for_route(route_id, direction=None):
    try:
        sql_query = """
            SELECT 
                osm_nodes_json, 
                atlas_sloids_json 
            FROM 
                routes_and_directions 
            WHERE 
                (osm_route_id LIKE :route_id 
                OR atlas_route_id LIKE :route_id)
        """
        params = {"route_id": f'%{route_id}%'}
        if direction:
            sql_query += " AND direction_id = :direction"
            params["direction"] = direction

        app.logger.info(f"Executing exact query for route {route_id} with direction {direction if direction else 'None'}")
        route_entries = db.session.execute(text(sql_query), params).fetchall()

        if not route_entries:
            app.logger.info(f"No exact matches for {route_id}, trying normalized matching")
            normalized_input = _normalize_route_id_for_matching(route_id)
            if normalized_input and normalized_input != route_id:
                sql_query_normalized = """
                    SELECT 
                        osm_nodes_json, 
                        atlas_sloids_json,
                        osm_route_id,
                        atlas_route_id
                    FROM 
                        routes_and_directions 
                    WHERE 
                        (REGEXP_REPLACE(osm_route_id, '-j[0-9]+', '-jXX') LIKE :normalized_route_id
                        OR REGEXP_REPLACE(atlas_route_id, '-j[0-9]+', '-jXX') LIKE :normalized_route_id)
                """
                params_normalized = {"normalized_route_id": f'%{normalized_input}%'}
                if direction:
                    sql_query_normalized += " AND direction_id = :direction"
                    params_normalized["direction"] = direction

                app.logger.info(f"Executing normalized query for route {normalized_input}")
                route_entries = db.session.execute(text(sql_query_normalized), params_normalized).fetchall()

        osm_nodes = []
        atlas_sloids = []
        for entry in route_entries:
            osm_nodes_json = entry[0]
            atlas_sloids_json = entry[1]
            if osm_nodes_json:
                try:
                    osm_nodes_list = json.loads(osm_nodes_json) if isinstance(osm_nodes_json, str) else osm_nodes_json
                    if isinstance(osm_nodes_list, list):
                        osm_nodes.extend(osm_nodes_list)
                except Exception as e:
                    app.logger.error(f"Error parsing OSM nodes JSON: {e}")
            if atlas_sloids_json:
                try:
                    atlas_sloids_list = json.loads(atlas_sloids_json) if isinstance(atlas_sloids_json, str) else atlas_sloids_json
                    if isinstance(atlas_sloids_list, list):
                        atlas_sloids.extend(atlas_sloids_list)
                except Exception as e:
                    app.logger.error(f"Error parsing ATLAS sloids JSON: {e}")

        app.logger.info(f"Found {len(osm_nodes)} OSM nodes and {len(atlas_sloids)} ATLAS sloids for route {route_id}" + 
                        (f" with direction {direction}" if direction else ""))
        return {
            'osm_nodes': list(set(osm_nodes)),
            'atlas_sloids': list(set(atlas_sloids))
        }
    except Exception as e:
        app.logger.error(f"Error retrieving stops for route {route_id}: {e}")
        return {'osm_nodes': [], 'atlas_sloids': []}


