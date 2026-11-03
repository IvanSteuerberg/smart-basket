"""BI star schema in the `bi` schema, the as-of price view and the read-only role (decision 0007).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Read-only role for Metabase. The login role is created by infra/db/initdb on first start
# (with its password); here it is created without login if it does not exist yet (CI, tests).
BI_READER_ROLE = "bi_reader"

UPGRADE = r"""
create schema bi;

-- Dimensions --------------------------------------------------------------
-- Type 1 for now; valid_from / valid_to / is_current are ready for type 2.

create table bi.dim_date (
    date_key        integer primary key,              -- yyyymmdd
    date            date not null unique,
    year            smallint not null,
    quarter         smallint not null,
    month           smallint not null,
    month_name      text not null,
    day             smallint not null,
    iso_year        smallint not null,
    iso_week        smallint not null,
    iso_dow         smallint not null,                -- 1 = Monday
    day_name        text not null,
    is_weekend      boolean not null,
    is_holiday_leon boolean not null default false,
    holiday_name    text
);

create table bi.dim_chain (
    chain_key   integer generated always as identity primary key,
    chain_id    bigint not null unique,
    code        text not null,
    name        text not null
);

create table bi.dim_zone (
    zone_key    integer generated always as identity primary key,
    zone_id     bigint not null unique,
    chain_key   integer not null references bi.dim_chain,
    kind        text not null,
    code        text not null
);

create table bi.dim_store (
    store_key   integer generated always as identity primary key,
    store_id    bigint not null,
    chain_key   integer not null references bi.dim_chain,
    name        text not null,
    format      text,
    longitude   double precision,
    latitude    double precision,
    valid_from  date not null default '1900-01-01',
    valid_to    date,
    is_current  boolean not null default true,
    unique (store_id, valid_from)
);

create table bi.dim_category (
    category_key    integer generated always as identity primary key,
    category_id     bigint not null unique,
    name            text not null,
    level1          text,
    level2          text,
    level3          text
);

create table bi.dim_brand (
    brand_key   integer generated always as identity primary key,
    brand_id    bigint,                               -- null row = "no brand"
    name        text not null,
    brand_type  text not null check (brand_type in ('private_label', 'manufacturer', 'unknown')),
    valid_from  date not null default '1900-01-01',
    valid_to    date,
    is_current  boolean not null default true,
    unique nulls not distinct (brand_id, valid_from)
);

create table bi.dim_product (
    product_key     integer generated always as identity primary key,
    canonical_id    bigint not null,
    name            text not null,
    variant_key     text not null default '',
    base_unit       text not null,
    category_key    integer references bi.dim_category,
    valid_from      date not null default '1900-01-01',
    valid_to        date,
    is_current      boolean not null default true,
    unique (canonical_id, valid_from)
);

create table bi.dim_promotion_kind (
    promotion_kind_key  smallint primary key,
    kind                text not null unique,
    name_es             text not null
);
insert into bi.dim_promotion_kind values
    (0, 'none', 'Sin promoción'),
    (1, 'promo_price', 'Precio rebajado'),
    (2, 'percent_off', 'Descuento porcentual'),
    (3, 'nxm', 'NxM'),
    (4, 'second_unit', 'Segunda unidad'),
    (5, 'volume_tier', 'Descuento por volumen'),
    (6, 'loyalty_price', 'Precio con tarjeta'),
    (7, 'coupon', 'Cupón');

create table bi.dim_reference_basket (
    basket_key  integer generated always as identity primary key,
    basket_id   bigint not null unique,
    code        text not null,
    name        text not null
);

-- Facts (aggregated, refreshed for a recent window after each ingestion) --

create table bi.fact_price_category_daily (
    date_key            integer not null references bi.dim_date,
    category_key        integer not null references bi.dim_category,
    chain_key           integer not null references bi.dim_chain,
    brand_type          text not null check (brand_type in ('private_label', 'manufacturer', 'unknown')),
    zone_key            integer not null references bi.dim_zone,
    base_unit           text not null check (base_unit in ('kg', 'l', 'ud')),
    mean_price_per_unit     numeric(12, 4) not null,
    median_price_per_unit   numeric(12, 4) not null,
    min_price_per_unit      numeric(12, 4) not null,
    max_price_per_unit      numeric(12, 4) not null,
    products            integer not null check (products >= 0),
    products_on_promotion   integer not null check (products_on_promotion >= 0),
    primary key (date_key, category_key, chain_key, brand_type, zone_key, base_unit)
);

create table bi.fact_price_index_daily (
    date_key        integer not null references bi.dim_date,
    chain_key       integer not null references bi.dim_chain,
    basket_key      integer not null references bi.dim_reference_basket,
    index_value     numeric(8, 2) not null,           -- base 100
    basket_cost     numeric(10, 2) not null,
    coverage        numeric(5, 4) not null check (coverage between 0 and 1),
    items           integer not null,
    primary key (date_key, chain_key, basket_key)
);

create table bi.fact_promotion_daily (
    date_key            integer not null references bi.dim_date,
    chain_key           integer not null references bi.dim_chain,
    category_key        integer not null references bi.dim_category,
    promotion_kind_key  smallint not null references bi.dim_promotion_kind,
    promotions          integer not null,
    products            integer not null,
    mean_depth          numeric(5, 2),                -- percent off the base price
    max_depth           numeric(5, 2),
    loyalty_share       numeric(5, 4) check (loyalty_share between 0 and 1),
    primary key (date_key, chain_key, category_key, promotion_kind_key)
);

create table bi.fact_recommendation (
    recommendation_id   uuid primary key,
    date_key            integer not null references bi.dim_date,
    engine_version      text not null,
    travel_mode         text not null,
    priority_mode       text,
    max_stores          smallint not null,
    stores              smallint not null,
    lambda              numeric(8, 4) not null,
    lines               smallint not null,
    missing_lines       smallint not null,
    total_cost          numeric(10, 2) not null,
    reference_cost      numeric(10, 2),
    savings             numeric(10, 2),
    minutes             numeric(8, 2) not null,
    data_age_hours      numeric(8, 2)
);

create table bi.fact_recommendation_line (
    recommendation_id   uuid not null references bi.fact_recommendation on delete cascade,
    line                smallint not null,
    part                smallint not null default 1,
    date_key            integer not null references bi.dim_date,
    product_key         integer references bi.dim_product,
    chain_key           integer references bi.dim_chain,
    store_key           integer references bi.dim_store,
    promotion_kind_key  smallint not null default 0 references bi.dim_promotion_kind,
    quantity            numeric(12, 4),
    unit_price          numeric(10, 2),
    line_total          numeric(10, 2),
    primary key (recommendation_id, line, part)
);

create table bi.fact_usage_daily (
    date_key    integer not null references bi.dim_date,
    event       text not null,
    events      integer not null check (events >= 0),
    primary key (date_key, event)
);

-- Product-level price evolution (FR-31): the price in force at the end of each day,
-- from the closed intervals of price_history plus the open interval of price_current.
create view bi.v_price_asof as
with intervals as (
    select chain_product_id, zone_id, price, price_per_unit, valid_from, valid_to
    from public.price_history
    union all
    select chain_product_id, zone_id, price, price_per_unit, valid_from, null
    from public.price_current
)
select
    d.date_key,
    d.date,
    cp.canonical_id,
    i.chain_product_id,
    cp.chain_id,
    i.zone_id,
    cp.brand_id,
    i.price,
    i.price_per_unit
from bi.dim_date d
join intervals i
    on i.valid_from < ((d.date + 1)::timestamp at time zone 'Europe/Madrid')
   and (i.valid_to is null
        or i.valid_to >= ((d.date + 1)::timestamp at time zone 'Europe/Madrid'))
join public.chain_product cp on cp.id = i.chain_product_id;

-- Fills dim_date for [first_day, last_day]; holidays are set by a later job.
create function bi.fill_dim_date(first_day date, last_day date) returns integer
language sql as $$
    insert into bi.dim_date (date_key, date, year, quarter, month, month_name, day,
                             iso_year, iso_week, iso_dow, day_name, is_weekend)
    select to_char(d, 'YYYYMMDD')::integer, d,
           extract(year from d), extract(quarter from d), extract(month from d),
           (array['enero','febrero','marzo','abril','mayo','junio','julio','agosto',
                  'septiembre','octubre','noviembre','diciembre'])[extract(month from d)::int],
           extract(day from d), extract(isoyear from d), extract(week from d),
           extract(isodow from d),
           (array['lunes','martes','miércoles','jueves','viernes','sábado','domingo'])
               [extract(isodow from d)::int],
           extract(isodow from d) >= 6
    from (select g::date as d
          from generate_series(first_day::timestamp, last_day::timestamp, interval '1 day') g) x
    on conflict (date_key) do nothing;
    select count(*)::integer from bi.dim_date;
$$;
select bi.fill_dim_date('2025-01-01', '2030-12-31');
"""

ROLE = f"""
do $$
begin
    if not exists (select from pg_roles where rolname = '{BI_READER_ROLE}') then
        create role {BI_READER_ROLE} nologin;
    end if;
end
$$;
-- Limited to bi: nothing in public, read-only on bi, now and for future tables.
revoke all on schema public from public;
revoke all on all tables in schema public from {BI_READER_ROLE};
grant usage on schema bi to {BI_READER_ROLE};
grant select on all tables in schema bi to {BI_READER_ROLE};
alter default privileges in schema bi grant select on tables to {BI_READER_ROLE};
alter role {BI_READER_ROLE} set default_transaction_read_only = on;
alter role {BI_READER_ROLE} set search_path = bi;
"""

DOWNGRADE = f"""
alter default privileges in schema bi revoke select on tables from {BI_READER_ROLE};
revoke all on all tables in schema bi from {BI_READER_ROLE};
revoke usage on schema bi from {BI_READER_ROLE};
drop schema bi cascade;
grant usage on schema public to public;
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(ROLE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
