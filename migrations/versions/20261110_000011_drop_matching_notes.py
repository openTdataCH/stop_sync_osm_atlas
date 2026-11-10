"""Drop ``stops_matched.matching_notes``.

The engine's free-text note on each match was stored but never read: the
match type already names the rule and branch that decided it.
"""

from alembic import op
import sqlalchemy as sa

revision = '20261110_000011'
down_revision = '20261106_000010'
branch_labels = None
depends_on = None


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    # The baseline builds tables from the current models, so fresh databases never had it.
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('stops_matched')}
    if 'matching_notes' in existing:
        op.drop_column('stops_matched', 'matching_notes')


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.add_column('stops_matched', sa.Column('matching_notes', sa.Text(), nullable=True))
