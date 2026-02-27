import json
from flask import current_app as app
from backend.extensions import db
from sqlalchemy import text

from matching_and_import_db.utils.route_id import normalize_route_id

def get_stops_for_route(route_id, direction=None):
    try:
        # Atlas queries
        atlas_query = """
            SELECT sloid FROM route_atlas_stops 
            WHERE atlas_route_id LIKE :route_id
        """
        atlas_params = {"route_id": f'%{route_id}%'}
        if direction:
            atlas_query += " AND direction_id = :direction"
            atlas_params["direction"] = direction
            
        atlas_rows = db.session.execute(text(atlas_query), atlas_params).fetchall()
        
        # OSM queries
        osm_query = """
            SELECT osm_node_id FROM route_osm_stops 
            WHERE osm_route_id LIKE :route_id
        """
        osm_params = {"route_id": f'%{route_id}%'}
        if direction:
            osm_query += " AND direction_id = :direction"
            osm_params["direction"] = direction
            
        osm_rows = db.session.execute(text(osm_query), osm_params).fetchall()
        
        # Fallback to normalized route id if no exact matches found
        if not atlas_rows and not osm_rows:
            app.logger.info(f"No exact matches for {route_id}, trying normalized matching")
            normalized_input = normalize_route_id(route_id)
            if normalized_input and normalized_input != route_id:
                atlas_query_norm = """
                    SELECT sloid FROM route_atlas_stops 
                    WHERE REGEXP_REPLACE(atlas_route_id, '-j[0-9]+', '-jXX') LIKE :normalized_route_id
                """
                atlas_params_norm = {"normalized_route_id": f'%{normalized_input}%'}
                if direction:
                    atlas_query_norm += " AND direction_id = :direction"
                    atlas_params_norm["direction"] = direction
                atlas_rows = db.session.execute(text(atlas_query_norm), atlas_params_norm).fetchall()
                
                osm_query_norm = """
                    SELECT osm_node_id FROM route_osm_stops 
                    WHERE REGEXP_REPLACE(osm_route_id, '-j[0-9]+', '-jXX') LIKE :normalized_route_id
                """
                osm_params_norm = {"normalized_route_id": f'%{normalized_input}%'}
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


