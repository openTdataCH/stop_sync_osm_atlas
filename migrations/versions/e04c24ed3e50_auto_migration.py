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
        'gtfs_stops',
        sa.Column('stop_id', sa.String(length=255), nullable=False),
        sa.Column('stop_name', sa.String(length=255), nullable=True),
        sa.Column('uic_number', sa.String(length=64), nullable=False),
        sa.Column('local_ref', sa.String(length=64), nullable=True),
        sa.Column('normalized_local_ref', sa.String(length=64), nullable=True),
        sa.Column('stop_lat', sa.Float(), nullable=False),
        sa.Column('stop_lon', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('stop_id'),
    )
    with op.batch_alter_table('gtfs_stops') as batch_op:
        batch_op.create_index('idx_gtfs_stops_coords', ['stop_lat', 'stop_lon'], unique=False)
        batch_op.create_index('idx_gtfs_stops_uic_number', ['uic_number'], unique=False)

    op.create_table(
        'gtfs_atlas_stop_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stop_id', sa.String(length=255), nullable=True),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('stop_type', sa.String(length=50), nullable=False),
        sa.Column('match_method', sa.String(length=50), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('gtfs_stop_lat', sa.Float(), nullable=True),
        sa.Column('gtfs_stop_lon', sa.Float(), nullable=True),
        sa.Column('atlas_lat', sa.Float(), nullable=True),
        sa.Column('atlas_lon', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['stop_id'], ['gtfs_stops.stop_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sloid'], ['atlas_stops.sloid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stop_id', 'sloid', name='uq_gtfs_atlas_stop_matches_stop_sloid'),
    )
    with op.batch_alter_table('gtfs_atlas_stop_matches') as batch_op:
        batch_op.create_index('idx_gtfs_atlas_stop_matches_stop_type', ['stop_type'], unique=False)
        batch_op.create_index('idx_gtfs_atlas_stop_matches_method', ['match_method'], unique=False)
        batch_op.create_index('idx_gtfs_atlas_stop_matches_sloid', ['sloid'], unique=False)
        batch_op.create_index('idx_gtfs_atlas_stop_matches_stop_id', ['stop_id'], unique=False)

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
        'atlas_routes',
        sa.Column('route_id', sa.String(length=100), nullable=False),
        sa.Column('route_id_normalized', sa.String(length=100), nullable=True),
        sa.Column('agency_id', sa.String(length=100), nullable=True),
        sa.Column('route_short_name', sa.String(length=255), nullable=True),
        sa.Column('route_long_name', sa.String(length=255), nullable=True),
        sa.Column('route_desc', sa.Text(), nullable=True),
        sa.Column('route_type', sa.String(length=50), nullable=True),
        sa.Column('run_id', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('route_id')
    )

    op.create_table(
        'atlas_route_directions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('route_id', sa.String(length=100), nullable=True),
        sa.Column('direction_id', sa.String(length=20), nullable=True),
        sa.Column('representative_headsign', sa.String(length=255), nullable=True),
        sa.Column('direction_label', sa.String(length=255), nullable=True),
        sa.Column('trip_count', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['route_id'], ['atlas_routes.route_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'osm_routes',
        sa.Column('relation_id', sa.String(length=100), nullable=False),
        sa.Column('route', sa.String(length=100), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('ref', sa.String(length=100), nullable=True),
        sa.Column('operator', sa.String(length=255), nullable=True),
        sa.Column('network', sa.String(length=255), nullable=True),
        sa.Column('gtfs_route_id', sa.String(length=255), nullable=True),
        sa.Column('run_id', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('relation_id')
    )

    op.create_table(
        'osm_route_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('relation_id', sa.String(length=100), nullable=True),
        sa.Column('tag_key', sa.String(length=255), nullable=True),
        sa.Column('tag_value', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['relation_id'], ['osm_routes.relation_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
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
        sa.UniqueConstraint('atlas_route_id', 'direction_id', 'sloid', 'stop_sequence', name='uq_route_atlas_stops_seq')
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
        sa.UniqueConstraint('osm_route_id', 'direction_id', 'osm_node_id', 'stop_sequence', name='uq_route_osm_stops_seq')
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
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('match_reason', sa.String(length=255), nullable=True),
        sa.Column('match_version', sa.String(length=50), nullable=True),
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

    op.create_table(
        'route_problems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('problem_type', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('atlas_route_id', sa.String(length=100), nullable=True),
        sa.Column('osm_route_id', sa.String(length=100), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('problems') as batch_op:
        batch_op.create_index('idx_problem_priority', ['priority'], unique=False)
        batch_op.create_index('idx_problem_stop_id', ['stop_id'], unique=False)
        batch_op.create_index('idx_problem_type', ['problem_type'], unique=False)

    # Table 'global_stats_buckets' removed as requested.

