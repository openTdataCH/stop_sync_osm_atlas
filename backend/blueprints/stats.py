from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func, case
from backend.models import StopsMatched, AtlasStop, OsmStopMember
from backend.extensions import db, limiter
from backend.db_errors import is_missing_table_error
from backend.query_helpers import (
    get_query_builder,
    parse_filter_params,
    resolve_stop_type_match_filters,
    build_stop_scope_condition,
    build_trio_middle_with_matched_side_condition,
)
from collections import OrderedDict
import threading

stats_bp = Blueprint('stats', __name__)

_STATS_CACHE_MAX_SIZE = 5
_STATS_CACHE = OrderedDict()
_STATS_CACHE_LOCK = threading.Lock()


def _canonicalize_list_param(value: str) -> str:
    if not value:
        return ''
    parts = [p.strip() for p in value.split(',') if p.strip()]
    parts.sort()
    return ','.join(parts)


def _canonicalize_station_filter_triples(args) -> tuple:
    station_values = [value.strip() for value in (args.get('station_filter') or '').split(',') if value.strip()]
    filter_types = [value.strip() for value in (args.get('filter_types') or '').split(',')] if args.get('filter_types') else []
    route_directions = [value.strip() for value in (args.get('route_directions') or '').split(',')] if args.get('route_directions') else []

    triples = []
    for index, station_value in enumerate(station_values):
        filter_type = filter_types[index] if index < len(filter_types) and filter_types[index] else 'station'
        route_direction = route_directions[index] if index < len(route_directions) else ''
        triples.append((station_value, filter_type, route_direction))

    triples.sort()
    return tuple(triples)


def _build_stats_cache_key(args) -> tuple:
    stop_filter_str = _canonicalize_list_param(args.get('stop_filter'))
    match_method_str = _canonicalize_list_param(args.get('match_method'))
    station_filter_triples = _canonicalize_station_filter_triples(args)
    transport_types_filter_str = _canonicalize_list_param(args.get('transport_types'))
    node_type_filter_str = _canonicalize_list_param(args.get('node_type'))
    atlas_operator_str = _canonicalize_list_param(args.get('atlas_operator'))
    osm_group_types = _canonicalize_list_param(args.get('osm_group_types'))
    show_duplicates_only = 'true' if (args.get('show_duplicates_only', 'false').lower() == 'true') else 'false'
    top_n = args.get('top_n') or ''
    return (
        stop_filter_str,
        match_method_str,
        station_filter_triples,
        transport_types_filter_str,
        node_type_filter_str,
        atlas_operator_str,
        osm_group_types,
        top_n,
        show_duplicates_only,
    )


@stats_bp.route('/api/global_stats', methods=['GET'])
@limiter.limit("30/minute")
def get_global_stats():
    try:
        cache_key = _build_stats_cache_key(request.args)
        with _STATS_CACHE_LOCK:
            if cache_key in _STATS_CACHE:
                _STATS_CACHE.move_to_end(cache_key)
                return jsonify(_STATS_CACHE[cache_key])

        stop_filter_str = request.args.get('stop_filter', None)
        match_method_str = request.args.get('match_method', None)
        show_duplicates_only = request.args.get('show_duplicates_only', 'false').lower() == 'true'
        top_n = request.args.get('top_n', None)

        filters = parse_filter_params(request.args)
        query_builder = get_query_builder()
        base_query = query_builder.apply_common_filters(StopsMatched.query, filters)

        resolved_filters = resolve_stop_type_match_filters(stop_filter_str, match_method_str)
        scope_condition = build_stop_scope_condition(StopsMatched, resolved_filters)
        if scope_condition is not None:
            query = base_query.filter(scope_condition)
        else:
            query = base_query
        if show_duplicates_only:
            query = query.filter(StopsMatched.atlas_stop_details.has(AtlasStop.duplicate_group_sloids.isnot(None)))
        if top_n:
            try:
                n_val = int(top_n)
            except Exception:
                n_val = None
            if n_val and n_val > 0:
                query = query.filter(
                    StopsMatched.stop_type == 'matched',
                    StopsMatched.distance_m.isnot(None)
                ).order_by(StopsMatched.distance_m.desc()).limit(n_val)
        trio_middle_matched_condition = build_trio_middle_with_matched_side_condition(StopsMatched)
        effective_stop_type = case(
            (
                db.or_(StopsMatched.stop_type == 'matched', trio_middle_matched_condition),
                'matched',
            ),
            else_=StopsMatched.stop_type,
        ).label('effective_stop_type')

        filtered = query.with_entities(
            StopsMatched.sloid.label('sloid'),
            StopsMatched.osm_node_id.label('osm_node_id'),
            effective_stop_type,
        ).subquery('f')

        filtered_osm = db.session.query(
            filtered.c.osm_node_id.label('osm_node_id'),
            filtered.c.effective_stop_type.label('effective_stop_type'),
        ).filter(filtered.c.osm_node_id.isnot(None)).subquery('filtered_osm')

        filtered_osm_stops = db.session.query(
            OsmStopMember.osm_stop_id.label('osm_stop_id'),
            filtered_osm.c.effective_stop_type.label('effective_stop_type'),
        ).join(
            filtered_osm,
            OsmStopMember.node_id == filtered_osm.c.osm_node_id,
        ).subquery('filtered_osm_stops')

        atlas_res = db.session.query(
            func.count(func.distinct(filtered.c.sloid)).label('total_atlas'),
            func.count(
                func.distinct(
                    case((filtered.c.effective_stop_type == 'matched', filtered.c.sloid), else_=None)
                )
            ).label('matched_atlas'),
            func.count(
                func.distinct(
                    case((filtered.c.effective_stop_type == 'atlas_unmatched', filtered.c.sloid), else_=None)
                )
            ).label('unmatched_atlas'),
            func.count(case((filtered.c.effective_stop_type == 'matched', 1), else_=None)).label('matched_pairs'),
        ).one()

        osm_res = db.session.query(
            func.count(func.distinct(filtered_osm_stops.c.osm_stop_id)).label('total_osm_stops'),
            func.count(
                func.distinct(
                    case(
                        (filtered_osm_stops.c.effective_stop_type == 'matched', filtered_osm_stops.c.osm_stop_id),
                        else_=None,
                    )
                )
            ).label('matched_osm_stops'),
            func.count(func.distinct(filtered_osm.c.osm_node_id)).label('total_osm_nodes'),
        ).one()

        unmatched_osm_stops = max(0, (osm_res.total_osm_stops or 0) - (osm_res.matched_osm_stops or 0))
        response_payload = {
            "total_atlas_stops": atlas_res.total_atlas,
            "matched_atlas_stops": atlas_res.matched_atlas,
            "total_osm_stops": osm_res.total_osm_stops,
            "matched_osm_stops": osm_res.matched_osm_stops,
            "total_osm_nodes": osm_res.total_osm_nodes,
            "matched_osm_nodes": int(atlas_res.matched_pairs or 0),
            "matched_pairs_count": int(atlas_res.matched_pairs or 0),
            "unmatched_entities_count": (atlas_res.unmatched_atlas or 0) + unmatched_osm_stops,
        }
        with _STATS_CACHE_LOCK:
            _STATS_CACHE[cache_key] = response_payload
            _STATS_CACHE.move_to_end(cache_key)
            if len(_STATS_CACHE) > _STATS_CACHE_MAX_SIZE:
                _STATS_CACHE.popitem(last=False)
        return jsonify(response_payload)
    except Exception as e:
        if is_missing_table_error(e):
            db.session.rollback()
            app.logger.warning("Global stats unavailable: matching tables are not initialized yet.")
            return jsonify({
                "total_atlas_stops": 0,
                "matched_atlas_stops": 0,
                "total_osm_stops": 0,
                "matched_osm_stops": 0,
                "total_osm_nodes": 0,
                "matched_osm_nodes": 0,
                "matched_pairs_count": 0,
                "unmatched_entities_count": 0,
            }), 200
        app.logger.error(f"Error in global_stats: {str(e)}")
        return jsonify({"error": str(e)}), 500


@stats_bp.route('/api/download_stats_summary_pdf', methods=['GET'])
def download_stats_summary_pdf():
    """Download the pregenerated statistics summary report."""
    import os
    from flask import send_file
    
    pdf_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'documentation', 'generated', 'stats_summary.pdf'
    )
    
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Stats summary report has not been generated yet."}), 404
        
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='stats_summary.pdf'
    )


