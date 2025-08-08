"""
Query helper functions and utilities for shared database operations.
This module provides common query patterns and caching to improve performance.
"""

from backend.models import db
from backend.query_builder import QueryBuilder
from functools import lru_cache


# Global QueryBuilder instance to avoid repeated instantiation
_query_builder_instance = None


def get_query_builder():
    """Get or create a singleton QueryBuilder instance."""
    global _query_builder_instance
    if _query_builder_instance is None:
        _query_builder_instance = QueryBuilder(db.session)
    return _query_builder_instance


def parse_filter_params(request_args):
    """
    Parse common filter parameters from request arguments.
    
    Args:
        request_args: Flask request.args object
    
    Returns:
        Dictionary of parsed filter parameters
    """
    filters = {}
    
    # Transport types
    transport_types_str = request_args.get('transport_types')
    if transport_types_str:
        filters['transport_types'] = [t.strip() for t in transport_types_str.split(',') if t.strip()]
    
    # Node types
    node_type_str = request_args.get('node_type')
    if node_type_str and node_type_str.lower() != 'all':
        filters['node_types'] = [nt.strip() for nt in node_type_str.split(',') if nt.strip()]
    
    # Atlas operators
    atlas_operator_str = request_args.get('atlas_operator')
    if atlas_operator_str:
        filters['atlas_operators'] = [op.strip() for op in atlas_operator_str.split(',') if op.strip()]
    
    # Station filter values
    station_filter_str = request_args.get('station_filter')
    if station_filter_str:
        filters['filter_values'] = [val.strip() for val in station_filter_str.split(',') if val.strip()]
        
        # Filter types and route directions
        filter_types_str = request_args.get('filter_types', '')
        route_directions_str = request_args.get('route_directions', '')
        
        filters['filter_types'] = [ft.strip() for ft in filter_types_str.split(',') if ft.strip()] if filter_types_str else []
        filters['route_directions'] = [rd.strip() for rd in route_directions_str.split(',') if rd.strip()] if route_directions_str else []
    
    return filters


@lru_cache(maxsize=128)
def get_cached_route_stops(route_id, direction=None):
    """
    Get route stops with caching to improve performance for repeated route queries.
    
    Args:
        route_id: The route ID
        direction: Optional direction
    
    Returns:
        Dictionary with route stops data
    """
    from backend.app_data import get_stops_for_route
    return get_stops_for_route(route_id, direction)


def build_pagination_info(page, limit, total_count):
    """
    Build pagination information for API responses.
    
    Args:
        page: Current page number
        limit: Items per page
        total_count: Total number of items
    
    Returns:
        Dictionary with pagination information
    """
    total_pages = (total_count + limit - 1) // limit  # Ceiling division
    
    return {
        'page': page,
        'limit': limit,
        'total_count': total_count,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1
    }


def optimize_query_for_endpoint(query, endpoint_type):
    """
    Optimize query based on the endpoint type to avoid unnecessary eager loading.
    
    Args:
        query: SQLAlchemy query object
        endpoint_type: Type of endpoint ('stats', 'search', 'data', 'problems')
    
    Returns:
        Optimized query object
    """
    # Different endpoints need different data
    eager_load_config = {
        'stats': {'atlas': True, 'osm': False},  # Stats mostly need Atlas data
        'search': {'atlas': True, 'osm': True},   # Search needs both
        'data': {'atlas': True, 'osm': True},     # Map data needs both
        'problems': {'atlas': True, 'osm': True}, # Problems need both
        'reports': {'atlas': True, 'osm': False}  # Reports mostly Atlas
    }
    
    config = eager_load_config.get(endpoint_type, {'atlas': True, 'osm': True})
    
    query_builder = get_query_builder()
    return query_builder.build_base_query(
        eager_load_atlas=config['atlas'],
        eager_load_osm=config['osm']
    )
