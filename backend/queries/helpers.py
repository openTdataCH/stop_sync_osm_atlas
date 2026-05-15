from backend.extensions import db
from backend.query_builder import QueryBuilder

_query_builder_instance = None


def get_query_builder():
    global _query_builder_instance
    if _query_builder_instance is None:
        _query_builder_instance = QueryBuilder(db.session)
    return _query_builder_instance


def normalize_stop_filter_values(stop_filter_values):
    normalized_values = []
    alias_map = {
        'unmatched': 'atlas_unmatched',
        'osm': 'osm_unmatched'
    }

    for value in stop_filter_values:
        normalized_value = alias_map.get(value, value)
        if normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    return normalized_values


def parse_match_method_values(match_method_str):
    if not match_method_str:
        return []

    return [value.strip() for value in match_method_str.split(',') if value.strip()]


def is_matched_method(value):
    return (
        value in ['exact', 'name'] or
        value.startswith('distance_matching_') or
        value.startswith('long_distance_group_proximity') or
        value.startswith('route_')
    )


def resolve_stop_type_match_filters(stop_filter_str, match_method_str):
    current_stop_types = []
    if stop_filter_str and stop_filter_str.lower() != 'all':
        current_stop_types = normalize_stop_filter_values([t.strip() for t in stop_filter_str.split(',') if t.strip()])

    current_match_methods = parse_match_method_values(match_method_str)
    matched_methods = [value for value in current_match_methods if is_matched_method(value)]

    unmatched_reason_filters = {
        'no_nearby_counterpart': 'no_nearby_counterpart' in current_match_methods,
        'osm_within_50m': 'osm_within_50m' in current_match_methods,
    }

    return {
        'current_stop_types': current_stop_types,
        'current_match_methods': current_match_methods,
        'matched_methods': matched_methods,
        'include_matched': 'matched' in current_stop_types or bool(matched_methods),
        'include_atlas_unmatched': (
            'atlas_unmatched' in current_stop_types or
            unmatched_reason_filters['no_nearby_counterpart'] or
            unmatched_reason_filters['osm_within_50m']
        ),
        'include_osm_unmatched': 'osm_unmatched' in current_stop_types,
        'unmatched_reason_filters': unmatched_reason_filters,
        'has_scope_filter': bool(current_stop_types) or bool(current_match_methods),
    }


def build_match_method_conditions(stop_model, matched_methods):
    if not matched_methods:
        return None

    method_conditions = []
    for method in matched_methods:
        if method.startswith('route_'):
            method_conditions.append(stop_model.match_type.like(f'{method}%'))
        elif method.startswith('long_distance_group_proximity'):
            method_conditions.append(stop_model.match_type.like(f'{method}%'))
        elif method.startswith('distance_matching_'):
            method_conditions.append(stop_model.match_type.like(f'{method}%'))
        else:
            method_conditions.append(stop_model.match_type == method)

    if not method_conditions:
        return None

    return db.or_(*method_conditions) if len(method_conditions) > 1 else method_conditions[0]


def build_trio_middle_with_matched_side_condition(stop_model):
    """Return condition for trio middle nodes whose trio has both sides matched.

    These rows are stored as ``effectively_matched`` in ``stops_matched`` and 
    should be treated as matched for filtering/statistics semantics.
    """
    return stop_model.stop_type == 'effectively_matched'


def build_atlas_unmatched_condition(stop_model, unmatched_reason_filters):
    filter_for_no_osm_nearby = unmatched_reason_filters['no_nearby_counterpart']
    filter_for_osm_nearby = unmatched_reason_filters['osm_within_50m']

    if filter_for_no_osm_nearby and not filter_for_osm_nearby:
        return db.and_(
            stop_model.stop_type == 'atlas_unmatched',
            stop_model.match_type == 'no_nearby_counterpart'
        )

    if not filter_for_no_osm_nearby and filter_for_osm_nearby:
        return db.and_(
            stop_model.stop_type == 'atlas_unmatched',
            db.or_(stop_model.match_type != 'no_nearby_counterpart', stop_model.match_type.is_(None))
        )

    return stop_model.stop_type == 'atlas_unmatched'


def build_atlas_duplicate_membership_condition():
    """Return AtlasStop condition for true duplicate-group membership.

    Duplicate ATLAS membership is defined structurally:
    - non-representative members have ``representative_sloid`` set
    - representative members are referenced by at least one sibling row

    This avoids relying on JSONB null semantics from ``duplicate_group_sloids``.
    """
    from sqlalchemy.orm import aliased
    from backend.models import AtlasStop

    sibling = aliased(AtlasStop)
    is_representative_with_siblings = db.select(1).select_from(sibling).where(
        sibling.representative_sloid == AtlasStop.sloid
    ).exists()

    return db.or_(
        AtlasStop.representative_sloid.isnot(None),
        is_representative_with_siblings,
    )


def build_stop_scope_condition(stop_model, resolved_filters):
    scope_conditions = []
    trio_middle_matched_condition = build_trio_middle_with_matched_side_condition(stop_model)

    if resolved_filters['include_matched']:
        matched_methods_condition = build_match_method_conditions(stop_model, resolved_filters['matched_methods'])
        if matched_methods_condition is not None:
            matched_scope = db.and_(stop_model.stop_type == 'matched', matched_methods_condition)
            if 'distance_matching_trio' in resolved_filters['matched_methods']:
                matched_scope = db.or_(matched_scope, trio_middle_matched_condition)
            scope_conditions.append(matched_scope)
        else:
            scope_conditions.append(db.or_(stop_model.stop_type == 'matched', trio_middle_matched_condition))

    if resolved_filters['include_atlas_unmatched']:
        scope_conditions.append(
            build_atlas_unmatched_condition(stop_model, resolved_filters['unmatched_reason_filters'])
        )

    if resolved_filters['include_osm_unmatched']:
        scope_conditions.append(stop_model.stop_type == 'osm_unmatched')

    if scope_conditions:
        return db.or_(*scope_conditions) if len(scope_conditions) > 1 else scope_conditions[0]

    if resolved_filters['has_scope_filter']:
        return db.false()

    return None


def parse_filter_params(request_args):
    filters = {}
    transport_types_str = request_args.get('transport_types')
    if transport_types_str:
        filters['transport_types'] = [t.strip() for t in transport_types_str.split(',') if t.strip()]
    osm_entity_types_str = request_args.get('osm_entity_types')
    if osm_entity_types_str:
        filters['osm_entity_types'] = [t.strip() for t in osm_entity_types_str.split(',') if t.strip()]
    node_type_str = request_args.get('node_type')
    if node_type_str and node_type_str.lower() != 'all':
        filters['node_types'] = [nt.strip() for nt in node_type_str.split(',') if nt.strip()]
    atlas_operator_str = request_args.get('atlas_operator')
    if atlas_operator_str:
        filters['atlas_operators'] = [op.strip() for op in atlas_operator_str.split(',') if op.strip()]
    osm_operator_str = request_args.get('osm_operator')
    if osm_operator_str:
        filters['osm_operators'] = [op.strip() for op in osm_operator_str.split(',') if op.strip()]
    station_filter_str = request_args.get('station_filter')
    if station_filter_str:
        filters['filter_values'] = [val.strip() for val in station_filter_str.split(',') if val.strip()]
        filter_types_str = request_args.get('filter_types', '')
        route_directions_str = request_args.get('route_directions', '')
        filters['filter_types'] = [ft.strip() for ft in filter_types_str.split(',') if ft.strip()] if filter_types_str else []
        filters['route_directions'] = [rd.strip() for rd in route_directions_str.split(',') if rd.strip()] if route_directions_str else []
    osm_group_types_str = request_args.get('osm_group_types')
    if osm_group_types_str is not None:
        normalized_group_types = [
            group_type.strip()
            for group_type in osm_group_types_str.split(',')
            if group_type.strip()
        ]
        if 'all' in normalized_group_types:
            filters['osm_group_types'] = []
        elif normalized_group_types:
            filters['osm_group_types'] = normalized_group_types
    return filters


def optimize_query_for_endpoint(query, endpoint_type):
    eager_load_config = {
        'stats': {'atlas': True, 'osm': False},
        'search': {'atlas': True, 'osm': True},
        'data': {'atlas': True, 'osm': True},
        'problems': {'atlas': True, 'osm': True},
        'reports': {'atlas': True, 'osm': False}
    }
    config = eager_load_config.get(endpoint_type, {'atlas': True, 'osm': True})
    from sqlalchemy.orm import joinedload
    from backend.models import StopsMatched
    options = []
    if config['atlas']:
        options.append(joinedload(StopsMatched.atlas_stop_details))
    if config['osm']:
        options.append(joinedload(StopsMatched.osm_node_details))
    if options:
        query = query.options(*options)
    return query


