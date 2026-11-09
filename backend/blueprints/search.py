from flask import Blueprint, request, jsonify, current_app as app
import random
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from backend.models import StopsMatched, AtlasStop
from backend.extensions import db, limiter
from backend.serializers.stops import format_stop_data
from backend.services.stop_lookup import InvalidLookup, lookup_payload, parse_lookup
from backend.services import stop_suggest
from backend.services.transport_routes import get_stops_for_route
from backend.queries.helpers import get_query_builder, parse_filter_params, optimize_query_for_endpoint, resolve_stop_type_match_filters, build_stop_scope_condition, build_match_method_conditions
from backend.queries.helpers import build_atlas_duplicate_membership_condition

search_bp = Blueprint('search', __name__)


@search_bp.route('/api/top_matches', methods=['GET'])
@limiter.limit("60/minute")
def get_top_matches():
    try:
        from backend.services.validators import validate_pagination
        try:
            _, limit = validate_pagination(1, request.args.get('limit', 10), max_limit=100)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        match_method_str = request.args.get('match_method', None)
        show_duplicates_only = request.args.get('show_duplicates_only', 'false').lower() == 'true'
        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()
        query = optimize_query_for_endpoint(StopsMatched.query, 'search')
        query = query.filter(StopsMatched.stop_type == 'matched', StopsMatched.distance_m.isnot(None))
        query = query_builder.apply_common_filters(query, filters)
        if show_duplicates_only:
            duplicate_condition = build_atlas_duplicate_membership_condition()
            query = query.filter(StopsMatched.atlas_stop_details.has(duplicate_condition))
        if match_method_str:
            specific_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]
            if specific_methods:
                method_condition = build_match_method_conditions(StopsMatched, specific_methods)
                query = query.filter(method_condition) if method_condition is not None else query.filter(db.false())
            else:
                query = query.filter(db.false())
        stops = query.order_by(StopsMatched.distance_m.desc()).limit(limit).all()
        stops_data = [format_stop_data(stop) for stop in stops]
        return jsonify(stops_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@search_bp.route('/api/random_stop', methods=['GET'])
@limiter.limit("30/minute")
def get_random_stop():
    try:
        # Honor the same filters as the main UI.
        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        show_duplicates_only = request.args.get('show_duplicates_only', 'false').lower() == 'true'
        top_n = request.args.get('top_n', None)

        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()

        query = optimize_query_for_endpoint(StopsMatched.query, 'search')
        query = query_builder.apply_common_filters(query, filters)

        resolved_filters = resolve_stop_type_match_filters(stop_filter_str, match_method_str)
        scope_condition = build_stop_scope_condition(StopsMatched, resolved_filters)
        if scope_condition is not None:
            query = query.filter(scope_condition)

        if show_duplicates_only:
            duplicate_condition = build_atlas_duplicate_membership_condition()
            query = query.filter(StopsMatched.atlas_stop_details.has(duplicate_condition))

        # If Top-N mode is active, pick randomly from the (small) top-N set.
        n_val = None
        if top_n:
            try:
                n_val = int(top_n)
            except Exception:
                n_val = None
        if n_val and n_val > 0:
            top_query = query.filter(StopsMatched.stop_type == 'matched', StopsMatched.distance_m.isnot(None)) \
                .order_by(StopsMatched.distance_m.desc()) \
                .limit(n_val)
            candidates = top_query.all()
            if not candidates:
                return jsonify({"error": "No stop found for the current filters."}), 404
            random_stop = random.choice(candidates)
        else:
            # Fast random pick using id range sampling (avoids ORDER BY RAND() and large OFFSET scans)
            min_id, max_id = query.with_entities(func.min(StopsMatched.id), func.max(StopsMatched.id)).first()
            if min_id is None or max_id is None:
                return jsonify({"error": "No stop found for the current filters."}), 404

            random_stop = None
            for _ in range(5):
                candidate_id = random.randint(min_id, max_id)
                random_stop = query.filter(StopsMatched.id >= candidate_id).order_by(StopsMatched.id.asc()).limit(1).first()
                if random_stop:
                    break
            if not random_stop:
                # Fallback to the first available stop within range
                random_stop = query.order_by(StopsMatched.id.asc()).first()
            if not random_stop:
                return jsonify({"error": "No stop found for the current filters."}), 404

        stop_data = format_stop_data(random_stop, include_routes=False)

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


@search_bp.route('/api/lookup', methods=['GET'])
@limiter.limit("60/minute")
def lookup():
    """The public lookup: every match of a stop. See documentation/2.10 Public API.md."""
    try:
        query = parse_lookup(request.args)
    except InvalidLookup as error:
        return jsonify({"error": f"{error} See /docs/public_api."}), 400
    try:
        return jsonify(lookup_payload(query))
    except SQLAlchemyError:
        app.logger.warning("Lookup failed", exc_info=True)
        response = jsonify({"error": "The database is busy or unavailable, for example during a data update. Retry in a minute."})
        response.headers['Retry-After'] = '60'
        return response, 503


@search_bp.route('/api/search/suggest', methods=['GET'])
@limiter.limit("240/minute")
def search_suggest():
    """Stations and OSM elements whose name or number matches q, for the search box."""
    query = request.args.get('q', '')
    if len(query) > 100:
        return jsonify({"error": "q is longer than 100 characters."}), 400
    try:
        limit = min(max(int(request.args.get('limit', stop_suggest.DEFAULT_LIMIT)), 1), stop_suggest.MAX_LIMIT)
    except ValueError:
        return jsonify({"error": "limit must be a number."}), 400
    try:
        return jsonify({"query": query, "results": stop_suggest.suggest(query, limit)})
    except SQLAlchemyError:
        app.logger.warning("Search suggestions failed", exc_info=True)
        db.session.rollback()
        response = jsonify({"error": "The database is busy or unavailable, for example during a data update. Retry in a minute."})
        response.headers['Retry-After'] = '60'
        return response, 503


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
            stop = optimize_query_for_endpoint(StopsMatched.query, 'search').filter(StopsMatched.sloid == identifier).first()
            if stop:
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
        elif identifier_type in ('osm', 'osm_node_id'):
            stop = optimize_query_for_endpoint(StopsMatched.query, 'search').filter(StopsMatched.osm_node_id == identifier).first()
            if stop:
                lat_col_name = 'osm_lat'
                lon_col_name = 'osm_lon'
                popup_view_type = 'osm'
        elif identifier_type == 'station':
            stop = optimize_query_for_endpoint(StopsMatched.query, 'search').join(
                AtlasStop, StopsMatched.sloid == AtlasStop.sloid
            ).filter(AtlasStop.uic_ref == identifier).first()
            if stop:
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
        elif identifier_type == 'route':
            route_stops = get_stops_for_route(identifier)
            atlas_sloids = route_stops.get('atlas_sloids', [])
            osm_nodes = route_stops.get('osm_nodes', [])

            if atlas_sloids:
                stop = optimize_query_for_endpoint(StopsMatched.query, 'search').filter(StopsMatched.sloid.in_(atlas_sloids)).first()
                lat_col_name = 'atlas_lat'
                lon_col_name = 'atlas_lon'
                popup_view_type = 'atlas'
            elif osm_nodes:
                stop = optimize_query_for_endpoint(StopsMatched.query, 'search').filter(StopsMatched.osm_node_id.in_(osm_nodes)).first()
                if stop:
                    lat_col_name = 'osm_lat'
                    lon_col_name = 'osm_lon'
                    popup_view_type = 'osm'
        else:
            return jsonify({"error": "Invalid identifier_type"}), 400
        if stop:
            stop_data = format_stop_data(stop, include_routes=True, include_osm_tags=True)
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


