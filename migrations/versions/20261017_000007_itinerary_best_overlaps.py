"""Store each itinerary's highest stop overlap with the other source.

The importer fills this table with every snapshot. Until the next import after
this upgrade it stays empty, and route cards say the overlap is not computed.
"""

from alembic import op
import sqlalchemy as sa

revision = '20261017_000007'
down_revision = '20260911_000006'
branch_labels = None
depends_on = None


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    # The baseline creates every current model table, so fresh databases
    # already have this one. Only databases stamped at 000006 need it.
    if sa.inspect(op.get_bind()).has_table('itinerary_best_overlaps'):
        return
    op.create_table(
        'itinerary_best_overlaps',
        sa.Column('itinerary_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('best_itinerary_id', sa.Integer(), nullable=True),
        sa.Column('matched_stop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('stop_ratio', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['best_itinerary_id'], ['itineraries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('itinerary_id'),
    )


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.drop_table('itinerary_best_overlaps')
