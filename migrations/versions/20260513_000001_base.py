"""Route product baseline migration.

Revision ID: 20260513_000001
Revises:
Create Date: 2026-05-13 12:00:00.000000

This repository is pre-production and the import schema is rebuilt from scratch.
The migration history is therefore intentionally flattened to a single
forward-only baseline describing the current schema only.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '20260513_000001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade(engine_name):
    if engine_name not in ('', None):
        return
    upgrade_()


def downgrade(engine_name):
    return


def upgrade_():
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS postgis')

    import backend.models  # noqa: F401
    from backend.extensions import db

    db.Model.metadata.create_all(bind=bind, checkfirst=True)