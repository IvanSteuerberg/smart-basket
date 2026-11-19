"""BI views over the catalog agent's runs and leaf proposals (ADR 0022, iteration 14 E6).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-19
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UPGRADE = r"""
create or replace view bi.v_catalog_leaf_proposal as
select
    id,
    run_id,
    category_key,
    category_name,
    parent_category_id,
    status,
    jsonb_array_length(product_ids_json) as product_count,
    jsonb_array_length(signals_json) as signal_count,
    created_at,
    undone_at
from public.catalog_leaf_proposal;

create or replace view bi.v_catalog_agent_summary as
select
    id as run_id,
    status,
    policy_name,
    model_name,
    steps_count,
    total_latency_ms,
    created_at,
    finished_at
from public.agent_run
where agent_name = 'catalog';

grant select on bi.v_catalog_leaf_proposal, bi.v_catalog_agent_summary to bi_reader;
"""

DOWNGRADE = r"""
drop view if exists bi.v_catalog_agent_summary;
drop view if exists bi.v_catalog_leaf_proposal;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
