from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import func, case
from sqlalchemy.orm import aliased
from backend.models import StopsMatched, AtlasStop, OsmTrio
from backend.extensions import db, limiter
from backend.query_helpers import get_query_builder, parse_filter_params, resolve_stop_type_match_filters, build_stop_scope_condition
from collections import OrderedDict
import threading

stats_bp = Blueprint('stats', __name__)


def _build_trio_middle_with_matched_side_condition(stop_model):
    matched_side = aliased(StopsMatched)
    matched_side_exists = db.select(1).select_from(matched_side).where(
        matched_side.stop_type == 'matched',
        db.or_(
            matched_side.osm_node_id == OsmTrio.side_node_id_1,
            matched_side.osm_node_id == OsmTrio.side_node_id_2,
        )
    ).exists()

    trio_middle_exists = db.select(1).select_from(OsmTrio).where(
        OsmTrio.middle_node_id == stop_model.osm_node_id,
        matched_side_exists,
    ).exists()

    return db.and_(stop_model.stop_type == 'osm_unmatched', trio_middle_exists)

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
        trio_middle_matched_condition = _build_trio_middle_with_matched_side_condition(StopsMatched)
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
        total_atlas_expr = func.count(func.distinct(filtered.c.sloid))
        matched_atlas_expr = func.count(func.distinct(case((filtered.c.effective_stop_type == 'matched', filtered.c.sloid), else_=None)))
        unmatched_atlas_expr = func.count(func.distinct(case((filtered.c.effective_stop_type == 'atlas_unmatched', filtered.c.sloid), else_=None)))
        total_osm_expr = func.count(func.distinct(filtered.c.osm_node_id))
        matched_osm_expr = func.count(func.distinct(case((filtered.c.effective_stop_type == 'matched', filtered.c.osm_node_id), else_=None)))
        unmatched_osm_expr = func.count(func.distinct(case((filtered.c.effective_stop_type == 'osm_unmatched', filtered.c.osm_node_id), else_=None)))
        matched_pairs_count_expr = func.count(case((filtered.c.effective_stop_type == 'matched', 1), else_=None))
        res = db.session.query(
            total_atlas_expr.label('total_atlas'),
            matched_atlas_expr.label('matched_atlas'),
            unmatched_atlas_expr.label('unmatched_atlas'),
            total_osm_expr.label('total_osm'),
            matched_osm_expr.label('matched_osm'),
            unmatched_osm_expr.label('unmatched_osm'),
            matched_pairs_count_expr.label('matched_pairs')
        ).one()
        response_payload = {
            "total_atlas_stops": res.total_atlas,
            "matched_atlas_stops": res.matched_atlas,
            "total_osm_nodes": res.total_osm,
            "matched_osm_nodes": res.matched_osm,
            "matched_pairs_count": int(res.matched_pairs or 0),
            "unmatched_entities_count": (res.unmatched_atlas or 0) + (res.unmatched_osm or 0)
        }
        with _STATS_CACHE_LOCK:
            _STATS_CACHE[cache_key] = response_payload
            _STATS_CACHE.move_to_end(cache_key)
            if len(_STATS_CACHE) > _STATS_CACHE_MAX_SIZE:
                _STATS_CACHE.popitem(last=False)
        return jsonify(response_payload)
    except Exception as e:
        app.logger.error(f"Error in global_stats: {str(e)}")
        return jsonify({"error": str(e)}), 500


