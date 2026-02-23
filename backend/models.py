from backend.extensions import db
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

"""
Model definitions for core entities and related tables.
Relationships to `AtlasStop` and `OsmNode` are defined via explicit join
conditions rather than database-level foreign keys.
"""

class Stop(db.Model):
    __tablename__ = 'stops'
    __table_args__ = (
        db.Index('idx_stop_type_match_type', 'stop_type', 'match_type'),
        db.Index('idx_distance_m', 'distance_m'),
        # PostGIS spatial index for fast viewport queries (only applies on Postgres)
        db.Index('idx_stops_geom_gist', 'geom', postgresql_using='gist'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    sloid = db.Column(db.String(100), index=True)
    # Valid values: 'matched', 'atlas_unmatched', 'osm_unmatched'
    stop_type = db.Column(db.String(50))
    match_type = db.Column(db.String(50))
    # Indicates whether a 'manual' match was saved as persistent data
    manual_is_persistent = db.Column(db.Boolean, default=False)

    # Core location and linking attributes
    atlas_lat = db.Column(db.Float)
    atlas_lon = db.Column(db.Float)
    osm_node_id = db.Column(db.String(100), index=True)
    osm_lat = db.Column(db.Float)
    osm_lon = db.Column(db.Float)
    distance_m = db.Column(db.Float)

    # Display geometry (atlas point if present, else osm point). SRID 4326 (WGS84).
    # Populated by the import pipeline; indexed for bbox queries.
    geom = db.Column(Geometry(geometry_type='POINT', srid=4326), nullable=True)

    # Fast-path booleans for duplicate marker rendering (full group data on detail tables)
    has_atlas_duplicate = db.Column(db.Boolean, default=False)
    has_osm_duplicate = db.Column(db.Boolean, default=False)
    
    # Relationship to ATLAS stop details (lazy='select' to avoid unnecessary JOINs on /api/data;
    # endpoints that need details use explicit joinedload() via optimize_query_for_endpoint)
    atlas_stop_details = db.relationship('AtlasStop', primaryjoin='Stop.sloid == AtlasStop.sloid', foreign_keys='AtlasStop.sloid', uselist=False, lazy='select')

    # Relationship to OSM node details
    osm_node_details = db.relationship('OsmNode', primaryjoin='Stop.osm_node_id == OsmNode.osm_node_id', foreign_keys='OsmNode.osm_node_id', uselist=False, lazy='select')

    # Relationship to problems
    problems = db.relationship('Problem', back_populates='stop', cascade="all, delete-orphan")

class Problem(db.Model):
    __tablename__ = 'problems'
    __table_args__ = (
        db.Index('idx_problem_type', 'problem_type'),
        db.Index('idx_problem_stop_id', 'stop_id'),
        db.Index('idx_problem_priority', 'priority'),
    )
    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(db.Integer, db.ForeignKey('stops.id', ondelete='CASCADE'))
    problem_type = db.Column(db.String(50), nullable=False)
    solution = db.Column(db.String(500))
    is_persistent = db.Column(db.Boolean, default=False)
    # Attribution
    created_by_user_id = db.Column(db.Integer, index=True, nullable=True)
    created_by_user_email = db.Column(db.String(255), nullable=True)
    # Priority for this problem within its category (1 = highest)
    priority = db.Column(db.Integer)
    stop = db.relationship('Stop', back_populates='problems')

    def to_dict(self):
        # Use the Stop relationships instead of issuing separate queries.
        # Callers should use joinedload/subqueryload to pre-load these.
        stop = self.stop
        atlas_details = stop.atlas_stop_details if stop else None
        osm_details = stop.osm_node_details if stop else None

        return {
            'id': self.id,
            'stop_id': self.stop_id,
            'problem': self.problem_type,
            'solution': self.solution,
            'is_persistent': self.is_persistent,
            'priority': self.priority,
            'sloid': stop.sloid if stop else None,
            'stop_type': stop.stop_type if stop else None,
            'match_type': stop.match_type if stop else None,
            'atlas_designation': atlas_details.atlas_designation if atlas_details else None,
            'atlas_designation_official': atlas_details.atlas_designation_official if atlas_details else None,
            'atlas_business_org_abbr': atlas_details.atlas_business_org_abbr if atlas_details else None,
            'osm_name': osm_details.osm_name if osm_details else None,
            'osm_local_ref': osm_details.osm_local_ref if osm_details else None,
            'osm_operator': osm_details.osm_operator if osm_details else None,
            'osm_public_transport': osm_details.osm_public_transport if osm_details else None,
        }

class PersistentData(db.Model):
    __bind_key__ = 'user_input'
    __tablename__ = 'persistent_data'
    
    id = db.Column(db.Integer, primary_key=True)
    sloid = db.Column(db.String(100), index=True)
    osm_node_id = db.Column(db.String(100), index=True)
    problem_type = db.Column(db.String(50), index=True)
    solution = db.Column(db.String(500))
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    # Ownership/attribution
    created_by_user_id = db.Column(db.Integer, index=True, nullable=True)
    created_by_user_email = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('sloid', 'osm_node_id', 'problem_type', name='unique_problem'),
    )

class AtlasStop(db.Model):
    __tablename__ = 'atlas_stops'
    __table_args__ = (
        db.Index('idx_atlas_operator', 'atlas_business_org_abbr'),
    )
    
    sloid = db.Column(db.String(100), primary_key=True)
    uic_ref = db.Column(db.String(100), index=True)
    atlas_designation = db.Column(db.String(255))
    atlas_designation_official = db.Column(db.String(255))
    atlas_business_org_abbr = db.Column(db.String(100))
    routes_unified = db.Column(JSONB)
    # JSONB array of all SLOIDs in the duplicate group (e.g. ["sloid1", "sloid2"])
    duplicate_group_sloids = db.Column(JSONB)

class OsmNode(db.Model):
    __tablename__ = 'osm_nodes'
    
    osm_node_id = db.Column(db.String(100), primary_key=True)
    osm_local_ref = db.Column(db.String(100))
    osm_name = db.Column(db.String(255))
    osm_uic_name = db.Column(db.String(255))
    osm_uic_ref = db.Column(db.String(255))
    osm_network = db.Column(db.String(255))
    osm_public_transport = db.Column(db.String(255))
    osm_railway = db.Column(db.String(255))
    osm_amenity = db.Column(db.String(255))
    osm_aerialway = db.Column(db.String(255))
    osm_operator = db.Column(db.String(255))
    osm_node_type = db.Column(db.String(50))
    routes_osm = db.Column(JSONB)
    # JSONB array of all OSM node IDs in the duplicate group (e.g. ["123", "456"])
    duplicate_group_node_ids = db.Column(JSONB)

class UserNote(db.Model):
    __bind_key__ = 'user_input'
    __tablename__ = 'user_notes'

    id = db.Column(db.Integer, primary_key=True)
    # Either sloid or osm_node_id will be set, depending on note_type
    sloid = db.Column(db.String(100), index=True, nullable=True)
    osm_node_id = db.Column(db.String(100), index=True, nullable=True)
    # 'atlas' or 'osm'
    note_type = db.Column(db.String(20), index=True, nullable=False)
    user_id = db.Column(db.Integer, index=True, nullable=False)
    user_email = db.Column(db.String(255), nullable=True)
    note = db.Column(db.Text)
    is_persistent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    __table_args__ = (
        db.UniqueConstraint('sloid', 'osm_node_id', 'note_type', 'user_id', name='unique_user_note'),
    )

class RouteAndDirection(db.Model):
    __tablename__ = 'routes_and_directions'
    
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.String(20))
    osm_route_id = db.Column(db.String(100))
    osm_nodes_json = db.Column(JSONB)
    atlas_route_id = db.Column(db.String(100))
    atlas_sloids_json = db.Column(JSONB)
    route_name = db.Column(db.String(255))
    route_short_name = db.Column(db.String(50))
    route_long_name = db.Column(db.String(255))
    route_type = db.Column(db.String(50))
    match_type = db.Column(db.String(50))
    # Unified fields
    source = db.Column(db.String(10))  # 'gtfs' or 'hrdf'
    atlas_line_name = db.Column(db.String(100))
    direction_uic = db.Column(db.String(50))
    route_id_normalized = db.Column(db.String(100))

    __table_args__ = (
        db.Index('idx_osm_route_direction', 'osm_route_id', 'direction_id'),
        db.Index('idx_atlas_route_direction', 'atlas_route_id', 'direction_id'),
        db.Index('idx_atlas_line_direction_uic', 'atlas_line_name', 'direction_uic'),
        db.Index('idx_source', 'source')
    ) 