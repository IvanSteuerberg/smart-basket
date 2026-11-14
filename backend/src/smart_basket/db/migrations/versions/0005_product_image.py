"""Product photo URL of the chain catalog (iteration 12, task E1).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# The photo is loaded straight from the chain's CDN, so only an URL is kept; products without a
# usable one leave the column null.
UPGRADE = r"""
alter table chain_product
    add column image_url text;
"""

DOWNGRADE = r"""
alter table chain_product
    drop column if exists image_url;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
