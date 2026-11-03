"""Transactional schema of the data model (decision 0007, knowledge/architecture/data-model.md).

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Years whose price_history partitions are created up front; the worker creates the next ones.
INITIAL_PARTITION_YEARS = range(2025, 2029)

UPGRADE = r"""
create extension if not exists postgis;
create extension if not exists vector;
create extension if not exists btree_gist;

-- Reference ---------------------------------------------------------------

create table chain (
    id          bigint generated always as identity primary key,
    code        text not null unique check (code ~ '^[a-z0-9_]+$'),
    name        text not null
);

create table zone (
    id          bigint generated always as identity primary key,
    chain_id    bigint not null references chain on delete cascade,
    kind        text not null check (kind in ('chain', 'postal_code', 'warehouse', 'salepoint')),
    code        text not null,
    name        text,
    unique (chain_id, kind, code)
);
-- Exactly one chain-wide zone per chain.
create unique index zone_one_chain_wide on zone (chain_id) where kind = 'chain';

create table store (
    id              bigint generated always as identity primary key,
    chain_id        bigint not null references chain,
    zone_id         bigint not null references zone,
    osm_id          text unique,
    name            text not null,
    format          text,
    address         text,
    geom            geography(point, 4326) not null,
    opening_hours   text,
    is_active       boolean not null default true
);
create index store_geom_idx on store using gist (geom);
create index store_chain_idx on store (chain_id);

create table category (
    id          bigint generated always as identity primary key,
    parent_id   bigint references category,
    name        text not null,
    level       smallint not null check (level between 1 and 5),
    unique (parent_id, name)
);

-- Closure table: one row per (ancestor, descendant), including each category with itself.
create table category_closure (
    ancestor_id     bigint not null references category on delete cascade,
    descendant_id   bigint not null references category on delete cascade,
    depth           smallint not null check (depth >= 0),
    primary key (ancestor_id, descendant_id)
);
create index category_closure_descendant_idx on category_closure (descendant_id);

create table chain_category (
    id          bigint generated always as identity primary key,
    chain_id    bigint not null references chain,
    code        text not null,
    name        text not null,
    parent_code text,
    category_id bigint references category,
    unique (chain_id, code)
);

create table brand (
    id                  bigint generated always as identity primary key,
    name                text not null unique,
    is_private_label    boolean not null default false,
    owner_chain_id      bigint references chain,
    check (not is_private_label or owner_chain_id is not null)
);

-- Products ----------------------------------------------------------------

create table canonical_product (
    id                  bigint generated always as identity primary key,
    category_id         bigint not null references category,
    name                text not null,
    variant_key         text not null default '',
    base_unit           text not null check (base_unit in ('kg', 'l', 'ud')),
    default_quantity    numeric(12, 4) check (default_quantity > 0),
    embedding           vector,
    merged_into         bigint references canonical_product,
    created_at          timestamptz not null default now(),
    check (merged_into is null or merged_into <> id),
    unique (category_id, name, variant_key)
);

create table chain_product (
    id                  bigint generated always as identity primary key,
    chain_id            bigint not null references chain,
    chain_sku           text not null,
    name                text not null,
    brand_id            bigint references brand,
    ean                 text check (ean ~ '^[0-9]{8,14}$'),
    base_quantity       numeric(12, 4) check (base_quantity > 0),
    base_unit           text check (base_unit in ('kg', 'l', 'ud')),
    pack_count          integer not null default 1 check (pack_count >= 1),
    packaging           text,
    dietary_tags        text[] not null default '{}',
    chain_category_id   bigint references chain_category,
    canonical_id        bigint references canonical_product,
    match_confidence    real check (match_confidence between 0 and 1),
    match_method        text check (match_method in ('ean', 'rule', 'embedding', 'review')),
    embedding           vector,
    url                 text,
    first_seen          timestamptz not null default now(),
    last_seen           timestamptz not null default now(),
    is_active           boolean not null default true,
    unique (chain_id, chain_sku),
    check ((base_quantity is null) = (base_unit is null)),
    check ((canonical_id is null) = (match_method is null))
);
create index chain_product_canonical_idx on chain_product (canonical_id) where is_active;
create index chain_product_ean_idx on chain_product (ean) where ean is not null;
create index chain_product_brand_idx on chain_product (brand_id);

create table chain_product_zone (
    chain_product_id    bigint not null references chain_product on delete cascade,
    zone_id             bigint not null references zone on delete cascade,
    first_seen          timestamptz not null default now(),
    last_seen           timestamptz not null default now(),
    is_available        boolean not null default true,
    primary key (chain_product_id, zone_id)
);

create table product_match (
    id                  bigint generated always as identity primary key,
    chain_product_id    bigint not null references chain_product on delete cascade,
    canonical_id        bigint not null references canonical_product,
    method              text not null check (method in ('ean', 'rule', 'embedding', 'review', 'merge')),
    score               real,
    decided_at          timestamptz not null default now()
);
create index product_match_product_idx on product_match (chain_product_id, decided_at);

create table match_review (
    id                  bigint generated always as identity primary key,
    chain_product_id    bigint not null references chain_product on delete cascade,
    candidates          jsonb not null default '[]' check (jsonb_typeof(candidates) = 'array'),
    status              text not null default 'pending'
                        check (status in ('pending', 'accepted', 'rejected', 'new_canonical')),
    created_at          timestamptz not null default now(),
    resolved_at         timestamptz,
    check ((status = 'pending') = (resolved_at is null))
);
create unique index match_review_one_pending on match_review (chain_product_id)
    where status = 'pending';

-- Ingestion ---------------------------------------------------------------

create table ingest_run (
    id                  bigint generated always as identity primary key,
    chain_id            bigint not null references chain,
    zone_id             bigint references zone,
    kind                text not null default 'catalog'
                        check (kind in ('catalog', 'prices', 'promotions', 'flyer', 'stores')),
    started_at          timestamptz not null default now(),
    finished_at         timestamptz,
    status              text not null default 'running'
                        check (status in ('running', 'succeeded', 'failed', 'partial')),
    products_seen       integer not null default 0,
    prices_changed      integer not null default 0,
    errors              jsonb not null default '[]',
    check (finished_at is null or finished_at >= started_at)
);
create index ingest_run_chain_idx on ingest_run (chain_id, started_at desc);

create table raw_response (
    id          bigint generated always as identity primary key,
    run_id      bigint not null references ingest_run on delete cascade,
    url         text not null,
    fetched_at  timestamptz not null default now(),
    status_code smallint,
    sha256      text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    path        text not null
);
create index raw_response_run_idx on raw_response (run_id);

-- Prices ------------------------------------------------------------------

create table price_current (
    chain_product_id    bigint not null references chain_product on delete cascade,
    zone_id             bigint not null references zone,
    price               numeric(10, 2) not null check (price >= 0),
    price_per_unit      numeric(12, 4) check (price_per_unit >= 0),
    valid_from          timestamptz not null,
    last_seen_run       bigint references ingest_run,
    last_seen_at        timestamptz not null default now(),
    primary key (chain_product_id, zone_id)
);

-- Closed intervals [valid_from, valid_to), append-only, partitioned by year on valid_from.
create table price_history (
    id                  bigint generated always as identity,
    chain_product_id    bigint not null references chain_product,
    zone_id             bigint not null references zone,
    price               numeric(10, 2) not null check (price >= 0),
    price_per_unit      numeric(12, 4) check (price_per_unit >= 0),
    valid_from          timestamptz not null,
    valid_to            timestamptz not null,
    run_id              bigint references ingest_run,
    primary key (id, valid_from),
    check (valid_to > valid_from)
) partition by range (valid_from);
create index price_history_lookup_idx on price_history (chain_product_id, zone_id, valid_from)
    include (price, valid_to);
create table price_history_default partition of price_history default;

-- Creates the yearly partition for `year` if missing (called by the worker every year).
create function create_price_history_partition(year integer) returns text
language plpgsql as $$
declare
    part text := format('price_history_y%s', year);
begin
    if to_regclass(part) is null then
        execute format(
            'create table %I partition of price_history for values from (%L) to (%L)',
            part,
            make_timestamptz(year, 1, 1, 0, 0, 0, 'UTC'),
            make_timestamptz(year + 1, 1, 1, 0, 0, 0, 'UTC'));
    end if;
    return part;
end
$$;

-- Promotions --------------------------------------------------------------

create table promotion (
    id                  bigint generated always as identity primary key,
    chain_id            bigint not null references chain,
    kind                text not null check (kind in (
                            'promo_price', 'percent_off', 'nxm', 'second_unit',
                            'volume_tier', 'loyalty_price', 'coupon')),
    promo_price         numeric(10, 2) check (promo_price >= 0),
    percent             numeric(5, 2) check (percent > 0 and percent <= 100),
    amount              numeric(10, 2) check (amount > 0),
    buy_n               smallint check (buy_n >= 2),
    pay_m               smallint check (pay_m >= 1),
    reference_price     numeric(10, 2) check (reference_price >= 0),
    tiers               jsonb,
    requires_loyalty    boolean not null default false,
    coupon_code         text,
    applied_in_price    boolean not null default false,
    priority            smallint not null default 0,
    valid               daterange not null check (not isempty(valid) and not lower_inf(valid)),
    source              text not null check (source in ('web', 'flyer')),
    source_ref          text,
    raw_text            text,
    confidence          real check (confidence between 0 and 1),
    run_id              bigint references ingest_run,
    created_at          timestamptz not null default now(),
    constraint promotion_promo_price check (kind <> 'promo_price'
        or (promo_price is not null and percent is null and buy_n is null and tiers is null)),
    constraint promotion_percent_off check (kind <> 'percent_off'
        or (percent is not null and promo_price is null and buy_n is null and tiers is null)),
    constraint promotion_nxm check (kind <> 'nxm'
        or (buy_n is not null and pay_m is not null and pay_m < buy_n
            and promo_price is null and percent is null and tiers is null)),
    constraint promotion_second_unit check (kind <> 'second_unit'
        or (percent is not null and promo_price is null and buy_n is null and tiers is null)),
    constraint promotion_volume_tier check (kind <> 'volume_tier'
        or (tiers is not null and jsonb_typeof(tiers) = 'array' and jsonb_array_length(tiers) > 0
            and promo_price is null and percent is null and buy_n is null)),
    constraint promotion_loyalty_price check (kind <> 'loyalty_price'
        or (promo_price is not null and requires_loyalty and buy_n is null and tiers is null)),
    constraint promotion_coupon check (kind <> 'coupon'
        or (coupon_code is not null and num_nonnulls(amount, percent) = 1
            and promo_price is null and buy_n is null and tiers is null)),
    constraint promotion_nxm_pair check ((buy_n is null) = (pay_m is null))
);
create index promotion_chain_valid_idx on promotion using gist (chain_id, valid);

create table promotion_target (
    id                  bigint generated always as identity primary key,
    promotion_id        bigint not null references promotion on delete cascade,
    chain_product_id    bigint references chain_product,
    canonical_id        bigint references canonical_product,
    category_id         bigint references category,
    brand_id            bigint references brand,
    constraint promotion_target_exactly_one
        check (num_nonnulls(chain_product_id, canonical_id, category_id, brand_id) = 1)
);
create index promotion_target_promotion_idx on promotion_target (promotion_id);
create index promotion_target_product_idx on promotion_target (chain_product_id)
    where chain_product_id is not null;

create table promotion_zone (
    promotion_id    bigint not null references promotion on delete cascade,
    zone_id         bigint not null references zone on delete cascade,
    primary key (promotion_id, zone_id)
);

-- Reference basket (price index of FR-33) ---------------------------------

create table reference_basket (
    id          bigint generated always as identity primary key,
    code        text not null unique,
    name        text not null
);

create table reference_basket_item (
    basket_id       bigint not null references reference_basket on delete cascade,
    canonical_id    bigint not null references canonical_product,
    quantity        numeric(12, 4) not null check (quantity > 0),
    weight          numeric(8, 4) not null check (weight > 0),
    primary key (basket_id, canonical_id)
);

-- Recommendations (anonymous, NFR-06) -------------------------------------

create table recommendation (
    id                  uuid primary key default uuidv7(),
    created_at          timestamptz not null default now(),
    data_as_of          timestamptz not null,
    engine_version      text not null,
    origin_cell         text,
    travel_mode         text not null check (travel_mode in ('walk', 'car')),
    priority_mode       text check (priority_mode in ('savings', 'balanced', 'time')),
    max_stores          smallint not null check (max_stores between 1 and 3),
    lambda              numeric(8, 4) not null check (lambda >= 0),
    request             jsonb not null,
    result              jsonb not null,
    total_cost          numeric(10, 2) not null,
    reference_cost      numeric(10, 2),
    savings             numeric(10, 2),
    minutes             numeric(8, 2) not null check (minutes >= 0)
);
create index recommendation_created_idx on recommendation (created_at);

create table recommendation_item (
    recommendation_id   uuid not null references recommendation on delete cascade,
    line                smallint not null,
    part                smallint not null default 1 check (part >= 1),
    canonical_id        bigint references canonical_product,
    chain_product_id    bigint references chain_product,
    store_id            bigint references store,
    quantity            numeric(12, 4),
    unit_price          numeric(10, 2),
    line_total          numeric(10, 2),
    promotion_id        bigint references promotion,
    primary key (recommendation_id, line, part)
);

create table not_found_report (
    id                  bigint generated always as identity primary key,
    store_id            bigint not null references store,
    chain_product_id    bigint not null references chain_product,
    reported_at         timestamptz not null default now()
);
create index not_found_report_idx on not_found_report (store_id, chain_product_id);
"""

DOWNGRADE = """
drop table if exists not_found_report, recommendation_item, recommendation,
    reference_basket_item, reference_basket, promotion_zone, promotion_target, promotion,
    price_history, price_current, raw_response, ingest_run, match_review, product_match,
    chain_product_zone, chain_product, canonical_product, brand, chain_category,
    category_closure, category, store, zone, chain cascade;
drop function if exists create_price_history_partition(integer);
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    for year in INITIAL_PARTITION_YEARS:
        op.execute(f"select create_price_history_partition({year})")


def downgrade() -> None:
    op.execute(DOWNGRADE)
