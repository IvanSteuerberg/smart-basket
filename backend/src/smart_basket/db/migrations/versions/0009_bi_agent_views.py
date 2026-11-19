"""BI views over agent_run and agent_step (ADR 0022, iteration 13 task E10).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-19
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE = r"""
create or replace view bi.v_agent_run as
select
    id,
    agent_name,
    recommendation_id,
    status,
    policy_name,
    model_name,
    (policy_name = 'default') as is_ablation,
    steps_count,
    total_latency_ms,
    created_at,
    finished_at
from public.agent_run;

create or replace view bi.v_agent_step as
select
    id,
    run_id,
    step_number,
    (observation_json->>'kind') as observation_kind,
    chosen_action,
    confidence,
    retries,
    used_default,
    coalesce((result_json->>'overridden')::boolean, false) as overridden,
    latency_ms,
    (error is not null) as has_error,
    created_at
from public.agent_step;

grant select on bi.v_agent_run, bi.v_agent_step to bi_reader;
"""

DOWNGRADE = r"""
drop view if exists bi.v_agent_step;
drop view if exists bi.v_agent_run;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
