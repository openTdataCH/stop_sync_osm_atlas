from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode
import json

# Create blueprint for data operations
data_bp = Blueprint('data', __name__)

# Helper function to format stop data for API response (optimized)
def format_stop_data(stop, problem_type=None, include_routes=True, include_notes=True):
    """
    Format stop data for API response with optional fields for performance.
    
    Args:
        stop: Stop object
        problem_type: Optional problem type to include
        include_routes: Whether to include route information (can be expensive)
        include_notes: Whether to include note information
    
    Returns:
        Dictionary with formatted stop data
    """
    # Cache relationship access to avoid multiple property lookups
    atlas_details = stop.atlas_stop_details
    osm_details = stop.osm_node_details
    
    result = {
        "id": stop.id,
        "sloid": stop.sloid,
        "stop_type": stop.stop_type,
        "match_type": stop.match_type,
        "atlas_lat": stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat,
        "atlas_lon": stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon,
        "atlas_business_org_abbr": atlas_details.atlas_business_org_abbr if atlas_details else None,
        "atlas_operator": atlas_details.atlas_business_org_abbr if atlas_details else None,  # Alias for consistency
        "atlas_name": atlas_details.atlas_designation if atlas_details else None,
        "atlas_local_ref": None,  # Not available in current schema
        "atlas_transport_type": stop.osm_node_type,  # Best approximation
        "osm_lat": stop.osm_lat,
        "osm_lon": stop.osm_lon,
        "osm_network": osm_details.osm_network if osm_details else None,
        "osm_operator": osm_details.osm_operator if osm_details else None,
        "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
        "osm_railway": osm_details.osm_railway if osm_details else None,
        "osm_amenity": osm_details.osm_amenity if osm_details else None,
        "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
        "distance_m": stop.distance_m,
        "atlas_designation": atlas_details.atlas_designation if atlas_details else None,
        "atlas_designation_official": atlas_details.atlas_designation_official if atlas_details else None,
        "uic_ref": stop.uic_ref,
        "osm_node_id": stop.osm_node_id,
        "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
        "osm_name": osm_details.osm_name if osm_details else None,
        "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
        "atlas_duplicate_sloid": stop.atlas_duplicate_sloid,
        "osm_node_type": stop.osm_node_type,
    }
    
    # Conditionally include expensive fields
    if include_routes:
        result.update({
            "routes_atlas": atlas_details.routes_atlas if atlas_details else None,
            "routes_hrdf": atlas_details.routes_hrdf if atlas_details else None,
            "routes_osm": osm_details.routes_osm if osm_details else None,
        })
    
    if include_notes:
        result.update({
            "atlas_note": atlas_details.atlas_note if atlas_details else None,
            "osm_note": osm_details.osm_note if osm_details else None,
            "atlas_note_is_persistent": atlas_details.atlas_note_is_persistent if atlas_details else False,
            "osm_note_is_persistent": osm_details.osm_note_is_persistent if osm_details else False
        })
    
    # Add problem type if provided
    if problem_type:
        result["problem"] = problem_type
        
    return result

# Helper function to normalize route IDs for matching
def _normalize_route_id_for_matching(route_id):
    """Remove year codes (j24, j25, etc.) from route IDs for fuzzy matching."""
    if not route_id:
        return None
    import re
    # Replace j24, j25, j22, etc. with a generic jXX for comparison
    normalized = re.sub(r'-j\d+', '-jXX', str(route_id))
    return normalized

# New route query functionality with year code normalization
def get_stops_for_route(route_id, direction=None):
    """
    Gets all stops (both OSM and ATLAS) that belong to a route.
    Now includes year code normalization to handle j24/j25 mismatches.
    
    Args:
        route_id: The route ID to filter by
        direction: Optional direction ID to filter by
    
    Returns:
        A list of stop IDs (both ATLAS and OSM)
    """
    try:
        # First try exact matching
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
        
        # Add direction filter if provided
        if direction:
            sql_query += " AND direction_id = :direction"
            params["direction"] = direction
        
        app.logger.info(f"Executing exact query for route {route_id} with direction {direction if direction else 'None'}")
        
        # Execute the exact query
        route_entries = db.session.execute(db.text(sql_query), params).fetchall()
        
        # If no exact matches found, try normalized matching
        if not route_entries:
            app.logger.info(f"No exact matches for {route_id}, trying normalized matching")
            
            # Normalize the input route ID
            normalized_input = _normalize_route_id_for_matching(route_id)
            if normalized_input and normalized_input != route_id:
                # Build a more complex query that normalizes route IDs using REGEXP_REPLACE
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
                route_entries = db.session.execute(db.text(sql_query_normalized), params_normalized).fetchall()
                
                if route_entries:
                    app.logger.info(f"Found {len(route_entries)} normalized matches for {route_id}")
        
        # Extract all OSM nodes and ATLAS sloids
        osm_nodes = []
        atlas_sloids = []
        
        for entry in route_entries:
            # Handle both 2-column and 4-column results
            osm_nodes_json = entry[0]  # First column
            atlas_sloids_json = entry[1]  # Second column
            
            # Extract OSM nodes
            if osm_nodes_json:
                try:
                    # Handle string or JSON object
                    if isinstance(osm_nodes_json, str):
                        osm_nodes_list = json.loads(osm_nodes_json)
                    else:
                        osm_nodes_list = osm_nodes_json
                    
                    if isinstance(osm_nodes_list, list):
                        osm_nodes.extend(osm_nodes_list)
                    else:
                        app.logger.warning(f"Expected list of OSM nodes but got: {type(osm_nodes_list)}")
                except Exception as e:
                    app.logger.error(f"Error parsing OSM nodes JSON: {e}")
            
            # Extract ATLAS sloids
            if atlas_sloids_json:
                try:
                    # Handle string or JSON object
                    if isinstance(atlas_sloids_json, str):
                        atlas_sloids_list = json.loads(atlas_sloids_json)
                    else:
                        atlas_sloids_list = atlas_sloids_json
                    
                    if isinstance(atlas_sloids_list, list):
                        atlas_sloids.extend(atlas_sloids_list)
                    else:
                        app.logger.warning(f"Expected list of ATLAS sloids but got: {type(atlas_sloids_list)}")
                except Exception as e:
                    app.logger.error(f"Error parsing ATLAS sloids JSON: {e}")
        
        # Log what we found for debugging
        app.logger.info(f"Found {len(osm_nodes)} OSM nodes and {len(atlas_sloids)} ATLAS sloids for route {route_id}" + 
                      (f" with direction {direction}" if direction else ""))
        
        return {
            'osm_nodes': list(set(osm_nodes)),  # Remove duplicates
            'atlas_sloids': list(set(atlas_sloids))  # Remove duplicates
        }
    except Exception as e:
        app.logger.error(f"Error retrieving stops for route {route_id}: {e}")
        return {'osm_nodes': [], 'atlas_sloids': []}

# Helper function to check if a match method matches a route matching pattern
def _is_route_matching_method(method, target_pattern):
    """
    Check if a match method corresponds to a route matching pattern.
    Handles complex match_type values like 'route_matching_1_exact_91-15-E-j25-1_0'
    """
    if not method:
        return False
    
    # Convert both to string for comparison
    method_str = str(method)
    target_str = str(target_pattern)
    
    # Handle the target pattern (e.g., 'route_matching_1_')
    if target_str.endswith('_'):
        # Remove trailing underscore for pattern matching
        pattern_base = target_str.rstrip('_')
        # Check if the method starts with the pattern
        return method_str.startswith(pattern_base + '_')
    else:
        # Exact match
        return method_str == target_str

# ----------------------------
# API Endpoint: /api/operators
# ----------------------------
@data_bp.route('/api/operators', methods=['GET'])
def get_operators():
    """Get all unique Atlas operators for the filter dropdown."""
    try:
        # Query all unique non-empty Atlas operators, ordered alphabetically
        operators = db.session.query(AtlasStop.atlas_business_org_abbr)\
            .filter(AtlasStop.atlas_business_org_abbr.isnot(None))\
            .filter(AtlasStop.atlas_business_org_abbr != '')\
            .distinct()\
            .order_by(AtlasStop.atlas_business_org_abbr)\
            .all()
        
        # Extract the operator names from the query result tuples
        operator_list = [op[0] for op in operators if op[0]]
        
        return jsonify({
            "operators": operator_list,
            "total": len(operator_list)
        })
        
    except Exception as e:
        app.logger.error(f"Error fetching operators: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ----------------------------
# API Endpoint: /api/data
# ----------------------------
@data_bp.route('/api/data', methods=['GET'])
def get_data():
    try:
        # Parse viewport parameters
        bbox = request.args.get('bbox')
        if bbox:
            # bbox format: min_lat,min_lon,max_lat,max_lon
            bbox_parts = bbox.split(',')
            if len(bbox_parts) == 4:
                min_lat, min_lon, max_lat, max_lon = map(float, bbox_parts)
            else:
                raise ValueError("bbox parameter must have 4 values: min_lat,min_lon,max_lat,max_lon")
        else:
            # Fallback to individual parameters
            min_lat = float(request.args.get('min_lat'))
            max_lat = float(request.args.get('max_lat'))
            min_lon = float(request.args.get('min_lon'))
            max_lon = float(request.args.get('max_lon'))

        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        station_filter_str = request.args.get('station_filter', None)
        filter_types_str = request.args.get('filter_types', '')
        route_directions_str = request.args.get('route_directions', '')
        transport_types_filter_str = request.args.get('transport_types', None)
        node_type_filter_str = request.args.get('node_type', None)
        atlas_operator_filter_str = request.args.get('atlas_operator', None)
        
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 500))
        zoom = int(request.args.get('zoom', 14))

        # At lower zooms, avoid eager loading heavy relationships
        if zoom < 14:
            query = Stop.query
        else:
            query = Stop.query.options(
                joinedload(Stop.atlas_stop_details),
                joinedload(Stop.osm_node_details)
            )
        
        all_category_conditions = []

        # 1. Viewport filter (sargable: OR-of-ANDs instead of COALESCE)
        viewport_sargable = db.or_(
            db.and_(
                Stop.atlas_lat.isnot(None), Stop.atlas_lon.isnot(None),
                Stop.atlas_lat >= min_lat, Stop.atlas_lat <= max_lat,
                Stop.atlas_lon >= min_lon, Stop.atlas_lon <= max_lon
            ),
            db.and_(
                # Only use OSM coords when Atlas coords are null
                Stop.atlas_lat.is_(None), Stop.atlas_lon.is_(None),
                Stop.osm_lat.isnot(None), Stop.osm_lon.isnot(None),
                Stop.osm_lat >= min_lat, Stop.osm_lat <= max_lat,
                Stop.osm_lon >= min_lon, Stop.osm_lon <= max_lon
            )
        )
        all_category_conditions.append(viewport_sargable)

        # 2. Node Type filter
        if node_type_filter_str and node_type_filter_str.lower() != 'all':
            node_types = [nt.strip() for nt in node_type_filter_str.split(',') if nt.strip()]
            if node_types:
                node_type_or_conditions = []
                if 'atlas' in node_types:
                    node_type_or_conditions.append(Stop.sloid.isnot(None))
                if 'osm' in node_types:
                    node_type_or_conditions.append(Stop.osm_node_id.isnot(None))
                if node_type_or_conditions:
                    all_category_conditions.append(db.or_(*node_type_or_conditions) if len(node_type_or_conditions) > 1 else node_type_or_conditions[0])

        # 3. Transport Type filter
        if transport_types_filter_str:
            selected_transport_types = [t.strip() for t in transport_types_filter_str.split(',') if t.strip()]
            if selected_transport_types:
                transport_sub_conditions = []
                if 'ferry_terminal' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(OsmNode.osm_amenity == 'ferry_terminal'))
                if 'tram_stop' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(OsmNode.osm_railway == 'tram_stop'))
                if 'station' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(db.and_(OsmNode.osm_public_transport == 'station', OsmNode.osm_aerialway != 'station')))
                if 'platform' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(OsmNode.osm_public_transport == 'platform'))
                if 'stop_position' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(OsmNode.osm_public_transport == 'stop_position'))
                if 'aerialway_station' in selected_transport_types: 
                    transport_sub_conditions.append(Stop.osm_node_details.has(OsmNode.osm_aerialway == 'station'))
                if transport_sub_conditions:
                    all_category_conditions.append(db.or_(*transport_sub_conditions))
        
        # 4. Atlas Operator filter
        if atlas_operator_filter_str:
            atlas_operators = [op.strip() for op in atlas_operator_filter_str.split(',') if op.strip()]
            if atlas_operators:
                # Filter for stops that have Atlas details with the specified operator(s)
                operator_condition = Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                )
                all_category_conditions.append(operator_condition)
        
        # 5. Station/Node/Route ID filter (with improved route filtering)
        if station_filter_str:
            filter_values = [val.strip() for val in station_filter_str.split(',') if val.strip()]
            filter_types = filter_types_str.split(',')
            route_directions = route_directions_str.split(',')
            
            while len(filter_types) < len(filter_values): filter_types.append('station')
            while len(route_directions) < len(filter_values): route_directions.append('')
            
            if filter_values:
                station_id_sub_conditions = []
                for i, value in enumerate(filter_values):
                    filter_type = filter_types[i].strip()
                    direction = route_directions[i].strip()
                    if filter_type == 'atlas': station_id_sub_conditions.append(Stop.sloid.like(f'%{value}%'))
                    elif filter_type == 'osm': station_id_sub_conditions.append(Stop.osm_node_id.like(f'%{value}%'))
                    elif filter_type == 'hrdf_route':
                        station_id_sub_conditions.append(Stop.atlas_stop_details.has(
                            func.json_search(AtlasStop.routes_hrdf, 'one', value, None, '$[*].line_name') != None
                        ))
                    elif filter_type == 'route':
                        route_stops = get_stops_for_route(value, direction if direction else None)
                        route_specific_conditions = []
                        if route_stops['atlas_sloids']: route_specific_conditions.append(Stop.sloid.in_(route_stops['atlas_sloids']))
                        if route_stops['osm_nodes']: route_specific_conditions.append(Stop.osm_node_id.in_(route_stops['osm_nodes']))
                        if route_specific_conditions: station_id_sub_conditions.append(db.or_(*route_specific_conditions))
                    else: station_id_sub_conditions.append(Stop.uic_ref.like(f'%{value}%'))
                if station_id_sub_conditions:
                    all_category_conditions.append(db.or_(*station_id_sub_conditions))

        # 6. Stop Type and Match Method combined logic (with improved route matching filter)
        stop_type_match_method_or_conditions = []

        current_stop_types = []
        if stop_filter_str and stop_filter_str.lower() != 'all':
            current_stop_types = [t.strip() for t in stop_filter_str.split(',') if t.strip()]

        current_match_methods = []
        if match_method_str:
            current_match_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]

        # Handle 'matched' stops
        if 'matched' in current_stop_types:
            relevant_matched_methods = []
            
            for method in current_match_methods:
                if method in ['exact', 'name', 'manual']:
                    relevant_matched_methods.append(method)
                elif method.startswith('distance_matching_'):
                    # Use prefix/pattern matching for distance stages
                    relevant_matched_methods.append(method)
                elif method.startswith('route_gtfs') or method.startswith('route_hrdf'):
                    # Handle new route matching filters
                    relevant_matched_methods.append(method)
            
            if relevant_matched_methods:
                # Build conditions for route matching methods
                route_matching_conditions = []
                other_method_conditions = []
                
                for method in relevant_matched_methods:
                    if method.startswith('route_'):
                        # Use LIKE pattern to match route_gtfs, route_hrdf, etc.
                        route_matching_conditions.append(Stop.match_type.like(f'{method}%'))
                    elif method.startswith('distance_matching_'):
                        # Use LIKE for distance stages that may have suffixes
                        other_method_conditions.append(Stop.match_type.like(f'{method}%'))
                    else:
                        other_method_conditions.append(Stop.match_type == method)
                
                # Combine all method conditions
                all_method_conditions = other_method_conditions + route_matching_conditions
                
                if all_method_conditions:
                    stop_type_match_method_or_conditions.append(
                        db.and_(Stop.stop_type == 'matched', db.or_(*all_method_conditions))
                    )
            else:
                if not current_match_methods:
                    stop_type_match_method_or_conditions.append(Stop.stop_type == 'matched')

        # Handle 'unmatched' (ATLAS) stops
        if 'unmatched' in current_stop_types:
            filter_for_no_osm_nearby = 'no_nearby_counterpart' in current_match_methods
            filter_for_osm_nearby    = 'osm_within_50m' in current_match_methods

            unmatched_specific_condition = Stop.stop_type == 'unmatched'

            if filter_for_no_osm_nearby and not filter_for_osm_nearby:
                unmatched_specific_condition = db.and_(
                    Stop.stop_type == 'unmatched',
                    Stop.match_type == 'no_nearby_counterpart'
                )
            elif not filter_for_no_osm_nearby and filter_for_osm_nearby:
                unmatched_specific_condition = db.and_(
                    Stop.stop_type == 'unmatched',
                    db.or_(Stop.match_type != 'no_nearby_counterpart', Stop.match_type.is_(None))
                )
            
            stop_type_match_method_or_conditions.append(db.or_(
                unmatched_specific_condition,
                Stop.stop_type == 'station'
            ))
        
        # Handle 'osm' (pure/standalone) stops
        if 'osm' in current_stop_types:
            stop_type_match_method_or_conditions.append(Stop.stop_type == 'osm')
        
        if stop_type_match_method_or_conditions:
            all_category_conditions.append(db.or_(*stop_type_match_method_or_conditions))
        elif current_stop_types and not stop_type_match_method_or_conditions:
            all_category_conditions.append(db.false())

        if all_category_conditions:
            query = query.filter(db.and_(*all_category_conditions))

        query = query.offset(offset).limit(limit)
        stops = query.all()
        
        # Process results
        atlas_to_osm_matches = {}
        regular_stops = []
        
        for stop in stops:
            if zoom >= 14 and stop.stop_type == 'matched' and stop.sloid:
                # Group ATLAS stops with multiple OSM matches
                if stop.sloid not in atlas_to_osm_matches:
                                    atlas_to_osm_matches[stop.sloid] = {
                    "id": stop.id,
                    "sloid": stop.sloid,
                    "stop_type": stop.stop_type,
                    "match_type": stop.match_type,
                    "uic_ref": stop.uic_ref,
                    "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                    "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                    "atlas_business_org_abbr": stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details else None,
                    "atlas_lat": stop.atlas_lat,
                    "atlas_lon": stop.atlas_lon,
                    "lat": stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat,
                    "lon": stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon,
                    "routes_atlas": stop.atlas_stop_details.routes_atlas if stop.atlas_stop_details else None,
                    "routes_hrdf": stop.atlas_stop_details.routes_hrdf if stop.atlas_stop_details else None,
                    "routes_osm": stop.osm_node_details.routes_osm if stop.osm_node_details else None,
                    "atlas_duplicate_sloid": stop.atlas_duplicate_sloid,
                    "osm_matches": []
                }
                
                # Add OSM match data
                atlas_to_osm_matches[stop.sloid]["osm_matches"].append({
                    "osm_id": stop.id,
                    "osm_node_id": stop.osm_node_id,
                    "osm_local_ref": stop.osm_node_details.osm_local_ref if stop.osm_node_details else None,
                    "osm_network": stop.osm_node_details.osm_network if stop.osm_node_details else None,
                    "osm_operator": stop.osm_node_details.osm_operator if stop.osm_node_details else None,
                    "osm_public_transport": stop.osm_node_details.osm_public_transport if stop.osm_node_details else None,
                    "osm_railway": stop.osm_node_details.osm_railway if stop.osm_node_details else None,
                    "osm_amenity": stop.osm_node_details.osm_amenity if stop.osm_node_details else None,
                    "osm_aerialway": stop.osm_node_details.osm_aerialway if stop.osm_node_details else None,
                    "osm_name": stop.osm_node_details.osm_name if stop.osm_node_details else None,
                    "osm_uic_name": stop.osm_node_details.osm_uic_name if stop.osm_node_details else None,
                    "osm_lat": stop.osm_lat,
                    "osm_lon": stop.osm_lon,
                    "distance_m": stop.distance_m,
                    "routes_osm": stop.osm_node_details.routes_osm if stop.osm_node_details else None,
                    "match_type": stop.match_type,
                    "atlas_duplicate_sloid": stop.atlas_duplicate_sloid,
                    "osm_node_type": stop.osm_node_type
                })
            else:
                # Handle regular stops
                lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
                lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
                if zoom < 14:
                    # Minimal payload at lower zooms
                    regular_stops.append({
                        "id": stop.id,
                        "sloid": stop.sloid,
                        "stop_type": stop.stop_type,
                        "match_type": stop.match_type,
                        "uic_ref": stop.uic_ref,
                        "osm_node_id": stop.osm_node_id,
                        "atlas_lat": stop.atlas_lat,
                        "atlas_lon": stop.atlas_lon,
                        "osm_lat": stop.osm_lat,
                        "osm_lon": stop.osm_lon,
                        "distance_m": stop.distance_m,
                        "lat": lat,
                        "lon": lon,
                        "atlas_duplicate_sloid": stop.atlas_duplicate_sloid,
                        "osm_node_type": stop.osm_node_type
                    })
                else:
                    regular_stops.append({
                        "id": stop.id,
                        "sloid": stop.sloid,
                        "stop_type": stop.stop_type,
                        "match_type": stop.match_type,
                        "uic_ref": stop.uic_ref,
                        "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                        "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                        "atlas_business_org_abbr": stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details else None,
                        "osm_node_id": stop.osm_node_id,
                        "osm_local_ref": stop.osm_node_details.osm_local_ref if stop.osm_node_details else None,
                        "osm_network": stop.osm_node_details.osm_network if stop.osm_node_details else None,
                        "osm_operator": stop.osm_node_details.osm_operator if stop.osm_node_details else None,
                        "osm_public_transport": stop.osm_node_details.osm_public_transport if stop.osm_node_details else None,
                        "osm_railway": stop.osm_node_details.osm_railway if stop.osm_node_details else None,
                        "osm_amenity": stop.osm_node_details.osm_amenity if stop.osm_node_details else None,
                        "osm_aerialway": stop.osm_node_details.osm_aerialway if stop.osm_node_details else None,
                        "atlas_lat": stop.atlas_lat,
                        "atlas_lon": stop.atlas_lon,
                        "osm_name": stop.osm_node_details.osm_name if stop.osm_node_details else None,
                        "osm_uic_name": stop.osm_node_details.osm_uic_name if stop.osm_node_details else None,
                        "osm_lat": stop.osm_lat,
                        "osm_lon": stop.osm_lon,
                        "distance_m": stop.distance_m,
                        "lat": lat,
                        "lon": lon,
                        "routes_atlas": stop.atlas_stop_details.routes_atlas if stop.atlas_stop_details else None,
                        "routes_hrdf": stop.atlas_stop_details.routes_hrdf if stop.atlas_stop_details else None,
                        "routes_osm": stop.osm_node_details.routes_osm if stop.osm_node_details else None,
                        "atlas_duplicate_sloid": stop.atlas_duplicate_sloid,
                        "osm_node_type": stop.osm_node_type
                    })
        
        # Combine and return results
        combined_stops = regular_stops + (list(atlas_to_osm_matches.values()) if zoom >= 14 else [])
        return jsonify(combined_stops)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------
# API Endpoint: /api/route_stops
# ---------------------------
@data_bp.route('/api/route_stops', methods=['GET'])
def get_route_stops():
    """API endpoint to get all stops for a given route"""
    route_id = request.args.get('route_id')
    direction = request.args.get('direction')
    
    if not route_id:
        return jsonify({'error': 'No route ID provided'}), 400
    
    stops = get_stops_for_route(route_id, direction)
    return jsonify(stops) 