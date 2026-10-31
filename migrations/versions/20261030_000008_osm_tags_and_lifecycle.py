"""Keep every OSM tag of a stop element, and its lifecycle prefix.

``osm_tags`` holds the complete tag set for the stop popup. ``osm_lifecycle``
holds the prefix of a retired stop tag, such as ``disused``, for elements the
engine reports as disused. Both stay empty until the next import.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261030_000008'
down_revision = '20261017_000007'
branch_labels = None
depends_on = None


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    # The baseline creates every current model column, so fresh databases
    # already have these. Only databases stamped at 000007 need them.
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('osm_nodes')}
    if 'osm_lifecycle' not in existing:
        op.add_column('osm_nodes', sa.Column('osm_lifecycle', sa.String(length=20), nullable=True))
    if 'osm_tags' not in existing:
        op.add_column('osm_nodes', sa.Column('osm_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.drop_column('osm_nodes', 'osm_tags')
    op.drop_column('osm_nodes', 'osm_lifecycle')
