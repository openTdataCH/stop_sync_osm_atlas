"""
Enhanced QueryBuilder class for handling complex database queries with shared filtering logic.
This module consolidates common filtering patterns to reduce code duplication and improve performance.
"""

from backend.services.routes import get_stops_for_route
from backend.extensions import db
from backend.models import StopsMatched, AtlasStop, OsmNode, OsmStop, OsmStopMember
from sqlalchemy.orm import joinedload
from sqlalchemy import func


class FilterBuilder:
    """Helper class to build common filter conditions without duplication."""
    
    @staticmethod
    def build_transport_type_conditions(selected_transport_types):
        """Build transport type filter conditions."""
        if not selected_transport_types:
            return []
        
        transport_conditions = []
        
        # Define transport type mappings
        transport_mappings = {
            'ferry_terminal': StopsMatched.osm_node_details.has(OsmNode.osm_amenity == 'ferry_terminal'),
            'tram_stop': StopsMatched.osm_node_details.has(OsmNode.osm_railway == 'tram_stop'),
            'station': StopsMatched.osm_node_details.has(OsmNode.osm_node_type == 'railway_station'),
            'platform': StopsMatched.osm_node_details.has(OsmNode.osm_public_transport == 'platform'),
            'stop_position': StopsMatched.osm_node_details.has(OsmNode.osm_public_transport == 'stop_position'),
            'aerialway_station': StopsMatched.osm_node_details.has(OsmNode.osm_aerialway == 'station')
        }
        
        for transport_type in selected_transport_types:
            if transport_type in transport_mappings:
                transport_conditions.append(transport_mappings[transport_type])
        
        return transport_conditions
    
    @staticmethod
    def build_node_type_conditions(node_types):
        """Build node type filter conditions."""
        if not node_types:
            return []
        
        conditions = []
        if 'atlas' in node_types:
            conditions.append(StopsMatched.sloid.isnot(None))
        if 'osm' in node_types:
            conditions.append(StopsMatched.osm_node_id.isnot(None))
        
        return conditions
    
    @staticmethod
    def build_atlas_operator_conditions(atlas_operators):
        """Build Atlas operator filter conditions."""
        if not atlas_operators:
            return None
        
        return StopsMatched.atlas_stop_details.has(
            AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
        )
    
    @staticmethod
    def build_station_filter_conditions(filter_values, filter_types, route_directions, route_query_func):
        """Build station/route ID filter conditions."""
        if not filter_values:
            return []
        
        # Ensure arrays are same length
        while len(filter_types) < len(filter_values):
            filter_types.append('station')
        while len(route_directions) < len(filter_values):
            route_directions.append('')
        
        conditions = []
        for i, value in enumerate(filter_values):
            filter_type = filter_types[i].strip()
            direction = route_directions[i].strip()
            
            if filter_type == 'atlas':
                conditions.append(StopsMatched.sloid.like(f'%{value}%'))
            elif filter_type == 'osm':
                conditions.append(StopsMatched.osm_node_id.like(f'%{value}%'))
            elif filter_type == 'route':
                route_stops = route_query_func(value, direction if direction else None)
                route_conditions = []
                if route_stops['atlas_sloids']:
                    route_conditions.append(StopsMatched.sloid.in_(route_stops['atlas_sloids']))
                if route_stops['osm_nodes']:
                    route_conditions.append(StopsMatched.osm_node_id.in_(route_stops['osm_nodes']))
                if route_conditions:
                    conditions.append(db.or_(*route_conditions) if len(route_conditions) > 1 else route_conditions[0])
            elif filter_type == 'hrdf_route':
                # Postgres JSONB: check if any routes_unified entry has a matching line_name.
                conditions.append(
                    StopsMatched.atlas_stop_details.has(
                        func.jsonb_path_exists(
                            AtlasStop.routes_unified,
                            '$[*] ? (@.line_name == $line)',
                            func.jsonb_build_object('line', value)
                        )
                    )
                )
            else:  # UIC ref — search both atlas and osm tables
                conditions.append(db.or_(
                    StopsMatched.atlas_stop_details.has(AtlasStop.uic_ref.ilike(f'%{value}%')),
                    StopsMatched.osm_node_details.has(OsmNode.osm_uic_ref.ilike(f'%{value}%'))
                ))
        
        return conditions

    @staticmethod
    def build_osm_group_members_query(osm_group_types=None):
        query = db.session.query(OsmStopMember.node_id).join(
            OsmStop,
            OsmStopMember.osm_stop_id == OsmStop.id,
        )

        # Default: all grouped OSM members.
        if osm_group_types is None or len(osm_group_types) == 0:
            return query.filter(OsmStop.stop_kind.in_(['pair', 'trio']))

        pair_types = [group_type for group_type in osm_group_types if group_type.startswith('osm_pair_')]
        include_trio = 'osm_trio' in osm_group_types

        conditions = []
        if pair_types:
            conditions.append(
                db.and_(
                    OsmStop.stop_kind == 'pair',
                    OsmStop.group_kind.in_(pair_types),
                )
            )
        if include_trio:
            conditions.append(
                db.and_(
                    OsmStop.stop_kind == 'trio',
                    OsmStop.group_kind == 'osm_trio',
                )
            )

        if not conditions:
            return query.filter(db.false())

        return query.filter(db.or_(*conditions))


class QueryBuilder:
    """
    Enhanced QueryBuilder for building and executing complex database queries.
    Includes shared filtering logic and performance optimizations.
    """
    
    def __init__(self, session):
        """
        Initialize the QueryBuilder.
        
        Args:
            session: SQLAlchemy database session
        """
        self.session = session
        self.filter_builder = FilterBuilder()
    
    def get_stops_for_route(self, route_id, direction=None):
        """
        Gets all stops (both OSM and ATLAS) that belong to a route.
        
        Args:
            route_id: The route ID to filter by
            direction: Optional direction ID to filter by
        
        Returns:
            Dictionary with 'atlas_sloids' and 'osm_nodes' lists
        """
        return get_stops_for_route(route_id, direction)
    
    def build_base_query(self, eager_load_atlas=True, eager_load_osm=True):
        """
        Build a base query with optional eager loading for performance.
        
        Args:
            eager_load_atlas: Whether to eager load Atlas stop details
            eager_load_osm: Whether to eager load OSM node details
        
        Returns:
            SQLAlchemy query object
        """
        query = StopsMatched.query
        
        options = []
        if eager_load_atlas:
            options.append(joinedload(StopsMatched.atlas_stop_details))
        if eager_load_osm:
            options.append(joinedload(StopsMatched.osm_node_details))
        
        if options:
            query = query.options(*options)
        
        return query
    
    def apply_common_filters(self, query, filters):
        """
        Apply common filtering patterns to a query.
        
        Args:
            query: SQLAlchemy query object
            filters: Dictionary containing filter parameters
        
        Returns:
            Filtered SQLAlchemy query object
        """
        conditions = []
        osm_conditions = []
        
        # Transport type filter
        if filters.get('transport_types'):
            transport_conditions = self.filter_builder.build_transport_type_conditions(
                filters['transport_types']
            )
            if transport_conditions:
                osm_conditions.append(db.or_(*transport_conditions))
        
        # Node type filter
        if filters.get('node_types'):
            node_conditions = self.filter_builder.build_node_type_conditions(
                filters['node_types']
            )
            if node_conditions:
                conditions.append(db.or_(*node_conditions) if len(node_conditions) > 1 else node_conditions[0])
        
        # Atlas operator filter
        if filters.get('atlas_operators'):
            operator_condition = self.filter_builder.build_atlas_operator_conditions(
                filters['atlas_operators']
            )
            # Avoid evaluating SQLAlchemy clauses in boolean context
            if operator_condition is not None:
                conditions.append(operator_condition)
        
        # Station/Route filter
        if filters.get('filter_values'):
            station_conditions = self.filter_builder.build_station_filter_conditions(
                filters['filter_values'],
                filters.get('filter_types', []),
                filters.get('route_directions', []),
                self.get_stops_for_route
            )
            if station_conditions:
                conditions.append(db.or_(*station_conditions) if len(station_conditions) > 1 else station_conditions[0])
            else:
                conditions.append(db.false())
        
        # OSM group filter
        if 'osm_group_types' in filters:
            osm_conditions.append(
                StopsMatched.osm_node_id.in_(
                    self.filter_builder.build_osm_group_members_query(filters.get('osm_group_types'))
                )
            )

        if osm_conditions:
            combined_osm_condition = db.and_(*osm_conditions)
            conditions.append(combined_osm_condition)
        
        # Apply all conditions
        if conditions:
            query = query.filter(db.and_(*conditions))
        
        return query

    def apply_bucket_filters(self, query, filters):
        """
        Apply filter conditions to a GlobalStatsBucket query.
        
        Args:
            query: SQLAlchemy query object (for GlobalStatsBucket)
            filters: Dictionary containing filter parameters
        
        Returns:
            Filtered SQLAlchemy query object
        """
        from backend.models import GlobalStatsBucket
        conditions = []
        
        # Transport type filter
        if filters.get('transport_types'):
            transport_conditions = []
            for t_type in filters['transport_types']:
                col_name = f"is_{t_type}"
                if hasattr(GlobalStatsBucket, col_name):
                    transport_conditions.append(getattr(GlobalStatsBucket, col_name) == True)
            if transport_conditions:
                conditions.append(db.or_(*transport_conditions))
        
        # Node type filter
        if filters.get('node_types'):
            node_conditions = []
            if 'atlas' in filters['node_types']:
                node_conditions.append(GlobalStatsBucket.total_atlas > 0)
            if 'osm' in filters['node_types']:
                node_conditions.append(GlobalStatsBucket.total_osm_nodes > 0)
            if node_conditions:
                conditions.append(db.or_(*node_conditions))
                
        # Atlas operator filter
        if filters.get('atlas_operators'):
            conditions.append(GlobalStatsBucket.atlas_operator.in_(filters['atlas_operators']))
            
        # OSM group filter
        if 'osm_group_types' in filters:
            osm_group_types = filters.get('osm_group_types')
            if not osm_group_types:
                # Any pair or trio
                conditions.append(GlobalStatsBucket.osm_group_kind.isnot(None))
            else:
                group_conditions = []
                pair_types = [g for g in osm_group_types if g.startswith('osm_pair_')]
                include_trio = 'osm_trio' in osm_group_types
                if pair_types:
                    group_conditions.append(GlobalStatsBucket.osm_group_kind.in_(pair_types))
                if include_trio:
                    group_conditions.append(GlobalStatsBucket.osm_group_kind == 'osm_trio')
                if group_conditions:
                    conditions.append(db.or_(*group_conditions))
                else:
                    conditions.append(db.false())
                    
        if conditions:
            query = query.filter(db.and_(*conditions))
            
        return query
