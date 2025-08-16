from flask import Blueprint, request, jsonify, current_app as app
import random
from sqlalchemy import func
from backend.models import Stop, AtlasStop, OsmNode, PersistentData, Problem
from backend.extensions import db, limiter
from flask_login import login_required
from backend.serializers.stops import format_stop_data
from backend.query_helpers import get_query_builder, parse_filter_params, optimize_query_for_endpoint

search_bp = Blueprint('search', __name__)


@search_bp.route('/api/manual_match', methods=['POST'])
@limiter.limit("30/minute")
@login_required
def manual_match():
    try:
        payload = request.get_json() or {}
        atlas_stop_id = payload.get('atlas_stop_id')
        osm_stop_id = payload.get('osm_stop_id')
        make_persistent = bool(payload.get('make_persistent', False))
        if not atlas_stop_id or not osm_stop_id:
            return jsonify({"success": False, "error": "atlas_stop_id and osm_stop_id are required"}), 400
        atlas_stop = db.session.get(Stop, atlas_stop_id)
        osm_stop = db.session.get(Stop, osm_stop_id)
        if not atlas_stop or not osm_stop:
            return jsonify({"success": False, "error": "One or both stops not found"}), 404
        atlas_stop.stop_type = 'matched'
        atlas_stop.match_type = 'manual'
        atlas_stop.osm_node_id = osm_stop.osm_node_id
        atlas_stop.osm_lat = osm_stop.osm_lat
        atlas_stop.osm_lon = osm_stop.osm_lon
        osm_stop.stop_type = 'matched'
        osm_stop.match_type = 'manual'
        osm_stop.sloid = atlas_stop.sloid
        osm_stop.atlas_lat = atlas_stop.atlas_lat
        osm_stop.atlas_lon = atlas_stop.atlas_lon
        if make_persistent:
            atlas_stop.manual_is_persistent = True
            osm_stop.manual_is_persistent = True
        db.session.add(atlas_stop)
        db.session.add(osm_stop)
        db.session.flush()
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


@search_bp.route('/api/search', methods=['GET'])
@limiter.limit("60/minute")
def search():
    query_str = request.args.get('q', '').lower()
    results = {"osm": [], "atlas": []}
    if query_str:
        search_pattern = f"%{query_str}%"
        matched_query = optimize_query_for_endpoint(Stop.query, 'search').outerjoin(
            AtlasStop, Stop.sloid == AtlasStop.sloid
        ).outerjoin(
            OsmNode, Stop.osm_node_id == OsmNode.osm_node_id
        ).filter(Stop.stop_type == 'matched').filter(
            db.or_(
                AtlasStop.atlas_designation.ilike(search_pattern),
                AtlasStop.atlas_designation_official.ilike(search_pattern),
                Stop.uic_ref.ilike(search_pattern),
                AtlasStop.atlas_business_org_abbr.ilike(search_pattern),
                OsmNode.osm_name.ilike(search_pattern),
                OsmNode.osm_local_ref.ilike(search_pattern),
                OsmNode.osm_network.ilike(search_pattern),
                OsmNode.osm_operator.ilike(search_pattern),
                OsmNode.osm_uic_name.ilike(search_pattern),
                OsmNode.osm_railway.ilike(search_pattern),
                OsmNode.osm_amenity.ilike(search_pattern),
                OsmNode.osm_aerialway.ilike(search_pattern)
            )
        )
        matched_stops = matched_query.all()
        for stop in matched_stops:
            results['atlas'].append({
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "atlas_business_org_abbr": (stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details else None),
                "osm_lat": stop.osm_lat,
                "osm_lon": stop.osm_lon,
                "osm_network": (stop.osm_node_details.osm_network if stop.osm_node_details else None),
                "osm_operator": (stop.osm_node_details.osm_operator if stop.osm_node_details else None),
                "osm_public_transport": (stop.osm_node_details.osm_public_transport if stop.osm_node_details else None),
                "osm_railway": (stop.osm_node_details.osm_railway if stop.osm_node_details else None),
                "osm_amenity": (stop.osm_node_details.osm_amenity if stop.osm_node_details else None),
                "osm_aerialway": (stop.osm_node_details.osm_aerialway if stop.osm_node_details else None),
                "match_type": stop.match_type,
                "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                "uic_ref": stop.uic_ref,
                "osm_node_id": stop.osm_node_id,
                "osm_local_ref": stop.osm_node_details.osm_local_ref if stop.osm_node_details else None,
                "osm_uic_name": stop.osm_node_details.osm_uic_name if stop.osm_node_details else None,
                "osm_uic_ref": stop.osm_node_details.osm_uic_ref if stop.osm_node_details else None
            })
        unmatched_query = optimize_query_for_endpoint(Stop.query, 'search').outerjoin(
            AtlasStop, Stop.sloid == AtlasStop.sloid
        ).filter(Stop.stop_type == 'unmatched').filter(
            db.or_(
                AtlasStop.atlas_designation.ilike(search_pattern),
                AtlasStop.atlas_designation_official.ilike(search_pattern),
                AtlasStop.atlas_business_org_abbr.ilike(search_pattern),
                Stop.uic_ref.ilike(search_pattern)
            )
        )
        unmatched_stops = unmatched_query.all()
        for stop in unmatched_stops:
            results['atlas'].append({
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "atlas_business_org_abbr": (stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details else None),
                "match_type": stop.match_type,
                "atlas_designation": stop.atlas_stop_details.atlas_designation if stop.atlas_stop_details else None,
                "atlas_designation_official": stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details else None,
                "uic_ref": stop.uic_ref,
                "osm_railway": (stop.osm_node_details.osm_railway if stop.osm_node_details else None),
                "osm_amenity": (stop.osm_node_details.osm_amenity if stop.osm_node_details else None),
                "osm_aerialway": (stop.osm_node_details.osm_aerialway if stop.osm_node_details else None),
            })
    return jsonify(results)


@search_bp.route('/api/top_matches', methods=['GET'])
@limiter.limit("60/minute")
def get_top_matches():
    try:
        limit = int(request.args.get('limit', 10))
        match_method_str = request.args.get('match_method', None)
        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()
        query = optimize_query_for_endpoint(Stop.query, 'search')
        query = query.filter(Stop.stop_type == 'matched', Stop.distance_m.isnot(None))
        query = query_builder.apply_common_filters(query, filters)
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
        stops = query.order_by(Stop.distance_m.desc()).limit(limit).all()
        stops_data = [format_stop_data(stop) for stop in stops]
        return jsonify(stops_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@search_bp.route('/api/random_stop', methods=['GET'])
@limiter.limit("30/minute")
def get_random_stop():
    try:
        # Fast random pick using id range sampling (avoids ORDER BY RAND() and large OFFSET scans)
        min_id, max_id = db.session.query(func.min(Stop.id), func.max(Stop.id)).first()
        if min_id is None or max_id is None:
            return jsonify({"error": "No stop found."}), 404

        random_stop = None
        for _ in range(5):
            candidate_id = random.randint(min_id, max_id)
            random_stop = Stop.query.filter(Stop.id >= candidate_id).order_by(Stop.id.asc()).limit(1).first()
            if random_stop:
                break
        if not random_stop:
            # Fallback to the first available stop within range
            random_stop = Stop.query.order_by(Stop.id.asc()).first()
        if not random_stop:
            return jsonify({"error": "No stop found."}), 404

        stop_data = format_stop_data(random_stop, include_routes=False, include_notes=False)

        # Prefer ATLAS coords if available, otherwise OSM
        if random_stop.atlas_lat is not None and random_stop.atlas_lon is not None:
            center_lat, center_lon = random_stop.atlas_lat, random_stop.atlas_lon
            popup_view_type = 'atlas'
        elif random_stop.osm_lat is not None and random_stop.osm_lon is not None:
            center_lat, center_lon = random_stop.osm_lat, random_stop.osm_lon
            popup_view_type = 'osm'
        else:
            return jsonify({"error": "Selected random stop has no valid coordinates."}), 404

        return jsonify({
            "stop": stop_data,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "popup_view_type": popup_view_type
        })
    except Exception as e:
        app.logger.error(f"Error fetching random stop: {str(e)}")
        return jsonify({"error": str(e)}), 500


@search_bp.route('/api/stop_by_id', methods=['GET'])
@limiter.limit("60/minute")
def get_stop_by_id():
    try:
        identifier = request.args.get('identifier')
        identifier_type = request.args.get('identifier_type')
        if not identifier or not identifier_type:
            return jsonify({"error": "Missing identifier or identifier_type"}), 400
        stop = None
        lat_col_name, lon_col_name = None, None
        popup_view_type = None
        if identifier_type == 'sloid':
            stop = optimize_query_for_endpoint(Stop.query, 'search').filter(Stop.sloid == identifier).first()
            if stop:
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
        elif identifier_type in ('osm', 'osm_node_id'):
            stop = optimize_query_for_endpoint(Stop.query, 'search').filter(Stop.osm_node_id == identifier).first()
            if stop:
                lat_col_name = 'osm_lat'
                lon_col_name = 'osm_lon'
                popup_view_type = 'osm'
        else:
            return jsonify({"error": "Invalid identifier_type"}), 400
        if stop:
            stop_data = format_stop_data(stop)
            center_lat = getattr(stop, lat_col_name, None)
            center_lon = getattr(stop, lon_col_name, None)
            if center_lat is None or center_lon is None:
                center_lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
                center_lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
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


