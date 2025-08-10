from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode, PersistentData, Problem
from backend.app_data import format_stop_data
from backend.query_helpers import get_query_builder, parse_filter_params, optimize_query_for_endpoint

# Create blueprint for search and navigation operations
search_bp = Blueprint('search', __name__)

# ----------------------------
# API Endpoint: /api/manual_match
# ----------------------------
@search_bp.route('/api/manual_match', methods=['POST'])
def manual_match():
    """
    Create a manual match between an ATLAS stop (by stop.id) and an OSM stop (by stop.id).
    Request JSON:
      {
        "atlas_stop_id": <int>,
        "osm_stop_id": <int>,
        "make_persistent": <bool, optional>
      }
    Behavior:
      - Sets both stops to stop_type='matched', match_type='manual'.
      - When make_persistent is true, flags manual_is_persistent on both stops.
    """
    try:
        payload = request.get_json() or {}
        atlas_stop_id = payload.get('atlas_stop_id')
        osm_stop_id = payload.get('osm_stop_id')
        make_persistent = bool(payload.get('make_persistent', False))

        if not atlas_stop_id or not osm_stop_id:
            return jsonify({"success": False, "error": "atlas_stop_id and osm_stop_id are required"}), 400

        atlas_stop = Stop.query.get(atlas_stop_id)
        osm_stop = Stop.query.get(osm_stop_id)

        if not atlas_stop or not osm_stop:
            return jsonify({"success": False, "error": "One or both stops not found"}), 404

        # Set manual match flags and link both sides
        atlas_stop.stop_type = 'matched'
        atlas_stop.match_type = 'manual'
        # Link OSM details to atlas row
        atlas_stop.osm_node_id = osm_stop.osm_node_id
        atlas_stop.osm_lat = osm_stop.osm_lat
        atlas_stop.osm_lon = osm_stop.osm_lon

        osm_stop.stop_type = 'matched'
        osm_stop.match_type = 'manual'
        # Link ATLAS details to osm row
        osm_stop.sloid = atlas_stop.sloid
        osm_stop.atlas_lat = atlas_stop.atlas_lat
        osm_stop.atlas_lon = atlas_stop.atlas_lon

        if make_persistent:
            atlas_stop.manual_is_persistent = True
            osm_stop.manual_is_persistent = True

        db.session.add(atlas_stop)
        db.session.add(osm_stop)
        db.session.flush()

        # Mark related 'unmatched' problems as solved with a manual match note
        atlas_unmatched = Problem.query.filter_by(stop_id=atlas_stop.id, problem_type='unmatched').first()
        if atlas_unmatched:
            atlas_unmatched.solution = f"Manual match to OSM {osm_stop.osm_node_id}"
            atlas_unmatched.is_persistent = make_persistent
            db.session.add(atlas_unmatched)
        osm_unmatched = Problem.query.filter_by(stop_id=osm_stop.id, problem_type='unmatched').first()
        if osm_unmatched:
            osm_unmatched.solution = f"Manual match to ATLAS {atlas_stop.sloid}"
            osm_unmatched.is_persistent = make_persistent
            db.session.add(osm_unmatched)

        # Optionally create/update persistent mapping entry for manual match
        if make_persistent:
            existing = PersistentData.query.filter(
                PersistentData.sloid == atlas_stop.sloid,
                PersistentData.osm_node_id == osm_stop.osm_node_id,
                PersistentData.problem_type == 'unmatched',
                PersistentData.note_type.is_(None)
            ).first()
            if existing:
                existing.solution = 'manual'
            else:
                db.session.add(PersistentData(
                    sloid=atlas_stop.sloid,
                    osm_node_id=osm_stop.osm_node_id,
                    problem_type='unmatched',
                    solution='manual'
                ))

        db.session.commit()

        return jsonify({"success": True, "message": "Manual match saved", "is_persistent": make_persistent})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ----------------------------
# API Endpoint: /api/search
# ----------------------------
@search_bp.route('/api/search', methods=['GET'])
def search():
    query_str = request.args.get('q', '').lower()
    results = {"osm": [], "atlas": []}
    if query_str:
        search_pattern = f"%{query_str}%"
        
        # Base query with outer joins to search across related tables (optimized)
        matched_query = optimize_query_for_endpoint(Stop.query, 'search').outerjoin(
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
        # Unmatched stops query with joins (optimized for Atlas data only)
        unmatched_query = optimize_query_for_endpoint(Stop.query, 'search').outerjoin(
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
        )
        
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

        # Parse filters and build optimized query
        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()
        
        # Base query for top_matches with optimized loading
        query = optimize_query_for_endpoint(Stop.query, 'search')
        query = query.filter(Stop.stop_type == 'matched', Stop.distance_m.isnot(None))
        
        # Apply common filters
        query = query_builder.apply_common_filters(query, filters)
        
        # Apply match method filter if specified (support prefix for distance/route)
        if match_method_str:
            specific_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]
            if specific_methods:
                method_conditions = []
                for m in specific_methods:
                    if m.startswith('distance_matching_') or m.startswith('route_'):
                        method_conditions.append(Stop.match_type.like(f"{m}%"))
                    else:
                        method_conditions.append(Stop.match_type == m)
                query = query.filter(db.or_(*method_conditions))
            else:
                query = query.filter(db.false())
        
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

        # Parse filters and build optimized query
        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()
        query = optimize_query_for_endpoint(Stop.query, 'search')
        
        # Apply common filters
        query = query_builder.apply_common_filters(query, filters)
        
        # Additional filters specific to random stop
        additional_conditions = []
        
        # Stop Type filter
        if stop_filter_str and stop_filter_str.lower() != 'all':
            types = [t.strip() for t in stop_filter_str.split(',') if t.strip()]
            if types:
                additional_conditions.append(Stop.stop_type.in_(types))
        
        # Match Method filter
        if match_method_str:
            specific_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]
            if specific_methods:
                additional_conditions.append(Stop.match_type.in_(specific_methods))
            elif stop_filter_str and 'matched' in stop_filter_str.split(','):
                additional_conditions.append(db.false())  # User unchecked all matched methods
        
        # Apply additional conditions
        if additional_conditions:
            query = query.filter(db.and_(*additional_conditions))
        
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
            # For SLOID lookup, we primarily need Atlas details
            stop = optimize_query_for_endpoint(Stop.query, 'search').filter(Stop.sloid == identifier).first()
            if stop:
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
        elif identifier_type == 'osm': # Matching the filterType value used in main.js
            # For OSM lookup, we primarily need OSM details
            stop = optimize_query_for_endpoint(Stop.query, 'search').filter(Stop.osm_node_id == identifier).first()
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