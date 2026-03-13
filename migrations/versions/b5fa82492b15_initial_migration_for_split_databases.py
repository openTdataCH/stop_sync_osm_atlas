"""Initial migration for split databases

Revision ID: b5fa82492b15
Revises:
Create Date: 2026-02-23 11:05:36.243973

Clean baseline – no downgrade functions since this is a fresh start.
"""
import geoalchemy2
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b5fa82492b15'
down_revision = None
branch_labels = None
depends_on = None


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    pass


# ── Default database (import_db) ────────────────────────────────────────────

def upgrade_():
    # Ensure PostGIS extension is available for geometry columns
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')

    # atlas_stops
    op.create_table('atlas_stops',
        sa.Column('sloid', sa.String(length=100), nullable=False),
        sa.Column('uic_ref', sa.String(length=100), nullable=True),
        sa.Column('atlas_designation', sa.String(length=255), nullable=True),
        sa.Column('atlas_designation_official', sa.String(length=255), nullable=True),
        sa.Column('atlas_business_org_abbr', sa.String(length=100), nullable=True),
        sa.Column('representative_sloid', sa.String(length=100), nullable=True),
        sa.Column('duplicate_group_sloids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('sloid')
    )
    with op.batch_alter_table('atlas_stops') as batch_op:
        batch_op.create_index('idx_atlas_operator', ['atlas_business_org_abbr'], unique=False)
        batch_op.create_index(batch_op.f('ix_atlas_stops_uic_ref'), ['uic_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_atlas_stops_representative_sloid'), ['representative_sloid'], unique=False)

    # osm_nodes
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
        sa.Column('osm_node_type', sa.String(length=50), nullable=True),
        sa.Column('duplicate_group_node_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('osm_node_id')
    )

    # osm_pairs (two-node pair groups from pre-matching grouping)
    op.create_table('osm_pairs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('node_id_1', sa.String(length=100), nullable=False),
        sa.Column('node_id_2', sa.String(length=100), nullable=False),
        sa.Column('group_type', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['node_id_1'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['node_id_2'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('osm_pairs') as batch_op:
        batch_op.create_index(batch_op.f('ix_osm_pairs_node_id_1'), ['node_id_1'], unique=False)
        batch_op.create_index(batch_op.f('ix_osm_pairs_node_id_2'), ['node_id_2'], unique=False)

    # osm_trios (middle stop_position + two side nodes)
    op.create_table('osm_trios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('middle_node_id', sa.String(length=100), nullable=False),
        sa.Column('side_node_id_1', sa.String(length=100), nullable=False),
        sa.Column('side_node_id_2', sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(['middle_node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['side_node_id_1'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['side_node_id_2'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('osm_trios') as batch_op:
        batch_op.create_index(batch_op.f('ix_osm_trios_middle_node_id'), ['middle_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_osm_trios_side_node_id_1'), ['side_node_id_1'], unique=False)
        batch_op.create_index(batch_op.f('ix_osm_trios_side_node_id_2'), ['side_node_id_2'], unique=False)

    # route_atlas_stops
    op.create_table('route_atlas_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('atlas_route_id', sa.String(length=100), nullable=True),
        sa.Column('direction_id', sa.String(length=20), nullable=True),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('stop_sequence', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['sloid'], ['atlas_stops.sloid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('route_atlas_stops') as batch_op:
        batch_op.create_index('idx_atlas_route_dir_seq', ['atlas_route_id', 'direction_id', 'stop_sequence'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_atlas_route_id'), ['atlas_route_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_direction_id'), ['direction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_atlas_stops_sloid'), ['sloid'], unique=False)

    # route_osm_stops
    op.create_table('route_osm_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('osm_route_id', sa.String(length=100), nullable=True),
        sa.Column('direction_id', sa.String(length=20), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('stop_sequence', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['osm_node_id'], ['osm_nodes.osm_node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('route_osm_stops') as batch_op:
        batch_op.create_index('idx_osm_route_dir_seq', ['osm_route_id', 'direction_id', 'stop_sequence'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_direction_id'), ['direction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_route_osm_stops_osm_route_id'), ['osm_route_id'], unique=False)

    # routes_matched
    op.create_table('routes_matched',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('atlas_route_id', sa.String(length=100), nullable=True),
        sa.Column('osm_route_id', sa.String(length=100), nullable=True),
        sa.Column('match_type', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('routes_matched') as batch_op:
        batch_op.create_index(batch_op.f('ix_routes_matched_atlas_route_id'), ['atlas_route_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_routes_matched_osm_route_id'), ['osm_route_id'], unique=False)

    # stops_matched
    op.create_table('stops_matched',
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
        sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('stops_matched') as batch_op:
        batch_op.create_index('idx_distance_m', ['distance_m'], unique=False)
        batch_op.create_index('idx_stop_type_match_type', ['stop_type', 'match_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_stops_matched_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stops_matched_sloid'), ['sloid'], unique=False)
        batch_op.create_index('idx_stops_geom_gist', ['geom'], unique=False, postgresql_using='gist')

    # problems (depends on stops)
    op.create_table('problems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stop_id', sa.Integer(), nullable=True),
        sa.Column('problem_type', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['stop_id'], ['stops_matched.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('problems') as batch_op:
        batch_op.create_index('idx_problem_priority', ['priority'], unique=False)
        batch_op.create_index('idx_problem_stop_id', ['stop_id'], unique=False)
        batch_op.create_index('idx_problem_type', ['problem_type'], unique=False)


# ── user_input database (user_input_db) ─────────────────────────────────────

def upgrade_user_input():
    # persistent_data
    op.create_table('persistent_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('problem_type', sa.String(length=50), nullable=True),
        sa.Column('solution', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_by_user_email', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sloid', 'osm_node_id', 'problem_type', name='unique_problem')
    )
    with op.batch_alter_table('persistent_data') as batch_op:
        batch_op.create_index(batch_op.f('ix_persistent_data_created_by_user_id'), ['created_by_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_persistent_data_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_persistent_data_problem_type'), ['problem_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_persistent_data_sloid'), ['sloid'], unique=False)

    # user_notes
    op.create_table('user_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sloid', sa.String(length=100), nullable=True),
        sa.Column('osm_node_id', sa.String(length=100), nullable=True),
        sa.Column('note_type', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_persistent', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sloid', 'osm_node_id', 'note_type', 'user_id', name='unique_user_note')
    )
    with op.batch_alter_table('user_notes') as batch_op:
        batch_op.create_index(batch_op.f('ix_user_notes_note_type'), ['note_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_sloid'), ['sloid'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_user_id'), ['user_id'], unique=False)

    # users
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False),
        sa.Column('is_email_verified', sa.Boolean(), nullable=False),
        sa.Column('email_verified_at', sa.DateTime(), nullable=True),
        sa.Column('last_verification_sent_at', sa.DateTime(), nullable=True),
        sa.Column('is_totp_enabled', sa.Boolean(), nullable=False),
        sa.Column('totp_secret', sa.Text(), nullable=True),
        sa.Column('backup_codes_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users') as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    # auth_events (depends on users)
    op.create_table('auth_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email_attempted', sa.String(length=255), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auth_events') as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_events_email_attempted'), ['email_attempted'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_events_occurred_at'), ['occurred_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_events_user_id'), ['user_id'], unique=False)
