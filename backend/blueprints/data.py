from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from backend.models import Stop, AtlasStop, OsmNode
from backend.extensions import db, limiter
from backend.serializers.stops import format_stop_data
from flask_login import current_user
from backend.services.routes import get_stops_for_route
import json

# Create blueprint for data operations
data_bp = Blueprint('data', __name__)

# ----------------------------
# API Endpoint: /api/operators
# ----------------------------
@data_bp.route('/api/operators', methods=['GET'])
@limiter.limit("60/minute")
def get_operators():
    try:
        operators = db.session.query(AtlasStop.atlas_business_org_abbr) \
            .filter(AtlasStop.atlas_business_org_abbr.isnot(None)) \
            .filter(AtlasStop.atlas_business_org_abbr != '') \
            .distinct() \
            .order_by(AtlasStop.atlas_business_org_abbr) \
            .all()
        operator_list = [op[0] for op in operators if op[0]]
        return jsonify({"operators": operator_list, "total": len(operator_list)})
    except Exception as e:
        app.logger.error(f"Error fetching operators: {str(e)}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/api/data', methods=['GET'])
@limiter.limit("30/minute")
def get_data():
    try:
        bbox = request.args.get('bbox')
        if bbox:
            bbox_parts = bbox.split(',')
            if len(bbox_parts) == 4:
                min_lat, min_lon, max_lat, max_lon = map(float, bbox_parts)
            else:
                raise ValueError("bbox parameter must have 4 values: min_lat,min_lon,max_lat,max_lon")
        else:
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

        offset_raw = request.args.get('offset', 0)
        limit_raw = request.args.get('limit')
        try:
            offset = int(offset_raw)
        except Exception:
            offset = 0
        # Treat missing/invalid/non-positive/"all" as no explicit limit
        limit = None
        if limit_raw is not None:
            if isinstance(limit_raw, str) and limit_raw.lower() == 'all':
                limit = None
            else:
                try:
                    limit_val = int(limit_raw)
                    if limit_val > 0:
                        limit = limit_val
                except Exception:
                    limit = None

        query = Stop.query
        all_category_conditions = []

        viewport_sargable = db.or_(
            db.and_(
                Stop.atlas_lat.isnot(None), Stop.atlas_lon.isnot(None),
                Stop.atlas_lat >= min_lat, Stop.atlas_lat <= max_lat,
                Stop.atlas_lon >= min_lon, Stop.atlas_lon <= max_lon
            ),
            db.and_(
                Stop.atlas_lat.is_(None), Stop.atlas_lon.is_(None),
                Stop.osm_lat.isnot(None), Stop.osm_lon.isnot(None),
                Stop.osm_lat >= min_lat, Stop.osm_lat <= max_lat,
                Stop.osm_lon >= min_lon, Stop.osm_lon <= max_lon
            )
        )
        all_category_conditions.append(viewport_sargable)

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

        if atlas_operator_filter_str:
            atlas_operators = [op.strip() for op in atlas_operator_filter_str.split(',') if op.strip()]
            if atlas_operators:
                operator_condition = Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                )
                all_category_conditions.append(operator_condition)

        if station_filter_str:
            filter_values = [val.strip() for val in station_filter_str.split(',') if val.strip()]
            filter_types = filter_types_str.split(',')
            route_directions = route_directions_str.split(',')
            while len(filter_types) < len(filter_values):
                filter_types.append('station')
            while len(route_directions) < len(filter_values):
                route_directions.append('')
            if filter_values:
                station_id_sub_conditions = []
                for i, value in enumerate(filter_values):
                    filter_type = filter_types[i].strip()
                    direction = route_directions[i].strip()
                    if filter_type == 'atlas':
                        station_id_sub_conditions.append(Stop.sloid.like(f'%{value}%'))
                    elif filter_type == 'osm':
                        station_id_sub_conditions.append(Stop.osm_node_id.like(f'%{value}%'))
                    elif filter_type == 'hrdf_route':
                        station_id_sub_conditions.append(Stop.atlas_stop_details.has(
                            func.json_search(AtlasStop.routes_unified, 'one', value, None, '$[*].line_name') != None
                        ))
                    elif filter_type == 'route':
                        route_stops = get_stops_for_route(value, direction if direction else None)
                        route_specific_conditions = []
                        if route_stops['atlas_sloids']:
                            route_specific_conditions.append(Stop.sloid.in_(route_stops['atlas_sloids']))
                        if route_stops['osm_nodes']:
                            route_specific_conditions.append(Stop.osm_node_id.in_(route_stops['osm_nodes']))
                        if route_specific_conditions:
                            station_id_sub_conditions.append(db.or_(*route_specific_conditions))
                    else:
                        station_id_sub_conditions.append(Stop.uic_ref.like(f'%{value}%'))
                if station_id_sub_conditions:
                    all_category_conditions.append(db.or_(*station_id_sub_conditions))

        stop_type_match_method_or_conditions = []
        current_stop_types = []
        if stop_filter_str and stop_filter_str.lower() != 'all':
            current_stop_types = [t.strip() for t in stop_filter_str.split(',') if t.strip()]
        current_match_methods = []
        if match_method_str:
            current_match_methods = [m.strip() for m in match_method_str.split(',') if m.strip()]

        if 'matched' in current_stop_types:
            relevant_matched_methods = []
            for method in current_match_methods:
                if method in ['exact', 'name', 'manual']:
                    relevant_matched_methods.append(method)
                elif method.startswith('distance_matching_'):
                    relevant_matched_methods.append(method)
                # Accept any route-based method token (e.g., route_gtfs, route_hrdf, route_unified_gtfs, ...)
                elif method.startswith('route_'):
                    relevant_matched_methods.append(method)
            if relevant_matched_methods:
                route_matching_conditions = []
                other_method_conditions = []
                for method in relevant_matched_methods:
                    if method.startswith('route_'):
                        # Match both legacy (route_gtfs/hrdf) and unified (route_unified_gtfs/hrdf) stored types
                        route_matching_conditions.append(Stop.match_type.like(f'{method}%'))
                        if not method.startswith('route_unified_'):
                            suffix = method[len('route_'):]
                            route_matching_conditions.append(Stop.match_type.like(f'route_unified_{suffix}%'))
                    elif method.startswith('distance_matching_'):
                        other_method_conditions.append(Stop.match_type.like(f'{method}%'))
                    else:
                        other_method_conditions.append(Stop.match_type == method)
                all_method_conditions = other_method_conditions + route_matching_conditions
                if all_method_conditions:
                    stop_type_match_method_or_conditions.append(
                        db.and_(Stop.stop_type == 'matched', db.or_(*all_method_conditions))
                    )
            else:
                if not current_match_methods:
                    stop_type_match_method_or_conditions.append(Stop.stop_type == 'matched')

        if 'unmatched' in current_stop_types:
            filter_for_no_osm_nearby = 'no_nearby_counterpart' in current_match_methods
            filter_for_osm_nearby = 'osm_within_50m' in current_match_methods
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

        if 'osm' in current_stop_types:
            stop_type_match_method_or_conditions.append(Stop.stop_type == 'osm')

        if stop_type_match_method_or_conditions:
            all_category_conditions.append(db.or_(*stop_type_match_method_or_conditions))
        elif current_stop_types and not stop_type_match_method_or_conditions:
            all_category_conditions.append(db.false())

        if all_category_conditions:
            query = query.filter(db.and_(*all_category_conditions))

        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        stops = query.all()

        regular_stops = []
        for stop in stops:
            lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
            lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
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
        return jsonify(regular_stops)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@data_bp.route('/api/route_stops', methods=['GET'])
@limiter.limit("60/minute")
def get_route_stops():
    route_id = request.args.get('route_id')
    direction = request.args.get('direction')
    if not route_id:
        return jsonify({'error': 'No route ID provided'}), 400
    stops = get_stops_for_route(route_id, direction)
    return jsonify(stops)


@data_bp.route('/api/stop_popup', methods=['GET'])
@limiter.limit("120/minute")
def get_stop_popup():
    try:
        stop_id = request.args.get('stop_id', type=int)
        view_type = request.args.get('view_type', type=str)
        if not stop_id:
            return jsonify({"error": "stop_id is required"}), 400
        stop = Stop.query.options(
            joinedload(Stop.atlas_stop_details),
            joinedload(Stop.osm_node_details)
        ).filter(Stop.id == stop_id).first()
        if not stop:
            return jsonify({"error": "Stop not found"}), 404
        enriched = format_stop_data(stop, include_routes=True, include_notes=True)
        # Include attribution for notes if present
        if stop.atlas_stop_details:
            enriched['atlas_note_author_email'] = stop.atlas_stop_details.atlas_note_user_email
        if stop.osm_node_details:
            enriched['osm_note_author_email'] = stop.osm_node_details.osm_note_user_email
        if stop.stop_type == 'matched' and stop.sloid:
            matched_rows = Stop.query.options(
                joinedload(Stop.osm_node_details),
                joinedload(Stop.atlas_stop_details)
            ).filter(Stop.sloid == stop.sloid, Stop.stop_type == 'matched').all()
            atlas_lat = stop.atlas_lat
            atlas_lon = stop.atlas_lon
            if atlas_lat is None or atlas_lon is None:
                for r in matched_rows:
                    if r.atlas_lat is not None and r.atlas_lon is not None:
                        atlas_lat, atlas_lon = r.atlas_lat, r.atlas_lon
                        break
            enriched["atlas_lat"] = atlas_lat
            enriched["atlas_lon"] = atlas_lon
            osm_matches = []
            for r in matched_rows:
                if r.osm_node_id and r.osm_lat is not None and r.osm_lon is not None:
                    osm_details = r.osm_node_details
                    osm_matches.append({
                        "osm_id": r.id,
                        "osm_node_id": r.osm_node_id,
                        "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
                        "osm_network": osm_details.osm_network if osm_details else None,
                        "osm_operator": osm_details.osm_operator if osm_details else None,
                        "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
                        "osm_railway": osm_details.osm_railway if osm_details else None,
                        "osm_amenity": osm_details.osm_amenity if osm_details else None,
                        "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
                        "osm_name": osm_details.osm_name if osm_details else None,
                        "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
                        "osm_uic_ref": osm_details.osm_uic_ref if osm_details else None,
                        "osm_lat": r.osm_lat,
                        "osm_lon": r.osm_lon,
                        "distance_m": r.distance_m,
                        "routes_osm": osm_details.routes_osm if osm_details else None,
                        "match_type": r.match_type,
                        "atlas_duplicate_sloid": r.atlas_duplicate_sloid,
                        "osm_node_type": r.osm_node_type
                    })
            if osm_matches:
                enriched["osm_matches"] = osm_matches
        if view_type == 'osm' and stop.osm_node_id:
            same_osm_rows = Stop.query.options(
                joinedload(Stop.atlas_stop_details)
            ).filter(Stop.osm_node_id == stop.osm_node_id, Stop.stop_type == 'matched').all()
            if len(same_osm_rows) > 1:
                osm_details = stop.osm_node_details
                osm_centric = {
                    "id": stop.id,
                    "stop_type": 'matched',
                    "is_osm_node": True,
                    "osm_node_id": stop.osm_node_id,
                    "osm_name": osm_details.osm_name if osm_details else None,
                    "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
                    "osm_uic_ref": osm_details.osm_uic_ref if osm_details else None,
                    "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
                    "osm_network": osm_details.osm_network if osm_details else None,
                    "osm_operator": osm_details.osm_operator if osm_details else None,
                    "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
                    "osm_amenity": osm_details.osm_amenity if osm_details else None,
                    "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
                    "osm_railway": osm_details.osm_railway if osm_details else None,
                    "osm_lat": stop.osm_lat,
                    "osm_lon": stop.osm_lon,
                    "osm_node_type": stop.osm_node_type,
                    "uic_ref": stop.uic_ref,
                    "routes_osm": osm_details.routes_osm if osm_details else None,
                    "atlas_matches": []
                }
                for r in same_osm_rows:
                    atlas = r.atlas_stop_details
                    osm_centric["atlas_matches"].append({
                        "id": r.id,
                        "sloid": r.sloid,
                        "uic_ref": r.uic_ref,
                        "atlas_designation": atlas.atlas_designation if atlas else None,
                        "atlas_designation_official": atlas.atlas_designation_official if atlas else None,
                        "atlas_business_org_abbr": atlas.atlas_business_org_abbr if atlas else None,
                        "atlas_lat": r.atlas_lat,
                        "atlas_lon": r.atlas_lon,
                        "distance_m": r.distance_m,
                        "match_type": r.match_type,
                        "routes_unified": getattr(atlas, 'routes_unified', None) if atlas else None
                    })
                return jsonify({"stop": osm_centric})
        return jsonify({"stop": enriched})
    except Exception as e:
        app.logger.error(f"Error fetching stop popup: {e}")
        return jsonify({"error": str(e)}), 500


