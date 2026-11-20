"""Catalog agent pgvector support and reversible new-leaf proposals (ADR 0022, iteration 14 E2).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-19
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UPGRADE = r"""
alter table canonical_product alter column embedding type vector(768) using embedding::vector(768);
alter table chain_product alter column embedding type vector(768) using embedding::vector(768);

create index canonical_product_embedding_hnsw_idx
    on canonical_product using hnsw (embedding vector_cosine_ops);
create index chain_product_embedding_hnsw_idx
    on chain_product using hnsw (embedding vector_cosine_ops);

create table catalog_leaf_proposal (
    id                  bigint generated always as identity primary key,
    run_id              uuid references agent_run(id) on delete set null,
    category_key        text not null,
    category_name       text not null,
    parent_category_id  integer references category(id) on delete set null,
    signals_json        jsonb not null,
    product_ids_json    jsonb not null,
    status              text not null default 'applied' check (status in ('applied', 'undone')),
    created_at          timestamptz not null default now(),
    undone_at           timestamptz
);
create index catalog_leaf_proposal_status_idx
    on catalog_leaf_proposal (status, created_at desc);
"""

DOWNGRADE = r"""
drop table if exists catalog_leaf_proposal;

drop index if exists chain_product_embedding_hnsw_idx;
drop index if exists canonical_product_embedding_hnsw_idx;

alter table chain_product alter column embedding type vector using embedding::vector;
alter table canonical_product alter column embedding type vector using embedding::vector;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
