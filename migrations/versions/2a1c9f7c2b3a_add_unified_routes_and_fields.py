"""add unified routes and fields

Revision ID: 2a1c9f7c2b3a
Revises: 16d64a23de4e
Create Date: 2025-08-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a1c9f7c2b3a'
down_revision = '16d64a23de4e'
branch_labels = None
depends_on = None


def upgrade():
    # This migration is a no-op because all columns and indexes 
    # were already created in the previous migration (16d64a23de4e)
    pass


def downgrade():
    # This migration is a no-op, so downgrade is also a no-op
    # The actual columns/indexes are managed by migration 16d64a23de4e
    pass


