from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func, case
from sqlalchemy.orm import joinedload, load_only
from collections import defaultdict
from backend.models import StopsMatched, AtlasStop, OsmNode, OsmStop, OsmStopMember
from backend.extensions import db, limiter
from backend.db_errors import is_missing_table_error
from backend.serializers.stops import format_stop_data
from backend.services.routes import get_stops_for_route, get_osm_routes_for_node, get_unified_routes_for_sloid
from backend.query_helpers import (
    build_atlas_duplicate_membership_condition,
    build_stop_scope_condition,
    resolve_stop_type_match_filters,
)
import json
from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope

# Create blueprint for data operations
data_bp = Blueprint('data', __name__)

def _parse_bbox_from_request_args(args):
    """
    Supports either:
      - bbox=min_lat,min_lon,max_lat,max_lon
      - or explicit min_lat/max_lat/min_lon/max_lon
    Returns (min_lat, min_lon, max_lat, max_lon) as floats.
    """
    bbox = args.get('bbox')
    if bbox:
        bbox_parts = bbox.split(',')
        if len(bbox_parts) != 4:
            raise ValueError("bbox parameter must have 4 values: min_lat,min_lon,max_lat,max_lon")
        min_lat, min_lon, max_lat, max_lon = map(float, bbox_parts)
        return min_lat, min_lon, max_lat, max_lon

    min_lat = float(args.get('min_lat'))
    max_lat = float(args.get('max_lat'))
    min_lon = float(args.get('min_lon'))
    max_lon = float(args.get('max_lon'))
    return min_lat, min_lon, max_lat, max_lon


def _build_filtered_stop_query(min_lat, min_lon, max_lat, max_lon, args):
    """
    Shared filter builder used by multiple endpoints.
    Mirrors the filtering semantics of /api/data.
    """
    stop_filter_str = args.get('stop_filter', None)
    match_method_str = args.get('match_method', None)
    station_filter_str = args.get('station_filter', None)
    filter_types_str = args.get('filter_types', '')
    route_directions_str = args.get('route_directions', '')
    transport_types_filter_str = args.get('transport_types', None)
    node_type_filter_str = args.get('node_type', None)
    atlas_operator_filter_str = args.get('atlas_operator', None)
    osm_group_types_filter_str = args.get('osm_group_types', None)
    show_duplicates_only = args.get('show_duplicates_only', 'false').lower() == 'true'

    query = StopsMatched.query
    all_category_conditions = []

    # Viewport filter: use indexed geometry column (ATLAS point) for fast bbox queries.
    # We also check osm_lat/osm_lon for matched stops to ensure they aren't hidden
    # if the viewport zooms strictly into the OSM node and the ATLAS node goes out of bounds.
    envelope = ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    spatial_condition = db.or_(
        ST_Intersects(StopsMatched.geom, envelope),
        db.and_(
            StopsMatched.stop_type == 'matched',
            StopsMatched.osm_lat >= min_lat, StopsMatched.osm_lat <= max_lat,
            StopsMatched.osm_lon >= min_lon, StopsMatched.osm_lon <= max_lon
        )
    )
    all_category_conditions.append(spatial_condition)

    if node_type_filter_str and node_type_filter_str.lower() != 'all':
        node_types = [nt.strip() for nt in node_type_filter_str.split(',') if nt.strip()]
        if node_types:
            node_type_or_conditions = []
            if 'atlas' in node_types:
                node_type_or_conditions.append(StopsMatched.sloid.isnot(None))
            if 'osm' in node_types:
                node_type_or_conditions.append(StopsMatched.osm_node_id.isnot(None))
            if node_type_or_conditions:
                all_category_conditions.append(
                    db.or_(*node_type_or_conditions) if len(node_type_or_conditions) > 1 else node_type_or_conditions[0]
                )

    osm_filter_conditions = []

    if transport_types_filter_str:
        selected_transport_types = [t.strip() for t in transport_types_filter_str.split(',') if t.strip()]
        if selected_transport_types:
            transport_sub_conditions = []
            if 'ferry_terminal' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_amenity == 'ferry_terminal'))
            if 'tram_stop' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_railway == 'tram_stop'))
            if 'station' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_node_type == 'railway_station'))
            if 'platform' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_public_transport == 'platform'))
            if 'stop_position' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_public_transport == 'stop_position'))
            if 'aerialway_station' in selected_transport_types:
                transport_sub_conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_aerialway == 'station'))
            if transport_sub_conditions:
                osm_filter_conditions.append(db.or_(*transport_sub_conditions))

    if atlas_operator_filter_str:
        atlas_operators = [op.strip() for op in atlas_operator_filter_str.split(',') if op.strip()]
        if atlas_operators:
            operator_condition = StopsMatched.atlas_stop_details.has(
                AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
            )
            all_category_conditions.append(operator_condition)

    if osm_group_types_filter_str is not None:
        legacy_map = {
            'osm_group_uic': 'osm_pair_uic',
            'osm_group_name': 'osm_pair_name',
            'osm_group_tram': 'osm_pair_tram',
            'osm_group_uic_equal': 'osm_pair_uic_equal_15m',
            'osm_group_name_equal': 'osm_pair_name_equal_15m',
            'osm_group_tram_equal': 'osm_pair_tram_equal_15m',
        }
        osm_group_types = [
            legacy_map.get(group_type.strip(), group_type.strip())
            for group_type in osm_group_types_filter_str.split(',')
            if group_type.strip() and group_type.strip() != 'all'
        ]
        include_pairs = True
        include_trios = True
        pair_types = []
        if osm_group_types:
            include_pairs = False
            include_trios = False
            pair_types = [t for t in osm_group_types if t.startswith('osm_pair_')]
            include_pairs = len(pair_types) > 0
            include_trios = 'osm_trio' in osm_group_types

        members_query = db.session.query(OsmStopMember.node_id).join(
            OsmStop,
            OsmStopMember.osm_stop_id == OsmStop.id,
        )

        if osm_group_types:
            group_conditions = []
            if include_pairs:
                group_conditions.append(
                    db.and_(
                        OsmStop.stop_kind == 'pair',
                        OsmStop.group_kind.in_(pair_types),
                    )
                )
            if include_trios:
                group_conditions.append(
                    db.and_(
                        OsmStop.stop_kind == 'trio',
                        OsmStop.group_kind == 'osm_trio',
                    )
                )
            if group_conditions:
                members_query = members_query.filter(db.or_(*group_conditions))
            else:
                members_query = members_query.filter(db.false())
        else:
            members_query = members_query.filter(OsmStop.stop_kind.in_(['pair', 'trio']))

        osm_filter_conditions.append(
            StopsMatched.osm_node_id.in_(
                members_query
            )
        )

    if osm_filter_conditions:
        combined_osm_condition = db.and_(*osm_filter_conditions)
        all_category_conditions.append(combined_osm_condition)

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
                    station_id_sub_conditions.append(StopsMatched.sloid.like(f'%{value}%'))
                elif filter_type == 'osm':
                    station_id_sub_conditions.append(StopsMatched.osm_node_id.like(f'%{value}%'))
                elif filter_type in ['hrdf_route', 'route']:
                    route_stops = get_stops_for_route(value, direction if direction else None)
                    route_specific_conditions = []
                    if route_stops['atlas_sloids']:
                        route_specific_conditions.append(StopsMatched.sloid.in_(route_stops['atlas_sloids']))
                    if route_stops['osm_nodes']:
                        route_specific_conditions.append(StopsMatched.osm_node_id.in_(route_stops['osm_nodes']))
                    if route_specific_conditions:
                        station_id_sub_conditions.append(db.or_(*route_specific_conditions))
                else:
                    station_id_sub_conditions.append(db.or_(
                        StopsMatched.atlas_stop_details.has(AtlasStop.uic_ref.ilike(f'%{value}%')),
                        StopsMatched.osm_node_details.has(OsmNode.osm_uic_ref.ilike(f'%{value}%'))
                    ))
            if station_id_sub_conditions:
                all_category_conditions.append(db.or_(*station_id_sub_conditions))
            else:
                all_category_conditions.append(db.false())

    resolved_filters = resolve_stop_type_match_filters(stop_filter_str, match_method_str)
    scope_condition = build_stop_scope_condition(StopsMatched, resolved_filters)
    if scope_condition is not None:
        all_category_conditions.append(scope_condition)

    if show_duplicates_only:
        duplicate_condition = build_atlas_duplicate_membership_condition()
        all_category_conditions.append(
            StopsMatched.atlas_stop_details.has(duplicate_condition)
        )

    if all_category_conditions:
        query = query.filter(db.and_(*all_category_conditions))

    return query

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
        if is_missing_table_error(e):
            db.session.rollback()
            app.logger.warning("Operators unavailable: atlas tables are not initialized yet.")
            return jsonify({"operators": [], "total": 0}), 200
        app.logger.error(f"Error fetching operators: {str(e)}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/api/data', methods=['GET'])
@limiter.limit("30/minute")
def get_data():
    try:
        min_lat, min_lon, max_lat, max_lon = _parse_bbox_from_request_args(request.args)

        include_meta_raw = request.args.get('include_meta', '')
        include_meta = str(include_meta_raw).strip().lower() in ('1', 'true', 'yes', 'y')

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

        query = _build_filtered_stop_query(min_lat, min_lon, max_lat, max_lon, request.args)
        # Eager-load only osm_node_type from osm_nodes to avoid N+1 queries
        # and defer matching_notes to keep the viewport query light.
        query = query.options(
            joinedload(StopsMatched.osm_node_details).load_only(OsmNode.osm_node_type),
            joinedload(StopsMatched.atlas_stop_details).load_only(AtlasStop.duplicate_group_sloids),
            db.defer(StopsMatched.matching_notes)
        )

        # If a limit is applied (mid/low zoom caps), ensure results are stable across requests
        # and prioritize unmatched rows first to reduce "disappearing/reappearing" markers.
        if limit is not None:
            stop_type_rank = case(
                (StopsMatched.stop_type == 'atlas_unmatched', 0),
                (StopsMatched.stop_type == 'osm_unmatched', 1),
                (StopsMatched.stop_type == 'effectively_matched', 2),
                (StopsMatched.stop_type == 'matched', 3),
                else_=9,
            )
            query = query.order_by(stop_type_rank.asc(), StopsMatched.id.asc())

        query = query.offset(offset)
        has_more = False
        if limit is not None:
            # Fetch one extra row so we can tell whether the response was capped.
            query = query.limit(limit + 1)
        stops = query.all()
        if limit is not None and len(stops) > limit:
            has_more = True
            stops = stops[:limit]

        regular_stops = []
        for stop in stops:
            lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
            lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
            regular_stops.append({
                "id": stop.id,
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "match_type": stop.match_type,
                "osm_node_id": stop.osm_node_id,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "osm_lat": stop.osm_lat,
                "osm_lon": stop.osm_lon,
                "distance_m": stop.distance_m,
                "lat": lat,
                "lon": lon,
                "has_atlas_duplicate": bool(stop.atlas_stop_details and stop.atlas_stop_details.duplicate_group_sloids),
                "osm_node_type": stop.osm_node_details.osm_node_type if stop.osm_node_details else None
            })
        # Enrich any OSM-backed stop with pair partners and trio links.
        osm_node_ids = [s['osm_node_id'] for s in regular_stops if s['osm_node_id']]
        if osm_node_ids:
            osm_node_set = set(osm_node_ids)

            stop_rows = db.session.query(
                OsmStopMember.node_id,
                OsmStopMember.osm_stop_id,
                OsmStop.stop_kind,
                OsmStop.group_kind,
            ).join(
                OsmStop,
                OsmStopMember.osm_stop_id == OsmStop.id,
            ).filter(
                OsmStopMember.node_id.in_(osm_node_ids),
            ).all()

            node_to_stop = {
                row.node_id: {
                    'osm_stop_id': row.osm_stop_id,
                    'stop_kind': row.stop_kind,
                    'group_kind': row.group_kind,
                }
                for row in stop_rows
            }
            stop_ids = {row.osm_stop_id for row in stop_rows}

            members_by_stop = defaultdict(list)
            if stop_ids:
                member_rows = db.session.query(
                    OsmStopMember.osm_stop_id,
                    OsmStopMember.node_id,
                    OsmStopMember.member_role,
                ).filter(
                    OsmStopMember.osm_stop_id.in_(stop_ids),
                ).all()
                for member_row in member_rows:
                    members_by_stop[member_row.osm_stop_id].append({
                        'node_id': member_row.node_id,
                        'member_role': member_row.member_role,
                    })

            # Build a coordinate lookup from viewport data first.
            osm_coords = {
                stop_entry['osm_node_id']: (stop_entry['osm_lat'], stop_entry['osm_lon'])
                for stop_entry in regular_stops
                if stop_entry['osm_node_id'] and stop_entry['osm_lat'] is not None
            }

            linked_node_ids = set()
            for stop_members in members_by_stop.values():
                for member in stop_members:
                    linked_node_ids.add(member['node_id'])

            missing_ids = [node_id for node_id in linked_node_ids if node_id not in osm_coords]
            if missing_ids:
                partner_rows = db.session.query(
                    StopsMatched.osm_node_id, StopsMatched.osm_lat, StopsMatched.osm_lon
                ).filter(
                    StopsMatched.osm_node_id.in_(missing_ids),
                    StopsMatched.osm_lat.isnot(None)
                ).distinct(StopsMatched.osm_node_id).all()
                for partner_row in partner_rows:
                    osm_coords[partner_row.osm_node_id] = (partner_row.osm_lat, partner_row.osm_lon)

            trio_side_ids = []
            for stop_id, stop_members in members_by_stop.items():
                if not stop_members:
                    continue
                stop_info = node_to_stop.get(stop_members[0]['node_id'])
                if stop_info and stop_info['stop_kind'] == 'trio':
                    trio_side_ids.extend([
                        member['node_id'] for member in stop_members if member['member_role'] == 'trio_side'
                    ])

            # matched_side_ids block removed; trio match state is handled by effectively_matched db value

            for stop_entry in regular_stops:
                node_id = stop_entry['osm_node_id']
                stop_info = node_to_stop.get(node_id)
                if not stop_info:
                    continue

                stop_members = members_by_stop.get(stop_info['osm_stop_id'], [])
                if stop_info['stop_kind'] == 'pair':
                    partner_ids = [member['node_id'] for member in stop_members if member['node_id'] != node_id]
                    if partner_ids:
                        partner_id = partner_ids[0]
                        partner_coords = osm_coords.get(partner_id, (None, None))
                        stop_entry['osm_group_partner'] = {
                            'partner_node_id': partner_id,
                            'group_type': stop_info['group_kind'],
                            'partner_osm_lat': partner_coords[0],
                            'partner_osm_lon': partner_coords[1],
                        }

                if stop_info['stop_kind'] == 'trio':
                    middle_member = next((member for member in stop_members if member['member_role'] == 'trio_middle'), None)
                    middle_node_id = middle_member['node_id'] if middle_member else None

                    links = []
                    for member in stop_members:
                        partner_id = member['node_id']
                        if partner_id == node_id:
                            continue
                        # Draw only middle-to-side links (no side-to-side edge).
                        if node_id != middle_node_id and partner_id != middle_node_id:
                            continue
                        partner_coords = osm_coords.get(partner_id, (None, None))
                        links.append({
                            'partner_node_id': partner_id,
                            'partner_osm_lat': partner_coords[0],
                            'partner_osm_lon': partner_coords[1],
                            'is_middle': node_id == middle_node_id,
                            'partner_is_middle': partner_id == middle_node_id,
                        })

                    if links:
                        stop_entry['osm_trio_links'] = links

                    stop_entry['is_trio_middle_matched'] = (
                        node_id == middle_node_id and stop_entry['stop_type'] == 'effectively_matched'
                    )

        if include_meta:
            return jsonify({
                "stops": regular_stops,
                "meta": {
                    "offset": offset,
                    "limit": limit,
                    "returned": len(regular_stops),
                    "has_more": has_more
                }
            })

        return jsonify(regular_stops)
    except Exception as e:
        if is_missing_table_error(e):
            db.session.rollback()
            include_meta_raw = request.args.get('include_meta', '')
            include_meta = str(include_meta_raw).strip().lower() in ('1', 'true', 'yes', 'y')
            app.logger.warning("Map data unavailable: matching tables are not initialized yet.")
            if include_meta:
                return jsonify({
                    "stops": [],
                    "meta": {
                        "offset": 0,
                        "limit": None,
                        "returned": 0,
                        "has_more": False
                    }
                }), 200
            return jsonify([]), 200
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
        stop = StopsMatched.query.options(
            joinedload(StopsMatched.atlas_stop_details),
            joinedload(StopsMatched.osm_node_details)
        ).filter(StopsMatched.id == stop_id).first()
        if not stop:
            return jsonify({"error": "StopsMatched not found"}), 404
        enriched = format_stop_data(stop, include_routes=True)
        if stop.stop_type == 'matched' and stop.sloid:
            matched_rows = StopsMatched.query.options(
                joinedload(StopsMatched.osm_node_details),
                joinedload(StopsMatched.atlas_stop_details)
            ).filter(StopsMatched.sloid == stop.sloid, StopsMatched.stop_type == 'matched').all()
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
                        "match_type": r.match_type,
                        "matching_notes": r.matching_notes,
                        "has_osm_duplicate": bool(osm_details and osm_details.duplicate_group_node_ids),
                        "osm_node_type": osm_details.osm_node_type if osm_details else None,
                        "routes_osm": get_osm_routes_for_node(r.osm_node_id),
                    })
            if osm_matches:
                enriched["osm_matches"] = osm_matches
            # Include OSM pair/trio partner data from stop-unit membership.
            if stop.osm_node_id:
                member_row = db.session.query(
                    OsmStopMember.osm_stop_id,
                    OsmStop.stop_kind,
                    OsmStop.group_kind,
                ).join(
                    OsmStop,
                    OsmStopMember.osm_stop_id == OsmStop.id,
                ).filter(
                    OsmStopMember.node_id == stop.osm_node_id,
                ).first()

                if member_row:
                    stop_members = db.session.query(
                        OsmStopMember.node_id,
                        OsmStopMember.member_role,
                    ).filter(
                        OsmStopMember.osm_stop_id == member_row.osm_stop_id,
                    ).all()

                    if member_row.stop_kind == 'pair':
                        partner_id = next((member.node_id for member in stop_members if member.node_id != stop.osm_node_id), None)
                        if partner_id:
                            partner_osm = OsmNode.query.get(partner_id)
                            partner_coords = db.session.query(
                                StopsMatched.osm_lat, StopsMatched.osm_lon
                            ).filter(
                                StopsMatched.osm_node_id == partner_id,
                                StopsMatched.osm_lat.isnot(None)
                            ).first()
                            enriched["osm_group_partner"] = {
                                'partner_node_id': partner_id,
                                'group_type': member_row.group_kind,
                                'osm_name': partner_osm.osm_name if partner_osm else None,
                                'osm_public_transport': partner_osm.osm_public_transport if partner_osm else None,
                                'osm_uic_ref': partner_osm.osm_uic_ref if partner_osm else None,
                                'partner_osm_lat': partner_coords.osm_lat if partner_coords else None,
                                'partner_osm_lon': partner_coords.osm_lon if partner_coords else None,
                            }

                    if member_row.stop_kind == 'trio':
                        middle_id = next((member.node_id for member in stop_members if member.member_role == 'trio_middle'), None)
                        links = []
                        for member in stop_members:
                            partner_id = member.node_id
                            if partner_id == stop.osm_node_id:
                                continue
                            if stop.osm_node_id != middle_id and partner_id != middle_id:
                                continue
                            partner_coords = db.session.query(
                                StopsMatched.osm_lat, StopsMatched.osm_lon
                            ).filter(
                                StopsMatched.osm_node_id == partner_id,
                                StopsMatched.osm_lat.isnot(None)
                            ).first()
                            links.append({
                                'partner_node_id': partner_id,
                                'partner_osm_lat': partner_coords.osm_lat if partner_coords else None,
                                'partner_osm_lon': partner_coords.osm_lon if partner_coords else None,
                                'is_middle': stop.osm_node_id == middle_id,
                                'partner_is_middle': partner_id == middle_id,
                            })
                        enriched["osm_trio_links"] = links
        if view_type == 'osm' and stop.osm_node_id:
            same_osm_rows = StopsMatched.query.options(
                joinedload(StopsMatched.atlas_stop_details)
            ).filter(StopsMatched.osm_node_id == stop.osm_node_id, StopsMatched.stop_type == 'matched').all()
            if len(same_osm_rows) > 1:
                osm_details = stop.osm_node_details
                osm_centric = {
                    "id": stop.id,
                    "stop_type": 'matched',
                    "is_osm_node": True,
                    "match_type": stop.match_type,
                    "matching_notes": stop.matching_notes,
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
                    "osm_node_type": osm_details.osm_node_type if osm_details else None,
                    "uic_ref": osm_details.osm_uic_ref if osm_details else None,
                    "routes_osm": get_osm_routes_for_node(stop.osm_node_id),
                    "atlas_matches": []
                }
                for r in same_osm_rows:
                    atlas = r.atlas_stop_details
                    osm_centric["atlas_matches"].append({
                        "id": r.id,
                        "sloid": r.sloid,
                        "uic_ref": atlas.uic_ref if atlas else None,
                        "atlas_designation": atlas.atlas_designation if atlas else None,
                        "atlas_designation_official": atlas.atlas_designation_official if atlas else None,
                        "atlas_business_org_abbr": atlas.atlas_business_org_abbr if atlas else None,
                        "atlas_lat": r.atlas_lat,
                        "atlas_lon": r.atlas_lon,
                        "distance_m": r.distance_m,
                        "match_type": r.match_type,
                        "matching_notes": r.matching_notes,
                        "routes_unified": get_unified_routes_for_sloid(r.sloid) if r.sloid else [],
                    })
                return jsonify({"stop": osm_centric})
        return jsonify({"stop": enriched})
    except Exception as e:
        app.logger.error(f"Error fetching stop popup: {e}")
        return jsonify({"error": str(e)}), 500


