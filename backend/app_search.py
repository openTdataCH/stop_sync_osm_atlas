from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode
from backend.app_data import format_stop_data, get_stops_for_route

# Create blueprint for search and navigation operations
search_bp = Blueprint('search', __name__)

# ----------------------------
# API Endpoint: /api/save
# ----------------------------
@search_bp.route('/api/save', methods=['POST'])
def save_changes():
    try:
        changes = request.json
        manual_matches = changes.get("manualMatches", [])
        for pair in manual_matches:
            atlas_id = pair.get("atlas_id")
            osm_id = pair.get("osm_id")
            if atlas_id and osm_id:
                atlas_stop = Stop.query.get(atlas_id)
                osm_stop = Stop.query.get(osm_id)
                if atlas_stop and osm_stop:
                    atlas_stop.stop_type = 'matched'
                    osm_stop.stop_type = 'matched'
                    atlas_stop.match_type = 'manual'
                    osm_stop.match_type = 'manual'
                    db.session.add(atlas_stop)
                    db.session.add(osm_stop)
        db.session.commit()
        import json
        with open("changes.json", "w", encoding="utf-8") as f:
            json.dump(changes, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "success", "message": "Changes saved."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ----------------------------
# API Endpoint: /api/search
# ----------------------------
@search_bp.route('/api/search', methods=['GET'])
def search():
    query_str = request.args.get('q', '').lower()
    results = {"osm": [], "atlas": []}
    if query_str:
        search_pattern = f"%{query_str}%"
        
        # Base query with outer joins to search across related tables
        matched_query = Stop.query.outerjoin(
            AtlasStop, Stop.sloid == AtlasStop.sloid
        ).outerjoin(
            OsmNode, Stop.osm_node_id == OsmNode.osm_node_id
        ).filter(Stop.stop_type == 'matched').filter(
            db.or_(
                AtlasStop.atlas_designation.ilike(search_pattern),
                AtlasStop.atlas_designation_official.ilike(search_pattern),
                Stop.uic_ref.ilike(search_pattern),
                Stop.atlas_business_org_abbr.ilike(search_pattern),
                OsmNode.osm_name.ilike(search_pattern),
                OsmNode.osm_local_ref.ilike(search_pattern),
                OsmNode.osm_network.ilike(search_pattern),
                Stop.osm_operator.ilike(search_pattern),
                OsmNode.osm_uic_name.ilike(search_pattern),
                Stop.osm_railway.ilike(search_pattern),
                Stop.osm_amenity.ilike(search_pattern),
                Stop.osm_aerialway.ilike(search_pattern)
            )
        ).options(
            joinedload(Stop.atlas_stop_details),
            joinedload(Stop.osm_node_details)
        )
        
        matched_stops = matched_query.all()
        for stop in matched_stops:
            results['atlas'].append({
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "atlas_business_org_abbr": stop.atlas_business_org_abbr,
                "osm_lat": stop.osm_lat,
                "osm_lon": stop.osm_lon,
                "osm_network": stop.osm_node_details.osm_network if stop.osm_node_details else None,
                "osm_operator": stop.osm_operator,
                "osm_public_transport": stop.osm_public_transport,
                "osm_railway": stop.osm_railway,
                "osm_amenity": stop.osm_amenity,
                "osm_aerialway": stop.osm_aerialway,
                "match_type": stop.match_type,
                "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                "uic_ref": stop.uic_ref,
                "osm_node_id": stop.osm_node_id,
                "osm_local_ref": stop.osm_node_details.osm_local_ref if stop.osm_node_details else None,
                "osm_uic_name": stop.osm_node_details.osm_uic_name if stop.osm_node_details else None
            })
        # Unmatched stops query with joins
        unmatched_query = Stop.query.outerjoin(
            AtlasStop, Stop.sloid == AtlasStop.sloid
        ).filter(Stop.stop_type == 'unmatched').filter(
            db.or_(
                AtlasStop.atlas_designation.ilike(search_pattern),
                AtlasStop.atlas_designation_official.ilike(search_pattern),
                Stop.atlas_business_org_abbr.ilike(search_pattern),
                Stop.uic_ref.ilike(search_pattern),
                Stop.osm_railway.ilike(search_pattern),
                Stop.osm_amenity.ilike(search_pattern),
                Stop.osm_aerialway.ilike(search_pattern)
            )
        ).options(joinedload(Stop.atlas_stop_details))
        
        unmatched_stops = unmatched_query.all()
        for stop in unmatched_stops:
            results['atlas'].append({
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "atlas_business_org_abbr": stop.atlas_business_org_abbr,
                "match_type": stop.match_type,
                "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                "uic_ref": stop.uic_ref,
                "osm_railway": stop.osm_railway,
                "osm_amenity": stop.osm_amenity,
                "osm_aerialway": stop.osm_aerialway,
            })
    return jsonify(results)

# ----------------------------
# API Endpoint: /api/top_matches
# ----------------------------
@search_bp.route('/api/top_matches', methods=['GET'])
def get_top_matches():
    try:
        # Parse parameters
        limit = int(request.args.get('limit', 10))
        match_method_str = request.args.get('match_method', None)
        station_filter_str = request.args.get('station_filter', None)
        filter_types_str = request.args.get('filter_types', '')
        route_directions_str = request.args.get('route_directions', '')
        transport_types_filter_str = request.args.get('transport_types', None)
        atlas_operator_filter_str = request.args.get('atlas_operator', None)

        # Base query for top_matches
        query = Stop.query.filter(Stop.stop_type == 'matched', Stop.distance_m.isnot(None)).options(
            joinedload(Stop.atlas_stop_details),
            joinedload(Stop.osm_node_details)
        )
        
        user_filter_conditions = [] # For additional user-selectable filters

        # 1. Transport Type filter
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
                    user_filter_conditions.append(db.or_(*transport_sub_conditions))

        # 2. Match Method filter (specific methods)
        if match_method_str:
            specific_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]
            if specific_methods:
                user_filter_conditions.append(Stop.match_type.in_(specific_methods))
            else:
                user_filter_conditions.append(db.false())
        
        # 3. Atlas Operator filter
        if atlas_operator_filter_str:
            atlas_operators = [op.strip() for op in atlas_operator_filter_str.split(',') if op.strip()]
            if atlas_operators:
                user_filter_conditions.append(Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                ))
        
        # 4. Station/Node/Route ID filter
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
                    elif filter_type == 'route':
                        route_stops = get_stops_for_route(value, direction if direction else None)
                        route_specific_conditions = []
                        if route_stops['atlas_sloids']: route_specific_conditions.append(Stop.sloid.in_(route_stops['atlas_sloids']))
                        if route_stops['osm_nodes']: route_specific_conditions.append(Stop.osm_node_id.in_(route_stops['osm_nodes']))
                        if route_specific_conditions: station_id_sub_conditions.append(db.or_(*route_specific_conditions))
                    else: station_id_sub_conditions.append(Stop.uic_ref.like(f'%{value}%'))
                if station_id_sub_conditions:
                    user_filter_conditions.append(db.or_(*station_id_sub_conditions))

        # Combine all user-selected filter category conditions using the global operator
        if user_filter_conditions:
            query = query.filter(db.and_(*user_filter_conditions))
        
        # Get results sorted by distance, then apply limit
        stops = query.order_by(Stop.distance_m.desc()).limit(limit).all()
        
        # Format response data
        stops_data = [format_stop_data(stop) for stop in stops]
        return jsonify(stops_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------
# API Endpoint: /api/random_stop
# ----------------------------
@search_bp.route('/api/random_stop', methods=['GET'])
def get_random_stop():
    try:
        # Filter parameters (optional)
        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        station_filter_str = request.args.get('station_filter', None)
        filter_types_str = request.args.get('filter_types', None)
        route_directions_str = request.args.get('route_directions', None)
        transport_types_filter_str = request.args.get('transport_types', None)
        node_type_filter_str = request.args.get('node_type', None)
        atlas_operator_filter_str = request.args.get('atlas_operator', None)
        preferred_view = request.args.get('preferred_view', 'atlas') # 'atlas' or 'osm'

        query = Stop.query.options(
            joinedload(Stop.atlas_stop_details),
            joinedload(Stop.osm_node_details)
        )
        all_category_conditions = []

        # 1. Stop Type filter
        if stop_filter_str and stop_filter_str.lower() != 'all':
            types = [t.strip() for t in stop_filter_str.split(',') if t.strip()]
            if types:
                all_category_conditions.append(Stop.stop_type.in_(types))
        
        # 2. Node Type filter
        if node_type_filter_str and node_type_filter_str.lower() != 'all':
            node_types = [nt.strip() for nt in node_type_filter_str.split(',') if nt.strip()]
            if node_types:
                node_type_sub_conditions = []
                if 'atlas' in node_types: node_type_sub_conditions.append(Stop.sloid.isnot(None))
                if 'osm' in node_types: node_type_sub_conditions.append(Stop.osm_node_id.isnot(None))
                if node_type_sub_conditions:
                    all_category_conditions.append(db.or_(*node_type_sub_conditions) if len(node_type_sub_conditions) > 1 else node_type_sub_conditions[0])

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
                all_category_conditions.append(Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                ))

        # 5. Match Method filter
        if match_method_str:
            specific_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]
            if specific_methods:
                all_category_conditions.append(Stop.match_type.in_(specific_methods))
            elif stop_filter_str and 'matched' in stop_filter_str.split(','):
                all_category_conditions.append(db.false()) # User unchecked all matched methods
        
        # 6. Station/Node/Route ID filter
        if station_filter_str:
            filter_values = [val.strip() for val in station_filter_str.split(',') if val.strip()]
            filter_types = [val.strip() for val in filter_types_str.split(',') if val.strip()] if filter_types_str else []
            route_directions = [val.strip() for val in route_directions_str.split(',') if val.strip()] if route_directions_str else []
            
            while len(filter_types) < len(filter_values): filter_types.append('station')
            while len(route_directions) < len(filter_values): route_directions.append('')

            if filter_values:
                station_id_sub_conditions = []
                for i, value in enumerate(filter_values):
                    filter_type_single = filter_types[i]; direction = route_directions[i]
                    if filter_type_single == 'atlas': station_id_sub_conditions.append(Stop.sloid.like(f'%{value}%'))
                    elif filter_type_single == 'osm': station_id_sub_conditions.append(Stop.osm_node_id.like(f'%{value}%'))
                    elif filter_type_single == 'route':
                        route_stops_data = get_stops_for_route(value, direction if direction else None)
                        route_specific_conditions = []
                        if route_stops_data['atlas_sloids']: route_specific_conditions.append(Stop.sloid.in_(route_stops_data['atlas_sloids']))
                        if route_stops_data['osm_nodes']: route_specific_conditions.append(Stop.osm_node_id.in_(route_stops_data['osm_nodes']))
                        if route_specific_conditions: station_id_sub_conditions.append(db.or_(*route_specific_conditions) if len(route_specific_conditions) > 1 else route_specific_conditions[0])
                    else: station_id_sub_conditions.append(Stop.uic_ref.like(f'%{value}%'))
                if station_id_sub_conditions:
                     all_category_conditions.append(db.or_(*station_id_sub_conditions) if len(station_id_sub_conditions) > 1 else station_id_sub_conditions[0])
        
        # Combine all category conditions using the global operator
        if all_category_conditions:
            query = query.filter(db.and_(*all_category_conditions))
        
        # Ensure the chosen random stop has coordinates for the preferred view, if possible
        coordinate_filter_conditions = []
        if preferred_view == 'atlas':
            coordinate_filter_conditions.append(Stop.atlas_lat.isnot(None))
            coordinate_filter_conditions.append(Stop.atlas_lon.isnot(None))
        elif preferred_view == 'osm':
            coordinate_filter_conditions.append(Stop.osm_lat.isnot(None))
            coordinate_filter_conditions.append(Stop.osm_lon.isnot(None))
        else: # Default or if preferred_view is invalid, try to get any stop with any coordinate
            coordinate_filter_conditions.append(db.or_(
                db.and_(Stop.atlas_lat.isnot(None), Stop.atlas_lon.isnot(None)),
                db.and_(Stop.osm_lat.isnot(None), Stop.osm_lon.isnot(None))
            ))
        query = query.filter(db.and_(*coordinate_filter_conditions))

        random_stop = query.order_by(func.rand()).first()

        if random_stop:
            stop_data = format_stop_data(random_stop)
            center_lat, center_lon, popup_view_type_actual = None, None, preferred_view

            if preferred_view == 'atlas' and random_stop.atlas_lat is not None:
                center_lat, center_lon = random_stop.atlas_lat, random_stop.atlas_lon
            elif preferred_view == 'osm' and random_stop.osm_lat is not None:
                center_lat, center_lon = random_stop.osm_lat, random_stop.osm_lon
            else: # Fallback logic if preferred coordinates are not available
                if random_stop.atlas_lat is not None:
                    center_lat, center_lon = random_stop.atlas_lat, random_stop.atlas_lon
                    popup_view_type_actual = 'atlas'
                elif random_stop.osm_lat is not None:
                    center_lat, center_lon = random_stop.osm_lat, random_stop.osm_lon
                    popup_view_type_actual = 'osm'
                else:
                    return jsonify({"error": "Selected random stop has no valid coordinates."}), 404

            return jsonify({
                "stop": stop_data,
                "center_lat": center_lat,
                "center_lon": center_lon,
                "popup_view_type": popup_view_type_actual
            })
        else:
            return jsonify({"error": "No stop found for the given criteria in the current view."}), 404
    except Exception as e:
        app.logger.error(f"Error fetching random stop: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ----------------------------
# API Endpoint: /api/stop_by_id
# ----------------------------
@search_bp.route('/api/stop_by_id', methods=['GET'])
def get_stop_by_id():
    try:
        identifier = request.args.get('identifier')
        identifier_type = request.args.get('identifier_type') # 'sloid' or 'osm_node_id'

        if not identifier or not identifier_type:
            return jsonify({"error": "Missing identifier or identifier_type"}), 400

        stop = None
        lat_col_name, lon_col_name = None, None
        popup_view_type = None

        if identifier_type == 'sloid':
            stop = Stop.query.filter(Stop.sloid == identifier).options(
                joinedload(Stop.atlas_stop_details),
                joinedload(Stop.osm_node_details)
            ).first()
            if stop:
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
        elif identifier_type == 'osm': # Matching the filterType value used in main.js
            stop = Stop.query.filter(Stop.osm_node_id == identifier).options(
                joinedload(Stop.atlas_stop_details),
                joinedload(Stop.osm_node_details)
            ).first()
            if stop:
                # If it's a pure OSM stop or a matched one, osm_lat/lon should be primary
                lat_col_name = 'osm_lat'
                lon_col_name = 'osm_lon'
                popup_view_type = 'osm'
        else:
            return jsonify({"error": "Invalid identifier_type"}), 400

        if stop:
            stop_data = format_stop_data(stop) # Use existing helper
            center_lat = getattr(stop, lat_col_name, None)
            center_lon = getattr(stop, lon_col_name, None)

            if center_lat is None or center_lon is None:
                # Fallback if specific coords are missing, though query should ensure they exist for the type
                center_lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
                center_lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
                # If still None, then we can't center
                if center_lat is None or center_lon is None:
                    return jsonify({"error": f"Coordinates not available for {identifier_type} view of stop ID {identifier}"}), 404

            return jsonify({
                "stop": stop_data,
                "center_lat": center_lat,
                "center_lon": center_lon,
                "popup_view_type": popup_view_type
            })
        else:
            return jsonify({"error": f"No stop found for {identifier_type}: {identifier}"}), 404
    except Exception as e:
        app.logger.error(f"Error fetching stop by ID: {str(e)}")
        return jsonify({"error": str(e)}), 500 