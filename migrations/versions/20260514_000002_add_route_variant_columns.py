"""Add route variant columns for collapsed itinerary stop groups.

Revision ID: 20260514_000002
Revises: 20260513_000001
Create Date: 2026-05-14 16:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260514_000002'
down_revision = '20260513_000001'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    if engine_name not in ('', None):
        return
    upgrade_()


def downgrade(engine_name):
    return


def _has_column(inspector, table_name, column_name):
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(column['name'] == column_name for column in columns)


def upgrade_():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, 'atlas_itinerary_stop_calls', 'resolved_sloid_variants') is False:
        with op.batch_alter_table('atlas_itinerary_stop_calls') as batch_op:
            batch_op.add_column(sa.Column('resolved_sloid_variants', sa.Text(), nullable=True))

    inspector = sa.inspect(bind)
    if _has_column(inspector, 'stop_calls', 'source_sloid_variants') is False:
        with op.batch_alter_table('stop_calls') as batch_op:
            batch_op.add_column(sa.Column('source_sloid_variants', sa.Text(), nullable=True))