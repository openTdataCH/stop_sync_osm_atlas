"""Add route metadata columns to routes_matched

Revision ID: 0fd9b8d7a1c4
Revises: b5fa82492b15
Create Date: 2026-03-19 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0fd9b8d7a1c4'
down_revision = 'b5fa82492b15'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()


def upgrade_():
    with op.batch_alter_table('routes_matched') as batch_op:
        batch_op.add_column(sa.Column('atlas_route_short_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('atlas_route_long_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('osm_route_name', sa.String(length=255), nullable=True))


def downgrade_():
    with op.batch_alter_table('routes_matched') as batch_op:
        batch_op.drop_column('osm_route_name')
        batch_op.drop_column('atlas_route_long_name')
        batch_op.drop_column('atlas_route_short_name')


def upgrade_user_input():
    pass


def downgrade_user_input():
    pass
