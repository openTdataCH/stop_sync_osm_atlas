"""Replace additive global stats buckets with exact materialized filter rows.

Revision ID: 7c9f3d2a9b14
Revises: e04c24ed3e50
Create Date: 2026-04-10 11:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c9f3d2a9b14'
down_revision = 'e04c24ed3e50'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    if engine_name not in ('', None):
        return
    upgrade_()


def downgrade(engine_name):
    if engine_name not in ('', None):
        return
    downgrade_()


def upgrade_():
    op.create_table(
        'global_stats_filter_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('osm_stop_id', sa.Integer(), nullable=True),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('atlas_operator', sa.String(length=100), nullable=True),
        sa.Column('atlas_duplicate', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('stop_kind', sa.String(length=20), nullable=True),
        sa.Column('osm_group_kind', sa.String(length=50), nullable=True),
        sa.Column('stop_type', sa.String(length=50), nullable=True),
        sa.Column('effective_stop_type', sa.String(length=50), nullable=True),
        sa.Column('match_type', sa.String(length=50), nullable=True),
        sa.Column('is_ferry_terminal', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_tram_stop', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_station', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_platform', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_stop_position', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_aerialway_station', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('global_stats_filter_rows') as batch_op:
        batch_op.create_index(batch_op.f('ix_global_stats_filter_rows_atlas_operator'), ['atlas_operator'], unique=False)
        batch_op.create_index('idx_gsfr_scope_effective', ['scope', 'effective_stop_type'], unique=False)
        batch_op.create_index('idx_gsfr_match_type', ['match_type'], unique=False)
        batch_op.create_index('idx_gsfr_group_kind', ['osm_group_kind'], unique=False)
        batch_op.create_index('idx_gsfr_atlas_duplicate', ['atlas_duplicate'], unique=False)
        batch_op.create_index('idx_gsfr_sloid', ['sloid'], unique=False)
        batch_op.create_index('idx_gsfr_osm_node_id', ['osm_node_id'], unique=False)
        batch_op.create_index('idx_gsfr_osm_stop_id', ['osm_stop_id'], unique=False)
        batch_op.create_index('idx_gsfr_stop_type', ['stop_type'], unique=False)
        batch_op.create_index('idx_gsfr_stop_kind', ['stop_kind'], unique=False)

    op.drop_table('global_stats_buckets')


def downgrade_():
    op.create_table(
        'global_stats_buckets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('atlas_operator', sa.String(length=100), nullable=True),
        sa.Column('atlas_duplicate', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('osm_group_kind', sa.String(length=50), nullable=True),
        sa.Column('effective_stop_type', sa.String(length=50), nullable=True),
        sa.Column('match_type', sa.String(length=50), nullable=True),
        sa.Column('is_ferry_terminal', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_tram_stop', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_station', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_platform', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_stop_position', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_aerialway_station', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('total_atlas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('matched_atlas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('unmatched_atlas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('matched_pairs', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_osm_stops', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('matched_osm_stops', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_osm_nodes', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('global_stats_buckets') as batch_op:
        batch_op.create_index(batch_op.f('ix_global_stats_buckets_atlas_operator'), ['atlas_operator'], unique=False)
        batch_op.create_index('idx_gsb_scope_effective', ['scope', 'effective_stop_type'], unique=False)
        batch_op.create_index('idx_gsb_match_type', ['match_type'], unique=False)
        batch_op.create_index('idx_gsb_group_kind', ['osm_group_kind'], unique=False)
        batch_op.create_index('idx_gsb_atlas_duplicate', ['atlas_duplicate'], unique=False)

    op.drop_table('global_stats_filter_rows')
