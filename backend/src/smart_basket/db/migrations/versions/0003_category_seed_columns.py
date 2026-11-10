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

# `category` may already have rows (downgrade with a seed loaded), so `key` is added nullable,
# filled from `id`, and only then made `not null` with its unique and check constraints.
UPGRADE = r"""
alter table category
    add column key text,
    add column base_unit text check (base_unit in ('kg', 'l', 'ud')),
    add column default_quantity numeric(12, 4) check (default_quantity > 0),
    add column forms text[] not null default '{}',
    add column is_vague boolean not null default false;

update category set key = 'legacy_' || id where key is null;

alter table category
    alter column key set not null,
    add constraint category_key_key unique (key),
    add constraint category_key_check check (key ~ '^[a-z0-9_]+$');
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
