"""Add ATLAS operators table.

Revision ID: 5f0a9d7b2c41
Revises: e04c24ed3e50
Create Date: 2026-05-10 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f0a9d7b2c41'
down_revision = 'e04c24ed3e50'
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

    # Legacy imports may have stored blank strings instead of NULL. Normalize
    # them before backfilling atlas_operators or adding the foreign key.
    op.execute(
        """
        UPDATE atlas_stops
        SET atlas_business_org_abbr = NULL
        WHERE atlas_business_org_abbr IS NOT NULL
          AND trim(atlas_business_org_abbr) = ''
        """
    )

    op.create_table(
        'atlas_operators',
        sa.Column('atlas_business_org_abbr', sa.String(length=100), nullable=False),
        sa.Column('sboid', sa.String(length=100), nullable=True),
        sa.Column('atlas_business_org_name', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('atlas_business_org_abbr'),
        sa.UniqueConstraint('sboid'),
    )
    with op.batch_alter_table('atlas_operators') as batch_op:
        batch_op.create_index('idx_atlas_operator_sboid', ['sboid'], unique=False)

    if bind is not None and bind.dialect.name == 'postgresql':
        op.execute(
            """
            INSERT INTO atlas_operators (atlas_business_org_abbr)
            SELECT DISTINCT atlas_business_org_abbr
            FROM atlas_stops
            WHERE atlas_business_org_abbr IS NOT NULL AND atlas_business_org_abbr <> ''
            ON CONFLICT (atlas_business_org_abbr) DO NOTHING
            """
        )
    else:
        atlas_stops = sa.table(
            'atlas_stops',
            sa.column('atlas_business_org_abbr', sa.String()),
        )
        atlas_operators = sa.table(
            'atlas_operators',
            sa.column('atlas_business_org_abbr', sa.String()),
        )
        rows = bind.execute(
            sa.select(atlas_stops.c.atlas_business_org_abbr)
            .where(atlas_stops.c.atlas_business_org_abbr.isnot(None))
            .where(atlas_stops.c.atlas_business_org_abbr != '')
            .distinct()
        ).fetchall()
        if rows:
            bind.execute(
                atlas_operators.insert(),
                [
                    {'atlas_business_org_abbr': row[0]}
                    for row in rows
                    if row and row[0]
                ],
            )

    with op.batch_alter_table('atlas_stops') as batch_op:
        batch_op.create_foreign_key(
            'fk_atlas_stops_operator_abbr',
            'atlas_operators',
            ['atlas_business_org_abbr'],
            ['atlas_business_org_abbr'],
            ondelete='SET NULL',
        )