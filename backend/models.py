from backend.extensions import db

"""
Model definitions for core entities and related tables.
Relationships to `AtlasStop` and `OsmNode` are defined via explicit join
conditions rather than database-level foreign keys.
"""

class Stop(db.Model):
    __tablename__ = 'stops'
    __table_args__ = (
        db.Index('idx_atlas_lat_lon', 'atlas_lat', 'atlas_lon'),
        db.Index('idx_osm_lat_lon', 'osm_lat', 'osm_lon'),
        db.Index('idx_stop_type_match_type', 'stop_type', 'match_type'),
        db.Index('idx_distance_m', 'distance_m'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    sloid = db.Column(db.String(100), index=True)
    stop_type = db.Column(db.String(50))
    match_type = db.Column(db.String(50))
    # Indicates whether a 'manual' match was saved as persistent data
    manual_is_persistent = db.Column(db.Boolean, default=False)
    
    # Core location and linking attributes
    atlas_lat = db.Column(db.Float)
    atlas_lon = db.Column(db.Float)
    uic_ref = db.Column(db.String(100), index=True)
    osm_node_id = db.Column(db.String(100), index=True)
    osm_lat = db.Column(db.Float)
    osm_lon = db.Column(db.Float)
    distance_m = db.Column(db.Float)
    
    # OSM node type for marker rendering
    osm_node_type = db.Column(db.String(50))
    
    atlas_duplicate_sloid = db.Column(db.String(100), default=None)
    
    # Relationship to ATLAS stop details
    atlas_stop_details = db.relationship('AtlasStop', primaryjoin='Stop.sloid == AtlasStop.sloid', foreign_keys='AtlasStop.sloid', uselist=False, lazy='joined')
    
    # Relationship to OSM node details
    osm_node_details = db.relationship('OsmNode', primaryjoin='Stop.osm_node_id == OsmNode.osm_node_id', foreign_keys='OsmNode.osm_node_id', uselist=False, lazy='joined')

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
        # Build minimal stop data without relying on a non-existent Stop.to_dict()
        stop_data = {}
        if self.stop:
            stop_data = {
                'sloid': self.stop.sloid,
                'stop_type': self.stop.stop_type,
                'match_type': self.stop.match_type,
            }

        # Get OSM and ATLAS specific data from their respective tables
        atlas_data = {}
        if self.stop and self.stop.sloid:
            atlas_stop = AtlasStop.query.filter_by(sloid=self.stop.sloid).first()
            if atlas_stop:
                atlas_data = {
                    'atlas_designation': atlas_stop.atlas_designation,
                    'atlas_designation_official': atlas_stop.atlas_designation_official,
                    'atlas_business_org_abbr': atlas_stop.atlas_business_org_abbr,
                    'atlas_note': atlas_stop.atlas_note
                }
        
        osm_data = {}
        if self.stop and self.stop.osm_node_id:
            osm_node = OsmNode.query.filter_by(osm_node_id=self.stop.osm_node_id).first()
            if osm_node:
                osm_data = {
                    'osm_name': osm_node.osm_name,
                    'osm_local_ref': osm_node.osm_local_ref,
                    'osm_operator': osm_node.osm_operator,
                    'osm_note': osm_node.osm_note,
                    'osm_public_transport': osm_node.osm_public_transport,
                }

        # Merge all data into a single dictionary
        return {
            'id': self.id,
            'stop_id': self.stop_id,
            'problem': self.problem_type,
            'solution': self.solution,
            'is_persistent': self.is_persistent,
            'priority': self.priority,
            'sloid': stop_data.get('sloid'),
            'stop_type': stop_data.get('stop_type'),
            'match_type': stop_data.get('match_type'),
            'atlas_designation': atlas_data.get('atlas_designation'),
            'atlas_designation_official': atlas_data.get('atlas_designation_official'),
            'atlas_business_org_abbr': atlas_data.get('atlas_business_org_abbr'),
            'atlas_note': atlas_data.get('atlas_note'),
            'osm_name': osm_data.get('osm_name'),
            'osm_local_ref': osm_data.get('osm_local_ref'),
            'osm_operator': osm_data.get('osm_operator'),
            'osm_note': osm_data.get('osm_note'),
            'osm_public_transport': osm_data.get('osm_public_transport'),
        }

class PersistentData(db.Model):
    __tablename__ = 'persistent_data'
    
    id = db.Column(db.Integer, primary_key=True)
    sloid = db.Column(db.String(100), index=True)
    osm_node_id = db.Column(db.String(100), index=True)
    problem_type = db.Column(db.String(50), index=True)
    solution = db.Column(db.String(500))
    note_type = db.Column(db.String(20), index=True)  # 'atlas', 'osm', or NULL for problem solutions
    note = db.Column(db.Text)  # For storing persistent notes
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    # Ownership/attribution
    created_by_user_id = db.Column(db.Integer, index=True, nullable=True)
    created_by_user_email = db.Column(db.String(255), nullable=True)
    
    __table_args__ = (
        db.UniqueConstraint('sloid', 'osm_node_id', 'problem_type', 'note_type', name='unique_problem'),
    )

class AtlasStop(db.Model):
    __tablename__ = 'atlas_stops'
    __table_args__ = (
        db.Index('idx_atlas_operator', 'atlas_business_org_abbr'),
    )
    
    sloid = db.Column(db.String(100), primary_key=True)
    atlas_designation = db.Column(db.String(255))
    atlas_designation_official = db.Column(db.String(255))
    atlas_business_org_abbr = db.Column(db.String(100))
    routes_unified = db.Column(db.JSON)
    atlas_note = db.Column(db.Text)
    atlas_note_is_persistent = db.Column(db.Boolean, default=False)
    # Attribution for latest note change
    atlas_note_user_id = db.Column(db.Integer, index=True, nullable=True)
    atlas_note_user_email = db.Column(db.String(255), nullable=True)

class OsmNode(db.Model):
    __tablename__ = 'osm_nodes'
    
    osm_node_id = db.Column(db.String(100), primary_key=True)
    osm_local_ref = db.Column(db.String(100))
    osm_name = db.Column(db.String(255))
    osm_uic_name = db.Column(db.String(255))
    osm_network = db.Column(db.String(255))
    osm_public_transport = db.Column(db.String(255))
    osm_railway = db.Column(db.String(255))
    osm_amenity = db.Column(db.String(255))
    osm_aerialway = db.Column(db.String(255))
    osm_operator = db.Column(db.String(255))
    routes_osm = db.Column(db.JSON)
    osm_note = db.Column(db.Text)
    osm_note_is_persistent = db.Column(db.Boolean, default=False)
    # Attribution for latest note change
    osm_note_user_id = db.Column(db.Integer, index=True, nullable=True)
    osm_note_user_email = db.Column(db.String(255), nullable=True)

class RouteAndDirection(db.Model):
    __tablename__ = 'routes_and_directions'
    
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.String(20))
    osm_route_id = db.Column(db.String(100))
    osm_nodes_json = db.Column(db.JSON)
    atlas_route_id = db.Column(db.String(100))
    atlas_sloids_json = db.Column(db.JSON)
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