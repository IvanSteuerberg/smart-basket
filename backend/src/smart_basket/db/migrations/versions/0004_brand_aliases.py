"""Aliases and implied category of the brands (decision 0014, point 3).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# `implies_category` is a taxonomy key but has no foreign key: the taxonomy is reloaded from the
# seed and a stale category may be dropped, while the seed validates the reference on load.
UPGRADE = r"""
alter table brand
    add column aliases text[] not null default '{}',
    add column implies_category text,
    add column match_name boolean not null default true;
"""

DOWNGRADE = r"""
alter table brand
    drop column if exists match_name,
    drop column if exists implies_category,
    drop column if exists aliases;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
