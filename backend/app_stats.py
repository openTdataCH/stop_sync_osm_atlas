from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode
from backend.app_data import format_stop_data, get_stops_for_route

# Create blueprint for statistics and problems
stats_bp = Blueprint('stats', __name__)

@stats_bp.route('/api/global_stats', methods=['GET'])
def get_global_stats():
    try:
        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        station_filter_str = request.args.get('station_filter', None)
        filter_types_str = request.args.get('filter_types', None)
        route_directions_str = request.args.get('route_directions', None)
        transport_types_filter_str = request.args.get('transport_types', None)
        node_type_filter_str = request.args.get('node_type', None)
        show_duplicates_only = request.args.get('show_duplicates_only', 'false').lower() == 'true'

        active_node_types = []
        if node_type_filter_str:
            active_node_types = [nt.strip() for nt in node_type_filter_str.split(',') if nt.strip()]

        base_query = Stop.query.options(
            joinedload(Stop.atlas_stop_details),
            joinedload(Stop.osm_node_details)
        )
        all_category_conditions = []

        # Node Type Filter
        if active_node_types:
            node_type_sub_conditions = []
            if 'atlas' in active_node_types and 'osm' not in active_node_types:
                 node_type_sub_conditions.append(Stop.sloid.isnot(None))
            elif 'osm' in active_node_types and 'atlas' not in active_node_types:
                 node_type_sub_conditions.append(Stop.osm_node_id.isnot(None))
            elif 'atlas' in active_node_types and 'osm' in active_node_types:
                node_type_sub_conditions.append(db.or_(Stop.sloid.isnot(None), Stop.osm_node_id.isnot(None)))
            if node_type_sub_conditions:
                 all_category_conditions.append(db.or_(*node_type_sub_conditions) if len(node_type_sub_conditions) > 1 else node_type_sub_conditions[0])
        
        # Transport Type Filter
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

        # Station/Node/Route ID Filter
        if station_filter_str:
            filter_values = [val.strip() for val in station_filter_str.split(',') if val.strip()]
            filter_types = [val.strip() for val in filter_types_str.split(',') if val.strip()] if filter_types_str else []
            route_directions = [val.strip() for val in route_directions_str.split(',') if val.strip()] if route_directions_str else []
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
                        route_stops_data = get_stops_for_route(value, direction if direction else None)
                        route_specific_conditions = []
                        if route_stops_data['atlas_sloids']: route_specific_conditions.append(Stop.sloid.in_(route_stops_data['atlas_sloids']))
                        if route_stops_data['osm_nodes']: route_specific_conditions.append(Stop.osm_node_id.in_(route_stops_data['osm_nodes']))
                        if route_specific_conditions: station_id_sub_conditions.append(db.or_(*route_specific_conditions) if len(route_specific_conditions) > 1 else route_specific_conditions[0])
                    else: station_id_sub_conditions.append(Stop.uic_ref.like(f'%{value}%'))
                if station_id_sub_conditions: 
                    all_category_conditions.append(db.or_(*station_id_sub_conditions) if len(station_id_sub_conditions) > 1 else station_id_sub_conditions[0])

        # Stop Type and Match Method Logic
        stop_type_match_method_or_conditions_gs = []
        
        current_stop_types_gs = []
        if stop_filter_str and stop_filter_str.lower() != 'all':
            current_stop_types_gs = [t.strip() for t in stop_filter_str.split(',') if t.strip()]

        current_match_methods_gs = []
        if match_method_str:
            current_match_methods_gs = [m.strip() for m in match_method_str.split(',') if m.strip()]

        # Handle 'matched' stops
        if 'matched' in current_stop_types_gs:
            relevant_matched_methods = [
                m for m in current_match_methods_gs if (
                    m in ['exact', 'name', 'manual'] or 
                    m.startswith('distance_matching_') or 
                    m.startswith('route_matching_')
                )
            ]
            if relevant_matched_methods:
                stop_type_match_method_or_conditions_gs.append(
                    db.and_(Stop.stop_type == 'matched', Stop.match_type.in_(relevant_matched_methods))
                )
            else:
                if not current_match_methods_gs:
                    stop_type_match_method_or_conditions_gs.append(Stop.stop_type == 'matched')

        # Handle 'unmatched' (ATLAS) stops
        if 'unmatched' in current_stop_types_gs:
            filter_for_no_osm_nearby = 'no_osm_within_50m' in current_match_methods_gs
            filter_for_osm_nearby    = 'osm_within_50m' in current_match_methods_gs

            unmatched_specific_condition = Stop.stop_type == 'unmatched'

            if filter_for_no_osm_nearby and not filter_for_osm_nearby:
                unmatched_specific_condition = db.and_(
                    Stop.stop_type == 'unmatched',
                    Stop.match_type == 'no_osm_within_50m'
                )
            elif not filter_for_no_osm_nearby and filter_for_osm_nearby:
                unmatched_specific_condition = db.and_(
                    Stop.stop_type == 'unmatched',
                    db.or_(Stop.match_type != 'no_osm_within_50m', Stop.match_type.is_(None))
                )
            
            stop_type_match_method_or_conditions_gs.append(db.or_(
                unmatched_specific_condition,
                Stop.stop_type == 'station'
            ))
        
        # Handle 'osm' (pure/standalone) stops
        if 'osm' in current_stop_types_gs:
            stop_type_match_method_or_conditions_gs.append(Stop.stop_type == 'osm')
        
        if stop_type_match_method_or_conditions_gs:
            all_category_conditions.append(db.or_(*stop_type_match_method_or_conditions_gs))
        elif current_stop_types_gs and not stop_type_match_method_or_conditions_gs:
             all_category_conditions.append(db.false())

        # Apply all collected conditions
        if all_category_conditions:
            query = base_query.filter(db.and_(*all_category_conditions))
        else: 
            query = base_query
        
        if show_duplicates_only:
            query = query.filter(Stop.atlas_duplicate_sloid.isnot(None)).filter(Stop.atlas_duplicate_sloid != '')

        all_relevant_stops = query.all()
        all_relevant_records = []
        for stop in all_relevant_stops:
            all_relevant_records.append({
                'sloid': stop.sloid,
                'osm_node_id': stop.osm_node_id,
                'stop_type': stop.stop_type,
                'match_type': stop.match_type,
                'atlas_duplicate_sloid': stop.atlas_duplicate_sloid,
                'atlas_business_org_abbr': stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details else None,
                'osm_operator': stop.osm_node_details.osm_operator if stop.osm_node_details else None
            })

        # Calculate Counts
        total_osm_nodes_set = set()
        matched_osm_nodes_set = set()
        unmatched_osm_nodes_set = set()
        total_atlas_stops_set = set()
        matched_atlas_stops_set = set()
        unmatched_atlas_stops_set = set()

        for rec in all_relevant_records:
            is_atlas_entity = bool(rec['sloid'])
            is_osm_entity = bool(rec['osm_node_id'])

            # ATLAS stats
            if is_atlas_entity:
                total_atlas_stops_set.add(rec['sloid'])
                if rec['stop_type'] == 'matched':
                    matched_atlas_stops_set.add(rec['sloid'])
                elif rec['stop_type'] in ['unmatched', 'station']:
                    unmatched_atlas_stops_set.add(rec['sloid'])
            
            # OSM stats
            if is_osm_entity:
                total_osm_nodes_set.add(rec['osm_node_id'])
                if rec['stop_type'] == 'matched':
                    matched_osm_nodes_set.add(rec['osm_node_id'])
                elif rec['stop_type'] == 'osm':
                    unmatched_osm_nodes_set.add(rec['osm_node_id'])

        matched_pairs_count = sum(1 for rec in all_relevant_records if rec['stop_type'] == 'matched')

        final_total_atlas = 0
        final_matched_atlas = 0
        final_total_osm = 0
        final_matched_osm = 0
        final_unmatched_entities = 0

        if not active_node_types or ('atlas' in active_node_types and 'osm' in active_node_types):
            final_total_atlas = len(total_atlas_stops_set)
            final_matched_atlas = len(matched_atlas_stops_set)
            final_total_osm = len(total_osm_nodes_set)
            final_matched_osm = len(matched_osm_nodes_set)
            final_unmatched_entities = len(unmatched_atlas_stops_set) + len(unmatched_osm_nodes_set)
        elif 'atlas' in active_node_types: 
            final_total_atlas = len(total_atlas_stops_set)
            final_matched_atlas = len(matched_atlas_stops_set)
            final_unmatched_entities = len(unmatched_atlas_stops_set)
        elif 'osm' in active_node_types: 
            final_total_osm = len(total_osm_nodes_set)
            final_matched_osm = len(matched_osm_nodes_set)
            final_unmatched_entities = len(unmatched_osm_nodes_set)

        return jsonify({
            "total_atlas_stops": final_total_atlas,
            "matched_atlas_stops": final_matched_atlas,
            "total_osm_nodes": final_total_osm,
            "matched_osm_nodes": final_matched_osm,
            "matched_pairs_count": matched_pairs_count, 
            "unmatched_entities_count": final_unmatched_entities
        })

    except Exception as e:
        app.logger.error(f"Error in global_stats: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc()) 
        return jsonify({"error": str(e)}), 500 