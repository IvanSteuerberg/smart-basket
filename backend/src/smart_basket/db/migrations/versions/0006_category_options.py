"""Choice options offered by a vague taxonomy category (iteration 12, task E6a).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# The seed loader writes the explicit list; a vague node without one derives its options from
# its children at request time, so an empty array means "no explicit list".
UPGRADE = r"""
alter table category
    add column options text[] not null default '{}';
"""

DOWNGRADE = r"""
alter table category
    drop column if exists options;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
