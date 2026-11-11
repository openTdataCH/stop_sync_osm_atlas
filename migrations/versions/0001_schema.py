"""The whole schema of backend/models.py.

Revision ID: 0001
Revises:
Create Date: 2026-11-10

Generated with `flask db migrate` from an empty PostGIS database. A schema change
edits backend/models.py and adds a migration after this one; tests/test_migrations.py
fails while the two disagree. Every import rebuilds the tables from the models
(backend/importing/publication.py), so a migration only has to bring an existing
database to the same shape.
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from geoalchemy2 import alembic_helpers  # noqa: F401 -- registers create_geospatial_table and its index operations.
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    op.create_table('gtfs_line_families',
    sa.Column('gtfs_line_id', sa.Text(), nullable=False),
    sa.Column('route_id_normalized', sa.Text(), nullable=True),
    sa.Column('agency_id', sa.Text(), nullable=True),
    sa.Column('route_short_name', sa.String(length=255), nullable=True),
    sa.Column('route_long_name', sa.String(length=255), nullable=True),
    sa.Column('route_desc', sa.Text(), nullable=True),
    sa.Column('route_type', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('gtfs_line_id')
    )
    op.create_index('idx_gtfs_line_families_route_id_normalized', 'gtfs_line_families', ['route_id_normalized'], unique=False)
    op.create_index('idx_gtfs_line_families_route_type', 'gtfs_line_families', ['route_type'], unique=False)
    op.create_table('atlas_operators',
    sa.Column('atlas_business_org_abbr', sa.String(length=100), nullable=False),
    sa.Column('sboid', sa.String(length=100), nullable=True),
    sa.Column('atlas_business_org_name', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('atlas_business_org_abbr'),
    sa.UniqueConstraint('sboid')
    )
    op.create_index('idx_atlas_operator_sboid', 'atlas_operators', ['sboid'], unique=False)
    op.create_table('dataset_publication',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=100), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('gtfs_stops_raw',
    sa.Column('stop_id', sa.Text(), nullable=False),
    sa.Column('stop_code', sa.String(length=255), nullable=True),
    sa.Column('stop_name', sa.String(length=255), nullable=True),
    sa.Column('stop_lat', sa.Float(), nullable=False),
    sa.Column('stop_lon', sa.Float(), nullable=False),
    sa.Column('platform_code', sa.String(length=255), nullable=True),
    sa.Column('original_stop_id', sa.Text(), nullable=True),
    sa.Column('location_type', sa.String(length=20), nullable=True),
    sa.Column('parent_station', sa.Text(), nullable=True),
    sa.Column('uic_number', sa.String(length=64), nullable=True),
    sa.Column('local_ref', sa.String(length=64), nullable=True),
    sa.Column('normalized_local_ref', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('stop_id')
    )
    op.create_index('idx_gtfs_stops_raw_coords', 'gtfs_stops_raw', ['stop_lat', 'stop_lon'], unique=False)
    op.create_index('idx_gtfs_stops_raw_original_stop_id', 'gtfs_stops_raw', ['original_stop_id'], unique=False)
    op.create_index('idx_gtfs_stops_raw_parent_station', 'gtfs_stops_raw', ['parent_station'], unique=False)
    op.create_index('idx_gtfs_stops_raw_uic_number', 'gtfs_stops_raw', ['uic_number'], unique=False)
    op.create_table('osm_nodes',
    sa.Column('osm_node_id', sa.String(length=100), nullable=False),
    sa.Column('osm_local_ref', sa.String(length=100), nullable=True),
    sa.Column('osm_name', sa.String(length=255), nullable=True),
    sa.Column('osm_uic_name', sa.String(length=255), nullable=True),
    sa.Column('osm_uic_ref', sa.String(length=255), nullable=True),
    sa.Column('osm_network', sa.String(length=255), nullable=True),
    sa.Column('osm_public_transport', sa.String(length=255), nullable=True),
    sa.Column('osm_railway', sa.String(length=255), nullable=True),
    sa.Column('osm_amenity', sa.String(length=255), nullable=True),
    sa.Column('osm_aerialway', sa.String(length=255), nullable=True),
    sa.Column('osm_operator', sa.String(length=255), nullable=True),
    sa.Column('osm_operator_wikidata', sa.String(length=100), nullable=True),
    sa.Column('osm_network_wikidata', sa.String(length=100), nullable=True),
    sa.Column('osm_node_type', sa.String(length=50), nullable=True),
    sa.Column('duplicate_group_node_ids', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('osm_lifecycle', sa.String(length=20), nullable=True),
    sa.Column('osm_tags', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('osm_node_id')
    )
    op.create_table('osm_route_relations',
    sa.Column('relation_id', sa.String(length=100), nullable=False),
    sa.Column('route', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('ref', sa.String(length=100), nullable=True),
    sa.Column('operator', sa.String(length=255), nullable=True),
    sa.Column('operator_wikidata', sa.String(length=100), nullable=True),
    sa.Column('network', sa.String(length=255), nullable=True),
    sa.Column('network_wikidata', sa.String(length=100), nullable=True),
    sa.Column('from_name', sa.String(length=255), nullable=True),
    sa.Column('to_name', sa.String(length=255), nullable=True),
    sa.Column('via', sa.String(length=255), nullable=True),
    sa.Column('public_transport_version', sa.String(length=50), nullable=True),
    sa.Column('colour', sa.String(length=64), nullable=True),
    sa.Column('gtfs_route_id', sa.Text(), nullable=True),
    sa.Column('gtfs_trip_id', sa.Text(), nullable=True),
    sa.Column('gtfs_trip_id_sample', sa.Text(), nullable=True),
    sa.Column('gtfs_shape_id', sa.Text(), nullable=True),
    sa.Column('route_master_id', sa.String(length=100), nullable=True),
    sa.Column('family_origin', sa.String(length=50), nullable=True),
    sa.Column('synthetic_family_key', sa.Text(), nullable=True),
    sa.Column('run_id', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('relation_id')
    )
    op.create_index('idx_osm_route_relations_gtfs_route_id', 'osm_route_relations', ['gtfs_route_id'], unique=False)
    op.create_index('idx_osm_route_relations_ref_operator', 'osm_route_relations', ['ref', 'operator'], unique=False)
    op.create_index('idx_osm_route_relations_route', 'osm_route_relations', ['route'], unique=False)
    op.create_geospatial_table('stops_matched',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sloid', sa.Text(), nullable=True),
    sa.Column('stop_type', sa.String(length=50), nullable=True),
    sa.Column('match_type', sa.String(length=50), nullable=True),
    sa.Column('atlas_lat', sa.Float(), nullable=True),
    sa.Column('atlas_lon', sa.Float(), nullable=True),
    sa.Column('osm_node_id', sa.String(length=100), nullable=True),
    sa.Column('osm_lat', sa.Float(), nullable=True),
    sa.Column('osm_lon', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('geom', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_distance_m', 'stops_matched', ['distance_m'], unique=False)
    op.create_index('idx_stop_type_match_type', 'stops_matched', ['stop_type', 'match_type'], unique=False)
    op.create_geospatial_index('idx_stops_geom_gist', 'stops_matched', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_stops_matched_osm_node_id'), 'stops_matched', ['osm_node_id'], unique=False)
    op.create_index(op.f('ix_stops_matched_sloid'), 'stops_matched', ['sloid'], unique=False)
    op.create_table('atlas_stops',
    sa.Column('sloid', sa.Text(), nullable=False),
    sa.Column('uic_ref', sa.Text(), nullable=True),
    sa.Column('atlas_designation', sa.String(length=255), nullable=True),
    sa.Column('atlas_designation_official', sa.String(length=255), nullable=True),
    sa.Column('atlas_business_org_abbr', sa.String(length=100), nullable=True),
    sa.Column('representative_sloid', sa.Text(), nullable=True),
    sa.Column('duplicate_group_sloids', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['atlas_business_org_abbr'], ['atlas_operators.atlas_business_org_abbr'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('sloid')
    )
    op.create_index('idx_atlas_operator', 'atlas_stops', ['atlas_business_org_abbr'], unique=False)
    op.create_index(op.f('ix_atlas_stops_representative_sloid'), 'atlas_stops', ['representative_sloid'], unique=False)
    op.create_index(op.f('ix_atlas_stops_uic_ref'), 'atlas_stops', ['uic_ref'], unique=False)
    op.create_table('line_families',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_family_id', sa.Text(), nullable=False),
    sa.Column('family_origin', sa.String(length=50), nullable=True),
    sa.Column('route_type', sa.String(length=50), nullable=True),
    sa.Column('display_route_id', sa.Text(), nullable=True),
    sa.Column('public_name', sa.Text(), nullable=True),
    sa.Column('ref', sa.String(length=100), nullable=True),
    sa.Column('operator', sa.Text(), nullable=True),
    sa.Column('operator_wikidata', sa.String(length=100), nullable=True),
    sa.Column('network', sa.String(length=255), nullable=True),
    sa.Column('network_wikidata', sa.String(length=100), nullable=True),
    sa.Column('is_non_gtfs', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('gtfs_route_id', sa.Text(), nullable=True),
    sa.Column('normalized_route_id', sa.Text(), nullable=True),
    sa.Column('gtfs_line_id', sa.Text(), nullable=True),
    sa.Column('route_master_id', sa.String(length=100), nullable=True),
    sa.Column('representative_relation_id', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['gtfs_line_id'], ['gtfs_line_families.gtfs_line_id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['representative_relation_id'], ['osm_route_relations.relation_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_family_id', name='uq_line_families_source_family_id')
    )
    op.create_index('idx_line_families_gtfs_route_id', 'line_families', ['gtfs_route_id'], unique=False)
    op.create_index('idx_line_families_source', 'line_families', ['source'], unique=False)
    op.create_table('osm_stops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stop_kind', sa.String(length=20), nullable=False),
    sa.Column('group_kind', sa.String(length=50), nullable=True),
    sa.Column('representative_node_id', sa.String(length=100), nullable=False),
    sa.CheckConstraint("group_kind IS NULL OR group_kind IN ('ptv2_pair_uic_ref', 'ptv2_pair_name', 'tram_stop_pair', 'ptv2_pair_uic_ref_equal_count', 'ptv2_pair_name_equal_count', 'tram_stop_pair_equal_count', 'ptv2_two_sided_stop')", name='ck_osm_stops_group_kind'),
    sa.CheckConstraint("stop_kind IN ('single', 'pair', 'two_sided_stop')", name='ck_osm_stops_stop_kind'),
    sa.ForeignKeyConstraint(['representative_node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_osm_stops_group_kind', 'osm_stops', ['group_kind'], unique=False)
    op.create_index('idx_osm_stops_representative_node_id', 'osm_stops', ['representative_node_id'], unique=False)
    op.create_index('idx_osm_stops_stop_kind', 'osm_stops', ['stop_kind'], unique=False)
    op.create_table('problems',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stop_id', sa.Integer(), nullable=True),
    sa.Column('problem_type', sa.String(length=50), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['stop_id'], ['stops_matched.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_problem_priority', 'problems', ['priority'], unique=False)
    op.create_index('idx_problem_stop_id', 'problems', ['stop_id'], unique=False)
    op.create_index('idx_problem_type', 'problems', ['problem_type'], unique=False)
    op.create_table('gtfs_stop_identity_resolution',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stop_id', sa.Text(), nullable=False),
    sa.Column('source_location_type', sa.String(length=20), nullable=True),
    sa.Column('identity_level', sa.String(length=50), nullable=True),
    sa.Column('resolved_sloid', sa.Text(), nullable=True),
    sa.Column('resolution_method', sa.String(length=100), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('gtfs_stop_lat', sa.Float(), nullable=True),
    sa.Column('gtfs_stop_lon', sa.Float(), nullable=True),
    sa.Column('atlas_lat', sa.Float(), nullable=True),
    sa.Column('atlas_lon', sa.Float(), nullable=True),
    sa.Column('details_json', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['resolved_sloid'], ['atlas_stops.sloid'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['stop_id'], ['gtfs_stops_raw.stop_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stop_id', name='uq_gtfs_stop_identity_resolution_stop_id')
    )
    op.create_index('idx_gtfs_stop_identity_resolution_level', 'gtfs_stop_identity_resolution', ['identity_level'], unique=False)
    op.create_index('idx_gtfs_stop_identity_resolution_method', 'gtfs_stop_identity_resolution', ['resolution_method'], unique=False)
    op.create_index('idx_gtfs_stop_identity_resolution_sloid', 'gtfs_stop_identity_resolution', ['resolved_sloid'], unique=False)
    op.create_table('itineraries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('line_family_id', sa.Integer(), nullable=False),
    sa.Column('source_itinerary_id', sa.Text(), nullable=False),
    sa.Column('direction_id', sa.String(length=20), nullable=True),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('representative_headsign', sa.String(length=255), nullable=True),
    sa.Column('from_name', sa.String(length=255), nullable=True),
    sa.Column('to_name', sa.String(length=255), nullable=True),
    sa.Column('trip_count', sa.Integer(), nullable=True),
    sa.Column('canonical_stop_count', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['line_family_id'], ['line_families.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_itinerary_id', name='uq_itineraries_source_itinerary_id')
    )
    op.create_index('idx_itineraries_line_family', 'itineraries', ['line_family_id'], unique=False)
    op.create_index('idx_itineraries_source', 'itineraries', ['source'], unique=False)
    op.create_table('line_family_matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('gtfs_line_family_id', sa.Integer(), nullable=False),
    sa.Column('osm_line_family_id', sa.Integer(), nullable=False),
    sa.Column('match_method', sa.String(length=255), nullable=True),
    sa.Column('stop_score', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['gtfs_line_family_id'], ['line_families.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['osm_line_family_id'], ['line_families.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gtfs_line_family_id', 'osm_line_family_id', name='uq_line_family_matches_pair')
    )
    op.create_index('idx_line_family_matches_gtfs_family', 'line_family_matches', ['gtfs_line_family_id'], unique=False)
    op.create_index('idx_line_family_matches_osm_family', 'line_family_matches', ['osm_line_family_id'], unique=False)
    op.create_table('osm_stop_members',
    sa.Column('osm_stop_id', sa.Integer(), nullable=False),
    sa.Column('node_id', sa.String(length=100), nullable=False),
    sa.Column('member_role', sa.String(length=20), nullable=False),
    sa.CheckConstraint("member_role IN ('single', 'pair_a', 'pair_b', 'middle', 'side')", name='ck_osm_stop_members_member_role'),
    sa.ForeignKeyConstraint(['node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['osm_stop_id'], ['osm_stops.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('osm_stop_id', 'node_id'),
    sa.UniqueConstraint('node_id', name='uq_osm_stop_members_node_id')
    )
    op.create_table('itinerary_best_overlaps',
    sa.Column('itinerary_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('best_itinerary_id', sa.Integer(), nullable=True),
    sa.Column('matched_stop_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('stop_ratio', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['best_itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('itinerary_id')
    )
    op.create_table('itinerary_matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('line_family_match_id', sa.Integer(), nullable=True),
    sa.Column('gtfs_itinerary_id', sa.Integer(), nullable=False),
    sa.Column('osm_itinerary_id', sa.Integer(), nullable=False),
    sa.Column('stop_score', sa.Float(), nullable=True),
    sa.Column('match_reason', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['gtfs_itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['line_family_match_id'], ['line_family_matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['osm_itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gtfs_itinerary_id', 'osm_itinerary_id', name='uq_itinerary_matches_pair')
    )
    op.create_index('idx_itinerary_matches_gtfs_itinerary', 'itinerary_matches', ['gtfs_itinerary_id'], unique=False)
    op.create_index('idx_itinerary_matches_osm_itinerary', 'itinerary_matches', ['osm_itinerary_id'], unique=False)
    op.create_table('stop_calls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('itinerary_id', sa.Integer(), nullable=False),
    sa.Column('stop_sequence', sa.Integer(), nullable=False),
    sa.Column('source_stop_id', sa.Text(), nullable=True),
    sa.Column('source_sloid', sa.Text(), nullable=True),
    sa.Column('source_sloid_variants', sa.Text(), nullable=True),
    sa.Column('source_node_id', sa.String(length=100), nullable=True),
    sa.Column('canonical_stop_key', sa.Text(), nullable=True),
    sa.Column('stop_label', sa.Text(), nullable=True),
    sa.Column('uic_ref', sa.Text(), nullable=True),
    sa.Column('platform_code', sa.String(length=255), nullable=True),
    sa.Column('stop_lat', sa.Float(), nullable=True),
    sa.Column('stop_lon', sa.Float(), nullable=True),
    sa.Column('member_role', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_node_id'], ['osm_nodes.osm_node_id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_sloid'], ['atlas_stops.sloid'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('itinerary_id', 'stop_sequence', name='uq_stop_calls_itinerary_sequence')
    )
    op.create_index('idx_stop_calls_canonical_stop_key', 'stop_calls', ['canonical_stop_key'], unique=False)
    op.create_index('idx_stop_calls_itinerary_sequence', 'stop_calls', ['itinerary_id', 'stop_sequence'], unique=False)


def downgrade():
    op.drop_index('idx_stop_calls_itinerary_sequence', table_name='stop_calls')
    op.drop_index('idx_stop_calls_canonical_stop_key', table_name='stop_calls')
    op.drop_table('stop_calls')
    op.drop_index('idx_itinerary_matches_osm_itinerary', table_name='itinerary_matches')
    op.drop_index('idx_itinerary_matches_gtfs_itinerary', table_name='itinerary_matches')
    op.drop_table('itinerary_matches')
    op.drop_table('itinerary_best_overlaps')
    op.drop_table('osm_stop_members')
    op.drop_index('idx_line_family_matches_osm_family', table_name='line_family_matches')
    op.drop_index('idx_line_family_matches_gtfs_family', table_name='line_family_matches')
    op.drop_table('line_family_matches')
    op.drop_index('idx_itineraries_source', table_name='itineraries')
    op.drop_index('idx_itineraries_line_family', table_name='itineraries')
    op.drop_table('itineraries')
    op.drop_index('idx_gtfs_stop_identity_resolution_sloid', table_name='gtfs_stop_identity_resolution')
    op.drop_index('idx_gtfs_stop_identity_resolution_method', table_name='gtfs_stop_identity_resolution')
    op.drop_index('idx_gtfs_stop_identity_resolution_level', table_name='gtfs_stop_identity_resolution')
    op.drop_table('gtfs_stop_identity_resolution')
    op.drop_index('idx_problem_type', table_name='problems')
    op.drop_index('idx_problem_stop_id', table_name='problems')
    op.drop_index('idx_problem_priority', table_name='problems')
    op.drop_table('problems')
    op.drop_index('idx_osm_stops_stop_kind', table_name='osm_stops')
    op.drop_index('idx_osm_stops_representative_node_id', table_name='osm_stops')
    op.drop_index('idx_osm_stops_group_kind', table_name='osm_stops')
    op.drop_table('osm_stops')
    op.drop_index('idx_line_families_source', table_name='line_families')
    op.drop_index('idx_line_families_gtfs_route_id', table_name='line_families')
    op.drop_table('line_families')
    op.drop_index(op.f('ix_atlas_stops_uic_ref'), table_name='atlas_stops')
    op.drop_index(op.f('ix_atlas_stops_representative_sloid'), table_name='atlas_stops')
    op.drop_index('idx_atlas_operator', table_name='atlas_stops')
    op.drop_table('atlas_stops')
    op.drop_index(op.f('ix_stops_matched_sloid'), table_name='stops_matched')
    op.drop_index(op.f('ix_stops_matched_osm_node_id'), table_name='stops_matched')
    op.drop_geospatial_index('idx_stops_geom_gist', table_name='stops_matched', postgresql_using='gist', column_name='geom')
    op.drop_index('idx_stop_type_match_type', table_name='stops_matched')
    op.drop_index('idx_distance_m', table_name='stops_matched')
    op.drop_geospatial_table('stops_matched')
    op.drop_index('idx_osm_route_relations_route', table_name='osm_route_relations')
    op.drop_index('idx_osm_route_relations_ref_operator', table_name='osm_route_relations')
    op.drop_index('idx_osm_route_relations_gtfs_route_id', table_name='osm_route_relations')
    op.drop_table('osm_route_relations')
    op.drop_table('osm_nodes')
    op.drop_index('idx_gtfs_stops_raw_uic_number', table_name='gtfs_stops_raw')
    op.drop_index('idx_gtfs_stops_raw_parent_station', table_name='gtfs_stops_raw')
    op.drop_index('idx_gtfs_stops_raw_original_stop_id', table_name='gtfs_stops_raw')
    op.drop_index('idx_gtfs_stops_raw_coords', table_name='gtfs_stops_raw')
    op.drop_table('gtfs_stops_raw')
    op.drop_table('dataset_publication')
    op.drop_index('idx_atlas_operator_sboid', table_name='atlas_operators')
    op.drop_table('atlas_operators')
    op.drop_index('idx_gtfs_line_families_route_type', table_name='gtfs_line_families')
    op.drop_index('idx_gtfs_line_families_route_id_normalized', table_name='gtfs_line_families')
    op.drop_table('gtfs_line_families')
