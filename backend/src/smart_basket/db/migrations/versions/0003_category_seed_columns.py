"""Seed columns of the canonical category taxonomy (decision 0007, point 2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# `category` is empty in every deployment, so `key` can be `not null` without a default.
UPGRADE = r"""
alter table category
    add column key text not null unique check (key ~ '^[a-z0-9_]+$'),
    add column base_unit text check (base_unit in ('kg', 'l', 'ud')),
    add column default_quantity numeric(12, 4) check (default_quantity > 0),
    add column forms text[] not null default '{}',
    add column is_vague boolean not null default false;
"""

DOWNGRADE = r"""
alter table category
    drop column is_vague,
    drop column forms,
    drop column default_quantity,
    drop column base_unit,
    drop column key;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
