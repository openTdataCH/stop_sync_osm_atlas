import json

from backend.extensions import db
from backend.query_builder import QueryBuilder
from backend.services.matching_rules import match_types_for_filter
from backend.services.problem_filters import parse_priorities, parse_problem_types

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
    return bool(match_types_for_filter(value))


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
        'include_osm_disused': 'osm_disused' in current_stop_types,
        'unmatched_reason_filters': unmatched_reason_filters,
        'has_scope_filter': bool(current_stop_types) or bool(current_match_methods),
    }


def build_match_method_conditions(stop_model, matched_methods):
    if not matched_methods:
        return None

    match_types = sorted({match_type for method in matched_methods for match_type in match_types_for_filter(method)})
    if not match_types:
        return None
    return stop_model.match_type.in_(match_types)


def build_two_sided_middle_with_matched_sides_condition(stop_model):
    """Return condition for two-sided stop middles whose two sides are both matched.

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
    two_sided_middle_matched_condition = build_two_sided_middle_with_matched_sides_condition(stop_model)

    if resolved_filters['include_matched']:
        matched_methods_condition = build_match_method_conditions(stop_model, resolved_filters['matched_methods'])
        if matched_methods_condition is not None:
            matched_scope = db.and_(stop_model.stop_type == 'matched', matched_methods_condition)
            if any('uic_two_sided_stop' in match_types_for_filter(method) for method in resolved_filters['matched_methods']):
                matched_scope = db.or_(matched_scope, two_sided_middle_matched_condition)
            scope_conditions.append(matched_scope)
        else:
            scope_conditions.append(db.or_(stop_model.stop_type == 'matched', two_sided_middle_matched_condition))

    if resolved_filters['include_atlas_unmatched']:
        scope_conditions.append(
            build_atlas_unmatched_condition(stop_model, resolved_filters['unmatched_reason_filters'])
        )

    if resolved_filters['include_osm_unmatched']:
        scope_conditions.append(stop_model.stop_type == 'osm_unmatched')

    if resolved_filters['include_osm_disused']:
        scope_conditions.append(stop_model.stop_type == 'osm_disused')

    if scope_conditions:
        return db.or_(*scope_conditions) if len(scope_conditions) > 1 else scope_conditions[0]

    if resolved_filters['has_scope_filter']:
        return db.false()

    return None


def parse_route_variants(text, count):
    """Variant selections of the route filters, one per filter value.

    ``text`` is a JSON list aligned with ``station_filter``: ``null`` keeps the
    whole route, ``{"atlas": key, "osm": key}`` narrows it to those variants
    (keys as in the routes page's ``atlas_variant``/``osm_variant``). Commas in
    ATLAS headsigns rule out the comma lists of the other parameters. Malformed
    input narrows to nothing rather than widening to the whole route.
    """
    if not text:
        return [None] * count
    nothing = {'atlas': None, 'osm': None}
    try:
        entries = json.loads(text)
    except ValueError:
        return [nothing] * count
    if not isinstance(entries, list):
        return [nothing] * count
    variants = []
    for entry in (entries + [None] * count)[:count]:
        if entry is None:
            variants.append(None)
        elif isinstance(entry, dict):
            variants.append({source: entry.get(source) if isinstance(entry.get(source), str) else None
                             for source in ('atlas', 'osm')})
        else:
            variants.append(nothing)
    return variants


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
    if request_args.get('missing_osm_operator_wikidata', '').lower() == 'true':
        filters['missing_osm_operator_wikidata'] = True
    wikidata_str = request_args.get('osm_operator_wikidata')
    if wikidata_str:
        filters['osm_operator_wikidata'] = [value.strip() for value in wikidata_str.split(',') if value.strip()]
    station_filter_str = request_args.get('station_filter')
    if station_filter_str:
        filters['filter_values'] = [val.strip() for val in station_filter_str.split(',') if val.strip()]
        filter_types_str = request_args.get('filter_types', '')
        route_directions_str = request_args.get('route_directions', '')
        filters['filter_types'] = [ft.strip() for ft in filter_types_str.split(',') if ft.strip()] if filter_types_str else []
        # Positional, like the filter values: "" is "both directions", so empty entries stay.
        filters['route_directions'] = [rd.strip() for rd in route_directions_str.split(',')] if route_directions_str else []
        filters['route_variants'] = parse_route_variants(request_args.get('route_variants'), len(filters['filter_values']))
    # problem_type=all (or a list) and/or priority keep entries with such a problem.
    if request_args.get('problem_type') or request_args.get('priority'):
        filters['problem_types'] = parse_problem_types(request_args.get('problem_type'))
        filters['problem_priorities'] = parse_priorities(request_args.get('priority'))
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


