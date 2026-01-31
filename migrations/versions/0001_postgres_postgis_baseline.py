"""Postgres/PostGIS baseline schema

Revision ID: 0001_postgres_postgis_baseline
Revises:
Create Date: 2025-12-20

This is a squashed baseline migration intended for a clean Postgres/PostGIS cutover.
It creates the current schema in one step and enables PostGIS.
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '0001_postgres_postgis_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Enable PostGIS
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # --- atlas_stops ---
    op.create_table(
        'atlas_stops',
        sa.Column('sloid', sa.String(length=100), primary_key=True),
        sa.Column('atlas_designation', sa.String(length=255)),
        sa.Column('atlas_designation_official', sa.String(length=255)),
        sa.Column('atlas_business_org_abbr', sa.String(length=100)),
        sa.Column('routes_unified', JSONB),
        sa.Column('atlas_note', sa.Text()),
        sa.Column('atlas_note_is_persistent', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('atlas_note_user_id', sa.Integer()),
        sa.Column('atlas_note_user_email', sa.String(length=255)),
    )
    op.create_index('idx_atlas_operator', 'atlas_stops', ['atlas_business_org_abbr'], unique=False)
    op.create_index('ix_atlas_stops_atlas_note_user_id', 'atlas_stops', ['atlas_note_user_id'], unique=False)

    # --- osm_nodes ---
    op.create_table(
        'osm_nodes',
        sa.Column('osm_node_id', sa.String(length=100), primary_key=True),
        sa.Column('osm_local_ref', sa.String(length=100)),
        sa.Column('osm_name', sa.String(length=255)),
        sa.Column('osm_uic_name', sa.String(length=255)),
        sa.Column('osm_uic_ref', sa.String(length=255)),
        sa.Column('osm_network', sa.String(length=255)),
        sa.Column('osm_public_transport', sa.String(length=255)),
        sa.Column('osm_railway', sa.String(length=255)),
        sa.Column('osm_amenity', sa.String(length=255)),
        sa.Column('osm_aerialway', sa.String(length=255)),
        sa.Column('osm_operator', sa.String(length=255)),
        sa.Column('routes_osm', JSONB),
        sa.Column('osm_note', sa.Text()),
        sa.Column('osm_note_is_persistent', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('osm_note_user_id', sa.Integer()),
        sa.Column('osm_note_user_email', sa.String(length=255)),
    )
    op.create_index('ix_osm_nodes_osm_note_user_id', 'osm_nodes', ['osm_note_user_id'], unique=False)

    # --- persistent_data ---
    op.create_table(
        'persistent_data',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sloid', sa.String(length=100)),
        sa.Column('osm_node_id', sa.String(length=100)),
        sa.Column('problem_type', sa.String(length=50)),
        sa.Column('solution', sa.String(length=500)),
        sa.Column('note_type', sa.String(length=20)),
        sa.Column('note', sa.Text()),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by_user_id', sa.Integer()),
        sa.Column('created_by_user_email', sa.String(length=255)),
        sa.UniqueConstraint('sloid', 'osm_node_id', 'problem_type', 'note_type', name='unique_problem'),
    )
    op.create_index('ix_persistent_data_created_by_user_id', 'persistent_data', ['created_by_user_id'], unique=False)
    op.create_index('ix_persistent_data_note_type', 'persistent_data', ['note_type'], unique=False)
    op.create_index('ix_persistent_data_osm_node_id', 'persistent_data', ['osm_node_id'], unique=False)
    op.create_index('ix_persistent_data_problem_type', 'persistent_data', ['problem_type'], unique=False)
    op.create_index('ix_persistent_data_sloid', 'persistent_data', ['sloid'], unique=False)

    # --- routes_and_directions ---
    op.create_table(
        'routes_and_directions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('direction_id', sa.String(length=20)),
        sa.Column('osm_route_id', sa.String(length=100)),
        sa.Column('osm_nodes_json', JSONB),
        sa.Column('atlas_route_id', sa.String(length=100)),
        sa.Column('atlas_sloids_json', JSONB),
        sa.Column('route_name', sa.String(length=255)),
        sa.Column('route_short_name', sa.String(length=50)),
        sa.Column('route_long_name', sa.String(length=255)),
        sa.Column('route_type', sa.String(length=50)),
        sa.Column('match_type', sa.String(length=50)),
        sa.Column('source', sa.String(length=10)),
        sa.Column('atlas_line_name', sa.String(length=100)),
        sa.Column('direction_uic', sa.String(length=50)),
        sa.Column('route_id_normalized', sa.String(length=100)),
    )
    op.create_index('idx_osm_route_direction', 'routes_and_directions', ['osm_route_id', 'direction_id'], unique=False)
    op.create_index('idx_atlas_route_direction', 'routes_and_directions', ['atlas_route_id', 'direction_id'], unique=False)
    op.create_index('idx_atlas_line_direction_uic', 'routes_and_directions', ['atlas_line_name', 'direction_uic'], unique=False)
    op.create_index('idx_source', 'routes_and_directions', ['source'], unique=False)

    # --- stops ---
    op.create_table(
        'stops',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sloid', sa.String(length=100), index=True),
        sa.Column('stop_type', sa.String(length=50)),
        sa.Column('match_type', sa.String(length=50)),
        sa.Column('manual_is_persistent', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('atlas_lat', sa.Float()),
        sa.Column('atlas_lon', sa.Float()),
        sa.Column('uic_ref', sa.String(length=100), index=True),
        sa.Column('osm_node_id', sa.String(length=100), index=True),
        sa.Column('osm_lat', sa.Float()),
        sa.Column('osm_lon', sa.Float()),
        sa.Column('distance_m', sa.Float()),
        sa.Column('osm_node_type', sa.String(length=50)),
        sa.Column('atlas_duplicate_sloid', sa.String(length=100)),
        # PostGIS geometry column for fast viewport queries (lon/lat, SRID 4326)
        sa.Column('geom', Geometry(geometry_type='POINT', srid=4326), nullable=True),
    )
    op.create_index('idx_atlas_lat_lon', 'stops', ['atlas_lat', 'atlas_lon'], unique=False)
    op.create_index('idx_osm_lat_lon', 'stops', ['osm_lat', 'osm_lon'], unique=False)
    op.create_index('idx_stop_type_match_type', 'stops', ['stop_type', 'match_type'], unique=False)
    op.create_index('idx_distance_m', 'stops', ['distance_m'], unique=False)
    op.create_index('idx_stops_geom_gist', 'stops', ['geom'], unique=False, postgresql_using='gist')

    # --- problems ---
    op.create_table(
        'problems',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stop_id', sa.Integer(), sa.ForeignKey('stops.id', ondelete='CASCADE')),
        sa.Column('problem_type', sa.String(length=50), nullable=False),
        sa.Column('solution', sa.String(length=500)),
        sa.Column('is_persistent', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('created_by_user_id', sa.Integer(), index=True),
        sa.Column('created_by_user_email', sa.String(length=255)),
        sa.Column('priority', sa.Integer()),
    )
    op.create_index('idx_problem_type', 'problems', ['problem_type'], unique=False)
    op.create_index('idx_problem_stop_id', 'problems', ['stop_id'], unique=False)
    op.create_index('idx_problem_priority', 'problems', ['priority'], unique=False)
    # NOTE: created_by_user_id already has index=True on the column definition above,
    # which auto-creates `ix_problems_created_by_user_id`. Creating it again would raise
    # `DuplicateTable` (Postgres treats indexes as relations).

    # --- user_notes ---
    op.create_table(
        'user_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sloid', sa.String(length=100), index=True, nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), index=True, nullable=True),
        sa.Column('note_type', sa.String(length=20), index=True, nullable=False),
        sa.Column('user_id', sa.Integer(), index=True, nullable=False),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_persistent', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('sloid', 'osm_node_id', 'note_type', 'user_id', name='unique_user_note'),
    )


def downgrade():
    # Baseline is intended for clean cutover; keep downgrade minimal.
    op.drop_table('user_notes')
    op.drop_table('problems')
    op.drop_index('idx_stops_geom_gist', table_name='stops')
    op.drop_table('stops')
    op.drop_table('routes_and_directions')
    op.drop_table('persistent_data')
    op.drop_table('osm_nodes')
    op.drop_table('atlas_stops')
    op.execute("DROP EXTENSION IF EXISTS postgis;")


