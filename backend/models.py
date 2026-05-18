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
            'osm_operator_wikidata': osm_details.osm_operator_wikidata if osm_details else None,
            'osm_public_transport': osm_details.osm_public_transport if osm_details else None,
        }



class AtlasOperator(db.Model):
    __tablename__ = 'atlas_operators'
    __table_args__ = (
        db.Index('idx_atlas_operator_sboid', 'sboid'),
    )

    atlas_business_org_abbr = db.Column(db.String(100), primary_key=True)
    sboid = db.Column(db.String(100), unique=True)
    atlas_business_org_name = db.Column(db.String(255))

    atlas_stops = db.relationship('AtlasStop', back_populates='atlas_operator', lazy='select')


class AtlasStop(db.Model):
    __tablename__ = 'atlas_stops'
    __table_args__ = (
        db.Index('idx_atlas_operator', 'atlas_business_org_abbr'),
    )
    
    sloid = db.Column(db.String(100), primary_key=True)
    uic_ref = db.Column(db.String(100), index=True)
    atlas_designation = db.Column(db.String(255))
    atlas_designation_official = db.Column(db.String(255))
    atlas_business_org_abbr = db.Column(
        db.String(100),
        db.ForeignKey('atlas_operators.atlas_business_org_abbr', ondelete='SET NULL'),
    )
    # FK to the representative SLOID (NULL if this IS the representative or not in a group)
    representative_sloid = db.Column(db.String(100), nullable=True, index=True)
    # JSONB array of all SLOIDs in the duplicate group (e.g. ["sloid1", "sloid2"])
    duplicate_group_sloids = db.Column(JSONB)

    atlas_operator = db.relationship('AtlasOperator', back_populates='atlas_stops', lazy='select')


class GtfsStopRaw(db.Model):
    __tablename__ = 'gtfs_stops_raw'
    __table_args__ = (
        db.Index('idx_gtfs_stops_raw_uic_number', 'uic_number'),
        db.Index('idx_gtfs_stops_raw_original_stop_id', 'original_stop_id'),
        db.Index('idx_gtfs_stops_raw_parent_station', 'parent_station'),
        db.Index('idx_gtfs_stops_raw_coords', 'stop_lat', 'stop_lon'),
    )

    stop_id = db.Column(db.String(255), primary_key=True)
    stop_code = db.Column(db.String(255))
    stop_name = db.Column(db.String(255))
    stop_lat = db.Column(db.Float, nullable=False)
    stop_lon = db.Column(db.Float, nullable=False)
    platform_code = db.Column(db.String(255))
    original_stop_id = db.Column(db.String(255))
    location_type = db.Column(db.String(20))
    parent_station = db.Column(db.String(255))
    uic_number = db.Column(db.String(64), nullable=False)
    local_ref = db.Column(db.String(64))
    normalized_local_ref = db.Column(db.String(64))


class GtfsStopIdentityResolution(db.Model):
    __tablename__ = 'gtfs_stop_identity_resolution'
    __table_args__ = (
        db.UniqueConstraint('stop_id', name='uq_gtfs_stop_identity_resolution_stop_id'),
        db.Index('idx_gtfs_stop_identity_resolution_sloid', 'resolved_sloid'),
        db.Index('idx_gtfs_stop_identity_resolution_method', 'resolution_method'),
        db.Index('idx_gtfs_stop_identity_resolution_level', 'identity_level'),
    )

    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(db.String(255), db.ForeignKey('gtfs_stops_raw.stop_id', ondelete='CASCADE'), nullable=False)
    source_location_type = db.Column(db.String(20))
    identity_level = db.Column(db.String(50))
    resolved_sloid = db.Column(db.String(100), db.ForeignKey('atlas_stops.sloid', ondelete='SET NULL'))
    resolution_method = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float)
    distance_m = db.Column(db.Float)
    gtfs_stop_lat = db.Column(db.Float)
    gtfs_stop_lon = db.Column(db.Float)
    atlas_lat = db.Column(db.Float)
    atlas_lon = db.Column(db.Float)
    details_json = db.Column(JSONB)

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
    osm_operator_wikidata = db.Column(db.String(100))
    osm_network_wikidata = db.Column(db.String(100))
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


class AtlasLineFamily(db.Model):
    __tablename__ = 'atlas_line_families'
    __table_args__ = (
        db.Index('idx_atlas_line_families_route_id_normalized', 'route_id_normalized'),
        db.Index('idx_atlas_line_families_route_type', 'route_type'),
    )

    atlas_line_id = db.Column(db.String(100), primary_key=True)
    route_id_normalized = db.Column(db.String(100))
    agency_id = db.Column(db.String(100))
    route_short_name = db.Column(db.String(255))
    route_long_name = db.Column(db.String(255))
    route_desc = db.Column(db.Text)
    route_type = db.Column(db.String(50))


class OsmRouteRelation(db.Model):
    __tablename__ = 'osm_route_relations'
    __table_args__ = (
        db.Index('idx_osm_route_relations_gtfs_route_id', 'gtfs_route_id'),
        db.Index('idx_osm_route_relations_route', 'route'),
        db.Index('idx_osm_route_relations_ref_operator', 'ref', 'operator'),
    )

    relation_id = db.Column(db.String(100), primary_key=True)
    route = db.Column(db.String(100))
    name = db.Column(db.String(255))
    ref = db.Column(db.String(100))
    operator = db.Column(db.String(255))
    operator_wikidata = db.Column(db.String(100))
    network = db.Column(db.String(255))
    network_wikidata = db.Column(db.String(100))
    from_name = db.Column(db.String(255))
    to_name = db.Column(db.String(255))
    via = db.Column(db.String(255))
    public_transport_version = db.Column(db.String(50))
    colour = db.Column(db.String(64))
    gtfs_route_id = db.Column(db.String(255))
    gtfs_trip_id = db.Column(db.String(255))
    gtfs_trip_id_sample = db.Column(db.String(255))
    gtfs_shape_id = db.Column(db.String(255))
    route_master_id = db.Column(db.String(100))
    family_origin = db.Column(db.String(50))
    synthetic_family_key = db.Column(db.String(255))
    run_id = db.Column(db.String(100))


class LineFamily(db.Model):
    __tablename__ = 'line_families'
    __table_args__ = (
        db.Index('idx_line_families_source', 'source'),
        db.Index('idx_line_families_gtfs_route_id', 'gtfs_route_id'),
        db.UniqueConstraint('source', 'source_family_id', name='uq_line_families_source_family_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)
    source_family_id = db.Column(db.String(255), nullable=False)
    family_origin = db.Column(db.String(50))
    route_type = db.Column(db.String(50))
    display_route_id = db.Column(db.String(255))
    public_name = db.Column(db.String(255))
    ref = db.Column(db.String(100))
    operator = db.Column(db.String(255))
    operator_wikidata = db.Column(db.String(100))
    network = db.Column(db.String(255))
    network_wikidata = db.Column(db.String(100))
    is_non_gtfs = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    gtfs_route_id = db.Column(db.String(255))
    normalized_route_id = db.Column(db.String(255))
    atlas_line_id = db.Column(db.String(100), db.ForeignKey('atlas_line_families.atlas_line_id', ondelete='SET NULL'))
    route_master_id = db.Column(db.String(100))
    representative_relation_id = db.Column(db.String(100), db.ForeignKey('osm_route_relations.relation_id', ondelete='SET NULL'))


class Itinerary(db.Model):
    __tablename__ = 'itineraries'
    __table_args__ = (
        db.Index('idx_itineraries_line_family', 'line_family_id'),
        db.Index('idx_itineraries_source', 'source'),
        db.UniqueConstraint('source', 'source_itinerary_id', name='uq_itineraries_source_itinerary_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)
    line_family_id = db.Column(db.Integer, db.ForeignKey('line_families.id', ondelete='CASCADE'), nullable=False)
    source_itinerary_id = db.Column(db.String(255), nullable=False)
    direction_id = db.Column(db.String(20))
    headsign_or_pattern_hash = db.Column(db.String(128))
    display_name = db.Column(db.String(255))
    representative_headsign = db.Column(db.String(255))
    from_name = db.Column(db.String(255))
    to_name = db.Column(db.String(255))
    trip_count = db.Column(db.Integer)
    shape_id = db.Column(db.Text)
    geometry_wkt = db.Column(db.Text)
    canonical_stop_count = db.Column(db.Integer)


class StopCall(db.Model):
    __tablename__ = 'stop_calls'
    __table_args__ = (
        db.Index('idx_stop_calls_itinerary_sequence', 'itinerary_id', 'stop_sequence'),
        db.Index('idx_stop_calls_canonical_stop_key', 'canonical_stop_key'),
        db.UniqueConstraint('itinerary_id', 'stop_sequence', name='uq_stop_calls_itinerary_sequence'),
    )

    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey('itineraries.id', ondelete='CASCADE'), nullable=False)
    stop_sequence = db.Column(db.Integer, nullable=False)
    source_stop_id = db.Column(db.String(255))
    source_sloid = db.Column(db.String(100), db.ForeignKey('atlas_stops.sloid', ondelete='SET NULL'))
    source_sloid_variants = db.Column(db.Text)
    source_node_id = db.Column(db.String(100), db.ForeignKey('osm_nodes.osm_node_id', ondelete='SET NULL'))
    canonical_stop_key = db.Column(db.String(255))
    stop_label = db.Column(db.String(255))
    uic_ref = db.Column(db.String(100))
    platform_code = db.Column(db.String(255))
    stop_lat = db.Column(db.Float)
    stop_lon = db.Column(db.Float)
    member_role = db.Column(db.String(100))


class LineFamilyMatch(db.Model):
    __tablename__ = 'line_family_matches'
    __table_args__ = (
        db.Index('idx_line_family_matches_atlas_family', 'atlas_line_family_id'),
        db.Index('idx_line_family_matches_osm_family', 'osm_line_family_id'),
        db.UniqueConstraint('atlas_line_family_id', 'osm_line_family_id', name='uq_line_family_matches_pair'),
    )

    id = db.Column(db.Integer, primary_key=True)
    atlas_line_family_id = db.Column(db.Integer, db.ForeignKey('line_families.id', ondelete='CASCADE'), nullable=False)
    osm_line_family_id = db.Column(db.Integer, db.ForeignKey('line_families.id', ondelete='CASCADE'), nullable=False)
    match_method = db.Column(db.String(255))


class ItineraryMatch(db.Model):
    __tablename__ = 'itinerary_matches'
    __table_args__ = (
        db.Index('idx_itinerary_matches_atlas_itinerary', 'atlas_itinerary_id'),
        db.Index('idx_itinerary_matches_osm_itinerary', 'osm_itinerary_id'),
        db.UniqueConstraint('atlas_itinerary_id', 'osm_itinerary_id', name='uq_itinerary_matches_pair'),
    )

    id = db.Column(db.Integer, primary_key=True)
    line_family_match_id = db.Column(db.Integer, db.ForeignKey('line_family_matches.id', ondelete='CASCADE'))
    atlas_itinerary_id = db.Column(db.Integer, db.ForeignKey('itineraries.id', ondelete='CASCADE'), nullable=False)
    osm_itinerary_id = db.Column(db.Integer, db.ForeignKey('itineraries.id', ondelete='CASCADE'), nullable=False)
    direction_score = db.Column(db.Float)
    stop_score = db.Column(db.Float)
    geometry_score = db.Column(db.Float)
    overall_score = db.Column(db.Float)
    match_reason = db.Column(db.String(255))
