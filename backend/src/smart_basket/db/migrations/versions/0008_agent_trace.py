"""Agent trace: one row per agent run and one per step (ADR 0022, iteration 13 task E1).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = r"""
create table agent_run (
    id                  uuid primary key default uuidv7(),
    agent_name          text not null,
    recommendation_id   uuid references recommendation(id) on delete set null,
    state_json          jsonb not null default '{}'::jsonb,
    status              text not null
                        check (status in ('running', 'waiting_shopper', 'completed', 'failed',
                                          'timed_out')),
    policy_name         text not null,
    model_name          text,
    steps_count         integer not null default 0 check (steps_count >= 0),
    total_latency_ms    integer not null default 0 check (total_latency_ms >= 0),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    finished_at         timestamptz
);
create index agent_run_recommendation_idx on agent_run (recommendation_id);
create index agent_run_created_idx on agent_run (created_at desc);

create table agent_step (
    id                  bigint generated always as identity primary key,
    run_id              uuid not null references agent_run(id) on delete cascade,
    step_number         integer not null check (step_number >= 1),
    observation_json    jsonb not null,
    candidates_json     jsonb not null,
    chosen_action       text not null,
    action_args_json    jsonb not null default '{}'::jsonb,
    confidence          double precision,
    probabilities_json  jsonb,
    retries             integer not null default 0 check (retries >= 0),
    used_default        boolean not null default false,
    result_json         jsonb not null default '{}'::jsonb,
    latency_ms          integer not null default 0 check (latency_ms >= 0),
    error               text,
    created_at          timestamptz not null default now(),
    unique (run_id, step_number)
);
create index agent_step_run_idx on agent_step (run_id, step_number);
"""

DOWNGRADE = r"""
drop table if exists agent_step;
drop table if exists agent_run;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
