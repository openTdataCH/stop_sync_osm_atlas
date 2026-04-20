"""Baseline migration for import_db schema.

Revision ID: e04c24ed3e50
Revises:
Create Date: 2026-04-08 22:17:05.865390

This is a forward-only baseline migration. It intentionally contains only
the current import_db schema and excludes historical user_input_db tables.
"""

import geoalchemy2
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e04c24ed3e50'
down_revision = None
branch_labels = None
depends_on = None


def upgrade(engine_name):
    if engine_name not in ('', None):
        return
    upgrade_()


def downgrade(engine_name):
    # Forward-only baseline: downgrades are intentionally unsupported.
    return


def upgrade_():
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS postgis')

    op.create_table(
        'atlas_stops',
        sa.Column('sloid', sa.String(length=100), nullable=False),
        sa.Column('uic_ref', sa.String(length=100), nullable=True),
        sa.Column('atlas_designation', sa.String(length=255), nullable=True),
        sa.Column('atlas_designation_official', sa.String(length=255), nullable=True),
        sa.Column('atlas_business_org_abbr', sa.String(length=100), nullable=True),
        sa.Column('representative_sloid', sa.String(length=100), nullable=True),
        sa.Column('duplicate_group_sloids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('sloid'),
    )
    with op.batch_alter_table('atlas_stops') as batch_op:
        batch_op.create_index('idx_atlas_operator', ['atlas_business_org_abbr'], unique=False)
        batch_op.create_index(batch_op.f('ix_atlas_stops_uic_ref'), ['uic_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_atlas_stops_representative_sloid'), ['representative_sloid'], unique=False)

    op.create_table(
        'osm_nodes',
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
        sa.Column('osm_node_type', sa.String(length=50), nullable=True),
        sa.Column('duplicate_group_node_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('osm_node_id'),
    )

    op.create_table(
        'osm_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stop_kind', sa.String(length=20), nullable=False),
        sa.Column('group_kind', sa.String(length=50), nullable=True),
        sa.Column('representative_node_id', sa.String(length=100), nullable=False),
        sa.CheckConstraint("stop_kind IN ('single', 'pair', 'trio')", name='ck_osm_stops_stop_kind'),
        sa.CheckConstraint(
            "group_kind IS NULL OR group_kind IN ('osm_pair_uic', 'osm_pair_name', 'osm_pair_tram', "
            "'osm_pair_uic_equal_15m', 'osm_pair_name_equal_15m', 'osm_pair_tram_equal_15m', 'osm_trio')",
            name='ck_osm_stops_group_kind',
        ),
        sa.ForeignKeyConstraint(['representative_node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('osm_stops') as batch_op:
        batch_op.create_index('idx_osm_stops_stop_kind', ['stop_kind'], unique=False)
        batch_op.create_index('idx_osm_stops_group_kind', ['group_kind'], unique=False)
        batch_op.create_index('idx_osm_stops_representative_node_id', ['representative_node_id'], unique=False)

    op.create_table(
        'osm_stop_members',
        sa.Column('osm_stop_id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.String(length=100), nullable=False),
        sa.Column('member_role', sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "member_role IN ('single', 'pair_a', 'pair_b', 'trio_middle', 'trio_side')",
            name='ck_osm_stop_members_member_role',
        ),
        sa.ForeignKeyConstraint(['osm_stop_id'], ['osm_stops.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('osm_stop_id', 'node_id'),
        sa.UniqueConstraint('node_id', name='uq_osm_stop_members_node_id'),
    )

    op.create_table(
        'route_atlas_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('atlas_route_id', sa.String(length=100), nullable=True),
        sa.Column('direction_id', sa.String(length=20), nullable=True),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('stop_sequence', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['sloid'], ['atlas_stops.sloid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('route_atlas_stops') as batch_op:
        batch_op.create_index('idx_atlas_route_dir_seq', ['atlas_route_id', 'direction_id', 'stop_sequence'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_atlas_route_id'), ['atlas_route_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_direction_id'), ['direction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_sloid'), ['sloid'], unique=False)

    op.create_table(
        'route_osm_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('osm_route_id', sa.String(length=100), nullable=True),
        sa.Column('direction_id', sa.String(length=20), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('stop_sequence', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['osm_node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('route_osm_stops') as batch_op:
        batch_op.create_index('idx_osm_route_dir_seq', ['osm_route_id', 'direction_id', 'stop_sequence'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_direction_id'), ['direction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_osm_route_id'), ['osm_route_id'], unique=False)

    op.create_table(
        'routes_matched',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('atlas_route_id', sa.String(length=100), nullable=True),
        sa.Column('osm_route_id', sa.String(length=100), nullable=True),
        sa.Column('match_type', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('routes_matched') as batch_op:
        batch_op.create_index(batch_op.f('ix_routes_matched_atlas_route_id'), ['atlas_route_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_routes_matched_osm_route_id'), ['osm_route_id'], unique=False)

    op.create_table(
        'stops_matched',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('stop_type', sa.String(length=50), nullable=True),
        sa.Column('match_type', sa.String(length=50), nullable=True),
        sa.Column('atlas_lat', sa.Float(), nullable=True),
        sa.Column('atlas_lon', sa.Float(), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('osm_lat', sa.Float(), nullable=True),
        sa.Column('osm_lon', sa.Float(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('matching_notes', sa.Text(), nullable=True),
        sa.Column(
            'geom',
            geoalchemy2.types.Geometry(
                geometry_type='POINT',
                srid=4326,
                dimension=2,
                from_text='ST_GeomFromEWKT',
                name='geometry',
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('stops_matched') as batch_op:
        batch_op.create_index('idx_distance_m', ['distance_m'], unique=False)
        batch_op.create_index('idx_stop_type_match_type', ['stop_type', 'match_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_stops_matched_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stops_matched_sloid'), ['sloid'], unique=False)
        batch_op.create_index('idx_stops_geom_gist', ['geom'], unique=False, postgresql_using='gist')

    op.create_table(
        'problems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stop_id', sa.Integer(), nullable=True),
        sa.Column('problem_type', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['stop_id'], ['stops_matched.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('problems') as batch_op:
        batch_op.create_index('idx_problem_priority', ['priority'], unique=False)
        batch_op.create_index('idx_problem_stop_id', ['stop_id'], unique=False)
        batch_op.create_index('idx_problem_type', ['problem_type'], unique=False)

    # Table 'global_stats_buckets' removed as requested.

