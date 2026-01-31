from backend.extensions import db
from backend.query_builder import QueryBuilder
from functools import lru_cache

_query_builder_instance = None


def get_query_builder():
    global _query_builder_instance
    if _query_builder_instance is None:
        _query_builder_instance = QueryBuilder(db.session)
    return _query_builder_instance


def parse_filter_params(request_args):
    filters = {}
    transport_types_str = request_args.get('transport_types')
    if transport_types_str:
        filters['transport_types'] = [t.strip() for t in transport_types_str.split(',') if t.strip()]
    node_type_str = request_args.get('node_type')
    if node_type_str and node_type_str.lower() != 'all':
        filters['node_types'] = [nt.strip() for nt in node_type_str.split(',') if nt.strip()]
    atlas_operator_str = request_args.get('atlas_operator')
    if atlas_operator_str:
        filters['atlas_operators'] = [op.strip() for op in atlas_operator_str.split(',') if op.strip()]
    station_filter_str = request_args.get('station_filter')
    if station_filter_str:
        filters['filter_values'] = [val.strip() for val in station_filter_str.split(',') if val.strip()]
        filter_types_str = request_args.get('filter_types', '')
        route_directions_str = request_args.get('route_directions', '')
        filters['filter_types'] = [ft.strip() for ft in filter_types_str.split(',') if ft.strip()] if filter_types_str else []
        filters['route_directions'] = [rd.strip() for rd in route_directions_str.split(',') if rd.strip()] if route_directions_str else []
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
    from backend.models import Stop
    options = []
    if config['atlas']:
        options.append(joinedload(Stop.atlas_stop_details))
    if config['osm']:
        options.append(joinedload(Stop.osm_node_details))
    if options:
        query = query.options(*options)
    return query


