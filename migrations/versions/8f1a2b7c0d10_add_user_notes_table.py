"""add user_notes table and migrate existing persistent notes

Revision ID: 8f1a2b7c0d10
Revises: 71c74d9935a0
Create Date: 2025-10-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f1a2b7c0d10'
down_revision = '71c74d9935a0'
branch_labels = None
depends_on = None


def upgrade():
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
    with op.batch_alter_table('user_notes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_notes_note_type'), ['note_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_osm_node_id'), ['osm_node_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_sloid'), ['sloid'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_notes_user_id'), ['user_id'], unique=False)

    # Migrate existing persistent notes from persistent_data into user_notes (assign user_id=0 if unknown)
    op.execute("""
        INSERT INTO user_notes (sloid, osm_node_id, note_type, user_id, user_email, note, is_persistent, created_at, updated_at)
        SELECT sloid, osm_node_id, note_type, COALESCE(created_by_user_id, 0), created_by_user_email, note, 1, created_at, updated_at
        FROM persistent_data
        WHERE note_type IN ('atlas','osm') AND note IS NOT NULL AND note <> ''
    """)


def downgrade():
    with op.batch_alter_table('user_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_notes_user_id'))
        batch_op.drop_index(batch_op.f('ix_user_notes_sloid'))
        batch_op.drop_index(batch_op.f('ix_user_notes_osm_node_id'))
        batch_op.drop_index(batch_op.f('ix_user_notes_note_type'))
    op.drop_table('user_notes')


