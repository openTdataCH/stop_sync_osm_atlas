from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func, case
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode
from backend.app_data import format_stop_data
from backend.query_helpers import get_query_builder, parse_filter_params, optimize_query_for_endpoint
from collections import OrderedDict
import threading

# Create blueprint for statistics and problems
stats_bp = Blueprint('stats', __name__)

# In-memory LRU cache for global stats (stores last 10 results)
_STATS_CACHE_MAX_SIZE = 10
_STATS_CACHE = OrderedDict()  # key -> dict result
_STATS_CACHE_LOCK = threading.Lock()

def _canonicalize_list_param(value: str) -> str:
    if not value:
        return ''
    parts = [p.strip() for p in value.split(',') if p.strip()]
    parts.sort()
    return ','.join(parts)

def _build_stats_cache_key(args) -> tuple:
    # Normalize all relevant request args that influence stats
    stop_filter_str = _canonicalize_list_param(args.get('stop_filter'))
    match_method_str = _canonicalize_list_param(args.get('match_method'))
    station_filter_str = _canonicalize_list_param(args.get('station_filter'))
    filter_types_str = _canonicalize_list_param(args.get('filter_types'))
    route_directions_str = _canonicalize_list_param(args.get('route_directions'))
    transport_types_filter_str = _canonicalize_list_param(args.get('transport_types'))
    node_type_filter_str = _canonicalize_list_param(args.get('node_type'))
    show_duplicates_only = 'true' if (args.get('show_duplicates_only', 'false').lower() == 'true') else 'false'
    top_n = args.get('top_n') or ''
    return (
        stop_filter_str,
        match_method_str,
        station_filter_str,
        filter_types_str,
        route_directions_str,
        transport_types_filter_str,
        node_type_filter_str,
        top_n,
        show_duplicates_only,
    )

@stats_bp.route('/api/global_stats', methods=['GET'])
def get_global_stats():
    try:
        # Cache lookup
        cache_key = _build_stats_cache_key(request.args)
        with _STATS_CACHE_LOCK:
            if cache_key in _STATS_CACHE:
                # Move to end (MRU)
                _STATS_CACHE.move_to_end(cache_key)
                return jsonify(_STATS_CACHE[cache_key])

        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        station_filter_str = request.args.get('station_filter', None)
        filter_types_str = request.args.get('filter_types', None)
        route_directions_str = request.args.get('route_directions', None)
        transport_types_filter_str = request.args.get('transport_types', None)
        node_type_filter_str = request.args.get('node_type', None)
        show_duplicates_only = request.args.get('show_duplicates_only', 'false').lower() == 'true'
        top_n = request.args.get('top_n', None)

        # Parse common filter parameters using shared helper
        filters = parse_filter_params(request.args)
        
        # Extract active_node_types for later use in final calculations
        active_node_types = filters.get('node_types', [])
        
        # Build a lean base query (no eager loading for stats)
        query_builder = get_query_builder()
        base_query = query_builder.apply_common_filters(Stop.query, filters)
        
        all_category_conditions = []

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
                    m.startswith('route_')
                )
            ]
            if relevant_matched_methods:
                method_conditions = []
                for m in relevant_matched_methods:
                    if m.startswith('distance_matching_') or m.startswith('route_'):
                        method_conditions.append(Stop.match_type.like(f"{m}%"))
                    else:
                        method_conditions.append(Stop.match_type == m)
                stop_type_match_method_or_conditions_gs.append(
                    db.and_(Stop.stop_type == 'matched', db.or_(*method_conditions))
                )
            else:
                if not current_match_methods_gs:
                    stop_type_match_method_or_conditions_gs.append(Stop.stop_type == 'matched')

        # Handle 'unmatched' (ATLAS) stops
        if 'unmatched' in current_stop_types_gs:
            filter_for_no_osm_nearby = 'no_nearby_counterpart' in current_match_methods_gs
            filter_for_osm_nearby    = 'osm_within_50m' in current_match_methods_gs

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

        # If top_n is provided and we are in a matched context, reduce to top N by distance first
        if top_n:
            try:
                n_val = int(top_n)
            except Exception:
                n_val = None
            if n_val and n_val > 0:
                query = query.order_by(Stop.distance_m.desc()).limit(n_val)

        # Build a subquery of filtered rows
        filtered = query.with_entities(
            Stop.sloid.label('sloid'),
            Stop.osm_node_id.label('osm_node_id'),
            Stop.stop_type.label('stop_type')
        ).subquery('f')

        # Conditional distinct counts
        total_atlas_expr = func.count(func.distinct(filtered.c.sloid))
        matched_atlas_expr = func.count(func.distinct(case((filtered.c.stop_type == 'matched', filtered.c.sloid), else_=None)))
        unmatched_atlas_expr = func.count(func.distinct(case((filtered.c.stop_type.in_(['unmatched', 'station']), filtered.c.sloid), else_=None)))

        total_osm_expr = func.count(func.distinct(filtered.c.osm_node_id))
        matched_osm_expr = func.count(func.distinct(case((filtered.c.stop_type == 'matched', filtered.c.osm_node_id), else_=None)))
        unmatched_osm_expr = func.count(func.distinct(case((filtered.c.stop_type == 'osm', filtered.c.osm_node_id), else_=None)))

        matched_pairs_count_expr = func.count(case((filtered.c.stop_type == 'matched', 1), else_=None))

        res = db.session.query(
            total_atlas_expr.label('total_atlas'),
            matched_atlas_expr.label('matched_atlas'),
            unmatched_atlas_expr.label('unmatched_atlas'),
            total_osm_expr.label('total_osm'),
            matched_osm_expr.label('matched_osm'),
            unmatched_osm_expr.label('unmatched_osm'),
            matched_pairs_count_expr.label('matched_pairs')
        ).one()

        # Apply node_type visibility logic to final numbers
        if not active_node_types or ('atlas' in active_node_types and 'osm' in active_node_types):
            final_total_atlas = res.total_atlas
            final_matched_atlas = res.matched_atlas
            final_total_osm = res.total_osm
            final_matched_osm = res.matched_osm
            final_unmatched_entities = (res.unmatched_atlas or 0) + (res.unmatched_osm or 0)
        elif 'atlas' in active_node_types:
            final_total_atlas = res.total_atlas
            final_matched_atlas = res.matched_atlas
            final_total_osm = 0
            final_matched_osm = 0
            final_unmatched_entities = (res.unmatched_atlas or 0)
        else:  # osm only
            final_total_atlas = 0
            final_matched_atlas = 0
            final_total_osm = res.total_osm
            final_matched_osm = res.matched_osm
            final_unmatched_entities = (res.unmatched_osm or 0)

        # Build response once, store in cache, then return
        response_payload = {
            "total_atlas_stops": final_total_atlas,
            "matched_atlas_stops": final_matched_atlas,
            "total_osm_nodes": final_total_osm,
            "matched_osm_nodes": final_matched_osm,
            "matched_pairs_count": int(res.matched_pairs or 0),
            "unmatched_entities_count": final_unmatched_entities
        }
        with _STATS_CACHE_LOCK:
            _STATS_CACHE[cache_key] = response_payload
            _STATS_CACHE.move_to_end(cache_key)
            if len(_STATS_CACHE) > _STATS_CACHE_MAX_SIZE:
                _STATS_CACHE.popitem(last=False)
        return jsonify(response_payload)

    except Exception as e:
        app.logger.error(f"Error in global_stats: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc()) 
        return jsonify({"error": str(e)}), 500 