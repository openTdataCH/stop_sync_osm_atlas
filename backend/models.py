from backend.extensions import db
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

"""
Model definitions for core entities and related tables.
Relationships to `AtlasStop` and `OsmNode` are defined via explicit join
conditions rather than database-level foreign keys.
"""

class StopsMatched(db.Model):
    __tablename__ = 'stops_matched'
    __table_args__ = (
        db.Index('idx_stop_type_match_type', 'stop_type', 'match_type'),
        db.Index('idx_distance_m', 'distance_m'),
        # PostGIS spatial index for fast viewport queries (only applies on Postgres)
        db.Index('idx_stops_geom_gist', 'geom', postgresql_using='gist'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    sloid = db.Column(db.String(100), index=True)
    # Valid values: 'matched', 'effectively_matched', 'atlas_unmatched', 'osm_unmatched'
    stop_type = db.Column(db.String(50))
    match_type = db.Column(db.String(50))
    # Core location and linking attributes
    atlas_lat = db.Column(db.Float)
    atlas_lon = db.Column(db.Float)
    osm_node_id = db.Column(db.String(100), index=True)
    osm_lat = db.Column(db.Float)
    osm_lon = db.Column(db.Float)
    distance_m = db.Column(db.Float)
    matching_notes = db.Column(db.Text)


    # Display geometry (atlas point if present, else osm point). SRID 4326 (WGS84).
    # Populated by the import pipeline; indexed for bbox queries.
    geom = db.Column(Geometry(geometry_type='POINT', srid=4326), nullable=True)

    # Relationship to ATLAS stop details (lazy='select' to avoid unnecessary JOINs on /api/data;
    # endpoints that need details use explicit joinedload() via optimize_query_for_endpoint)
    atlas_stop_details = db.relationship('AtlasStop', primaryjoin='StopsMatched.sloid == AtlasStop.sloid', foreign_keys='AtlasStop.sloid', uselist=False, lazy='select')

    # Relationship to OSM node details
    osm_node_details = db.relationship('OsmNode', primaryjoin='StopsMatched.osm_node_id == OsmNode.osm_node_id', foreign_keys='OsmNode.osm_node_id', uselist=False, lazy='select')

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
    stop_id = db.Column(db.Integer, db.ForeignKey('stops_matched.id', ondelete='CASCADE'))
    problem_type = db.Column(db.String(50), nullable=False)
    # Priority for this problem within its category (1 = highest)
    priority = db.Column(db.Integer)
    stop = db.relationship('StopsMatched', back_populates='problems')

    def to_dict(self):
        # Use the StopsMatched relationships instead of issuing separate queries.
        # Callers should use joinedload/subqueryload to pre-load these.
        stop = self.stop
        atlas_details = stop.atlas_stop_details if stop else None
        osm_details = stop.osm_node_details if stop else None

        return {
            'id': self.id,
            'stop_id': self.stop_id,
            'problem': self.problem_type,
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
    # FK to the representative SLOID (NULL if this IS the representative or not in a group)
    representative_sloid = db.Column(db.String(100), nullable=True, index=True)
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
    # JSONB array of all OSM node IDs in the duplicate group (e.g. ["123", "456"])
    duplicate_group_node_ids = db.Column(JSONB)


class OsmStop(db.Model):
    """Canonical OSM stop unit used for counting/filtering semantics."""
    __tablename__ = 'osm_stops'

    __table_args__ = (
        db.Index('idx_osm_stops_stop_kind', 'stop_kind'),
        db.Index('idx_osm_stops_group_kind', 'group_kind'),
        db.Index('idx_osm_stops_representative_node_id', 'representative_node_id'),
        db.CheckConstraint(
            "stop_kind IN ('single', 'pair', 'trio')",
            name='ck_osm_stops_stop_kind'
        ),
        db.CheckConstraint(
            "group_kind IS NULL OR group_kind IN ('osm_pair_uic', 'osm_pair_name', 'osm_pair_tram', "
            "'osm_pair_uic_equal_15m', 'osm_pair_name_equal_15m', 'osm_pair_tram_equal_15m', 'osm_trio')",
            name='ck_osm_stops_group_kind'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    stop_kind = db.Column(db.String(20), nullable=False)
    group_kind = db.Column(db.String(50), nullable=True)
    representative_node_id = db.Column(
        db.String(100),
        db.ForeignKey('osm_nodes.osm_node_id', ondelete='CASCADE'),
        nullable=False,
    )

    representative_node = db.relationship('OsmNode', foreign_keys=[representative_node_id], lazy='select')
    members = db.relationship('OsmStopMember', back_populates='osm_stop', cascade="all, delete-orphan")


class OsmStopMember(db.Model):
    """Membership rows mapping raw OSM nodes to stop units with role semantics."""
    __tablename__ = 'osm_stop_members'

    __table_args__ = (
        db.CheckConstraint(
            "member_role IN ('single', 'pair_a', 'pair_b', 'trio_middle', 'trio_side')",
            name='ck_osm_stop_members_member_role'
        ),
        db.UniqueConstraint('node_id', name='uq_osm_stop_members_node_id'),
    )

    osm_stop_id = db.Column(
        db.Integer,
        db.ForeignKey('osm_stops.id', ondelete='CASCADE'),
        primary_key=True,
    )
    node_id = db.Column(
        db.String(100),
        db.ForeignKey('osm_nodes.osm_node_id', ondelete='CASCADE'),
        primary_key=True,
    )
    member_role = db.Column(db.String(20), nullable=False)

    osm_stop = db.relationship('OsmStop', back_populates='members', lazy='select')
    osm_node = db.relationship('OsmNode', lazy='select')


class RouteAtlasStops(db.Model):
    __tablename__ = 'route_atlas_stops'

    id = db.Column(db.Integer, primary_key=True)
    atlas_route_id = db.Column(db.String(100), index=True)
    direction_id = db.Column(db.String(20), index=True)
    sloid = db.Column(db.String(100), db.ForeignKey('atlas_stops.sloid', ondelete='CASCADE'), index=True)
    stop_sequence = db.Column(db.Integer)

    __table_args__ = (
        db.Index('idx_atlas_route_dir_seq', 'atlas_route_id', 'direction_id', 'stop_sequence'),
    )

class RouteOsmStops(db.Model):
    __tablename__ = 'route_osm_stops'

    id = db.Column(db.Integer, primary_key=True)
    osm_route_id = db.Column(db.String(100), index=True)
    direction_id = db.Column(db.String(20), index=True)
    osm_node_id = db.Column(db.String(100), db.ForeignKey('osm_nodes.osm_node_id', ondelete='CASCADE'), index=True)
    stop_sequence = db.Column(db.Integer)

    __table_args__ = (
        db.Index('idx_osm_route_dir_seq', 'osm_route_id', 'direction_id', 'stop_sequence'),
    )

class RoutesMatched(db.Model):
    __tablename__ = 'routes_matched'

    id = db.Column(db.Integer, primary_key=True)
    atlas_route_id = db.Column(db.String(100), index=True)
    osm_route_id = db.Column(db.String(100), index=True)
    match_type = db.Column(db.String(50))


class GlobalStatsBucket(db.Model):
    __tablename__ = 'global_stats_buckets'
    __table_args__ = (
        db.Index('idx_gsb_scope_effective', 'scope', 'effective_stop_type'),
        db.Index('idx_gsb_match_type', 'match_type'),
        db.Index('idx_gsb_group_kind', 'osm_group_kind'),
        db.Index('idx_gsb_atlas_duplicate', 'atlas_duplicate'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False) # 'atlas+osm', 'atlas_only', 'osm_only'
    atlas_operator = db.Column(db.String(100), nullable=True, index=True)
    atlas_duplicate = db.Column(db.Boolean, nullable=False, default=False)
    osm_group_kind = db.Column(db.String(50), nullable=True)
    effective_stop_type = db.Column(db.String(50), nullable=True) # matched, effectively_matched, atlas_unmatched, osm_unmatched
    match_type = db.Column(db.String(50), nullable=True)
    
    # Transport dimension flags for easy boolean querying
    is_ferry_terminal = db.Column(db.Boolean, nullable=False, default=False)
    is_tram_stop = db.Column(db.Boolean, nullable=False, default=False)
    is_station = db.Column(db.Boolean, nullable=False, default=False)
    is_platform = db.Column(db.Boolean, nullable=False, default=False)
    is_stop_position = db.Column(db.Boolean, nullable=False, default=False)
    is_aerialway_station = db.Column(db.Boolean, nullable=False, default=False)
    
    # Aggregated counters
    total_atlas = db.Column(db.Integer, nullable=False, default=0)
    matched_atlas = db.Column(db.Integer, nullable=False, default=0)
    unmatched_atlas = db.Column(db.Integer, nullable=False, default=0)
    matched_pairs = db.Column(db.Integer, nullable=False, default=0)
    total_osm_stops = db.Column(db.Integer, nullable=False, default=0)
    matched_osm_stops = db.Column(db.Integer, nullable=False, default=0)
    total_osm_nodes = db.Column(db.Integer, nullable=False, default=0)