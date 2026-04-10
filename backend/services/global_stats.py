from sqlalchemy import case, func

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.models import GlobalStatsFilterRow, OsmStopMember, StopsMatched
from backend.queries.helpers import (
    build_atlas_duplicate_membership_condition,
    build_stop_scope_condition,
    get_query_builder,
    parse_filter_params,
    resolve_stop_type_match_filters,
)


_TRANSPORT_COLUMN_MAP = {
    'ferry_terminal': GlobalStatsFilterRow.is_ferry_terminal,
    'tram_stop': GlobalStatsFilterRow.is_tram_stop,
    'station': GlobalStatsFilterRow.is_station,
    'platform': GlobalStatsFilterRow.is_platform,
    'stop_position': GlobalStatsFilterRow.is_stop_position,
    'aerialway_station': GlobalStatsFilterRow.is_aerialway_station,
}


def _parse_positive_int(value):
    if value is None:
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _is_grouped_osm_condition(model):
    return model.stop_kind.in_(['pair', 'trio'])


def _can_use_materialized_filter_rows(args):
    """Return True when request is a broad filter request (not identifier search/top-N)."""
    filters = parse_filter_params(args)

    # Smart-search identifiers and route lookups require canonical source-table filtering.
    if filters.get('filter_values'):
        return False

    # Top-N requires distance ordering and limiting from canonical source rows.
    if _parse_positive_int(args.get('top_n')):
        return False

    return True


def _apply_materialized_common_filters(query, filters):
    conditions = []

    if filters.get('transport_types'):
        transport_conditions = [
            _TRANSPORT_COLUMN_MAP[transport_type].is_(True)
            for transport_type in filters['transport_types']
            if transport_type in _TRANSPORT_COLUMN_MAP
        ]
        if transport_conditions:
            conditions.append(db.or_(*transport_conditions))

    if filters.get('node_types'):
        node_conditions = []
        if 'atlas' in filters['node_types']:
            node_conditions.append(GlobalStatsFilterRow.sloid.isnot(None))
        if 'osm' in filters['node_types']:
            node_conditions.append(GlobalStatsFilterRow.osm_node_id.isnot(None))
        if node_conditions:
            conditions.append(db.or_(*node_conditions) if len(node_conditions) > 1 else node_conditions[0])

    if filters.get('atlas_operators'):
        conditions.append(GlobalStatsFilterRow.atlas_operator.in_(filters['atlas_operators']))

    if 'osm_group_types' in filters:
        osm_group_types = filters.get('osm_group_types')
        if osm_group_types:
            conditions.append(GlobalStatsFilterRow.osm_group_kind.in_(osm_group_types))
        else:
            # osm_group_types=all maps to any pair/trio member.
            conditions.append(_is_grouped_osm_condition(GlobalStatsFilterRow))

    if conditions:
        query = query.filter(db.and_(*conditions))

    return query


def _build_scoped_global_stats_materialized_query(args):
    stop_filter_str = args.get('stop_filter', None)
    match_method_str = args.get('match_method', None)
    show_duplicates_only = args.get('show_duplicates_only', 'false').lower() == 'true'

    filters = parse_filter_params(args)
    query = _apply_materialized_common_filters(GlobalStatsFilterRow.query, filters)

    resolved_filters = resolve_stop_type_match_filters(stop_filter_str, match_method_str)
    scope_condition = build_stop_scope_condition(GlobalStatsFilterRow, resolved_filters)
    if scope_condition is not None:
        query = query.filter(scope_condition)

    if show_duplicates_only:
        query = query.filter(GlobalStatsFilterRow.atlas_duplicate.is_(True))

    return query


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


def _compute_global_stats_materialized(args, db_session) -> dict:
    """Compute global stats from `global_stats_filter_rows` for broad filter requests."""
    filtered = _build_scoped_global_stats_materialized_query(args).with_entities(
        GlobalStatsFilterRow.sloid.label('sloid'),
        GlobalStatsFilterRow.osm_node_id.label('osm_node_id'),
        GlobalStatsFilterRow.osm_stop_id.label('osm_stop_id'),
        GlobalStatsFilterRow.effective_stop_type.label('effective_stop_type'),
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
        func.count(func.distinct(filtered.c.osm_stop_id)).label('total_osm_stops'),
        func.count(
            func.distinct(
                case(
                    (filtered.c.effective_stop_type == 'matched', filtered.c.osm_stop_id),
                    else_=None,
                )
            )
        ).label('matched_osm_stops'),
        func.count(func.distinct(filtered.c.osm_node_id)).label('total_osm_nodes'),
    ).one()

    unmatched_osm_stops = max(0, (res.total_osm_stops or 0) - (res.matched_osm_stops or 0))
    return {
        'total_atlas_stops': int(res.total_atlas or 0),
        'matched_atlas_stops': int(res.matched_atlas or 0),
        'total_osm_stops': int(res.total_osm_stops or 0),
        'matched_osm_stops': int(res.matched_osm_stops or 0),
        'total_osm_nodes': int(res.total_osm_nodes or 0),
        'matched_osm_nodes': int(res.matched_pairs or 0),
        'matched_pairs_count': int(res.matched_pairs or 0),
        'unmatched_entities_count': int(res.unmatched_atlas or 0) + unmatched_osm_stops,
    }


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
    """Return global stats payload with fast-path routing for broad filter requests.

    Routing:
    - broad filter requests (no identifier search / no top-N) use materialized rows
    - search/top-N requests use canonical source-table SQL path
    """
    if _can_use_materialized_filter_rows(args):
        try:
            return _compute_global_stats_materialized(args, db_session)
        except Exception as exc:
            if not is_missing_table_error(exc):
                raise

    return _compute_global_stats_sql(args, db_session)
