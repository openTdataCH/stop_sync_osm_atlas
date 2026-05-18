"""Collapsed schema baseline migration.

Revision ID: 20260516_000004
Revises:
Create Date: 2026-05-16 13:30:00.000000

This repository is still pre-production. The migration history is intentionally
collapsed into one forward-only baseline describing the current schema only.
Existing development databases should be recreated if they were stamped with an
older revision.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '20260516_000004'
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