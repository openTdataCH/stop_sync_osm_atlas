"""Allow GTFS stops without a UIC station number.

Generic GTFS feeds carry no UIC numbers, so the engine writes ``gtfs_stops``
rows with ``uic_number`` null. A NOT NULL column made those bundles fail to
load halfway through the import.
"""

from alembic import op
import sqlalchemy as sa

revision = '20261102_000009'
down_revision = '20261030_000008'
branch_labels = None
depends_on = None


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.alter_column('gtfs_stops_raw', 'uic_number', existing_type=sa.String(64), nullable=True)


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    op.alter_column('gtfs_stops_raw', 'uic_number', existing_type=sa.String(64), nullable=False)
