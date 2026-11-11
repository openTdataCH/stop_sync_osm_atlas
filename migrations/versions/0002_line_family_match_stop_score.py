"""Keep the stop score of each line link.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

The engine's line_family_matches rows carry ``stop_score``, the best stop ratio
of two itineraries of the two lines. With ``match_method`` it tells what
supports a link: the route ID, the stops, or both.
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('line_family_matches', sa.Column('stop_score', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('line_family_matches', 'stop_score')
