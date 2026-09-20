"""Record the active imported bundle independently of replaceable result tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260911_000005'
down_revision = '20260516_000004'
branch_labels = None
depends_on = None


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    if sa.inspect(op.get_bind()).has_table('dataset_publication'):
        return
    op.create_table(
        'dataset_publication',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.String(100), nullable=False),
        sa.Column('manifest', postgresql.JSONB(), nullable=False),
    )


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.drop_table('dataset_publication')
