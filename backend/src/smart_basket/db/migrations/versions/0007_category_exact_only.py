"""Leaves whose products are never interchangeable (iteration 12, task T4b).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# Leaves with shades (hair dye, lipstick...): a generic line cannot be bought, only a concrete
# product, so the recommender never swaps one product of the leaf for another.
UPGRADE = r"""
alter table category
    add column exact_only boolean not null default false;
"""

DOWNGRADE = r"""
alter table category
    drop column if exists exact_only;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
