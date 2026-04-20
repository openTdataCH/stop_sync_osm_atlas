from sqlalchemy import case, func

from backend.extensions import db
from backend.models import OsmStopMember, StopsMatched
from backend.queries.helpers import (
    build_atlas_duplicate_membership_condition,
    build_stop_scope_condition,
    get_query_builder,
    parse_filter_params,
    resolve_stop_type_match_filters,
)


def _build_scoped_global_stats_query(args):
    stop_filter_str = args.get('stop_filter', None)
    match_method_str = args.get('match_method', None)
    show_duplicates_only = args.get('show_duplicates_only', 'false').lower() == 'true'
    top_n = args.get('top_n', None)

    filters = parse_filter_params(args)
    query_builder = get_query_builder()
    base_query = query_builder.apply_common_filters(StopsMatched.query, filters)

    resolved_filters = resolve_stop_type_match_filters(stop_filter_str, match_method_str)
    scope_condition = build_stop_scope_condition(StopsMatched, resolved_filters)
    query = base_query.filter(scope_condition) if scope_condition is not None else base_query

    if show_duplicates_only:
        duplicate_condition = build_atlas_duplicate_membership_condition()
        query = query.filter(StopsMatched.atlas_stop_details.has(duplicate_condition))

    if top_n:
        try:
            n_val = int(top_n)
        except Exception:
            n_val = None
        if n_val and n_val > 0:
            query = query.filter(
                StopsMatched.stop_type == 'matched',
                StopsMatched.distance_m.isnot(None),
            ).order_by(StopsMatched.distance_m.desc()).limit(n_val)

    return query


def _build_effective_stop_type():
    return case(
        (
            db.or_(StopsMatched.stop_type == 'matched', StopsMatched.stop_type == 'effectively_matched'),
            'matched',
        ),
        else_=StopsMatched.stop_type,
    ).label('effective_stop_type')


def _compute_global_stats_sql(args, db_session) -> dict:
    """Compute global stats directly from StopsMatched with shared filter semantics."""
    query = _build_scoped_global_stats_query(args)
    effective_stop_type = _build_effective_stop_type()

    filtered = query.with_entities(
        StopsMatched.sloid.label('sloid'),
        StopsMatched.osm_node_id.label('osm_node_id'),
        effective_stop_type,
    ).subquery('f')

    res = db_session.query(
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
        func.count(func.distinct(OsmStopMember.osm_stop_id)).label('total_osm_stops'),
        func.count(
            func.distinct(
                case(
                    (filtered.c.effective_stop_type == 'matched', OsmStopMember.osm_stop_id),
                    else_=None,
                )
            )
        ).label('matched_osm_stops'),
        func.count(func.distinct(filtered.c.osm_node_id)).label('total_osm_nodes'),
    ).outerjoin(
        OsmStopMember,
        OsmStopMember.node_id == filtered.c.osm_node_id,
    ).one()

    unmatched_osm_stops = max(0, (res.total_osm_stops or 0) - (res.matched_osm_stops or 0))
    return {
        'total_atlas_stops': res.total_atlas,
        'matched_atlas_stops': res.matched_atlas,
        'total_osm_stops': res.total_osm_stops,
        'matched_osm_stops': res.matched_osm_stops,
        'total_osm_nodes': res.total_osm_nodes,
        'matched_osm_nodes': int(res.matched_pairs or 0),
        'matched_pairs_count': int(res.matched_pairs or 0),
        'unmatched_entities_count': (res.unmatched_atlas or 0) + unmatched_osm_stops,
    }


def compute_global_stats_payload(args, db_session) -> dict:
    """Return global stats using the canonical SQL path."""
    return _compute_global_stats_sql(args, db_session)
