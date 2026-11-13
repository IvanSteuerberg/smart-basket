"""Migrations against a real PostgreSQL 18 with PostGIS and pgvector.

Skipped unless TEST_DATABASE_URL points at a disposable database (CI sets it). The tests
downgrade it to an empty schema, upgrade it to head and check keys, constraints, partitions,
the as-of view and the read-only BI role. Synthetic data only.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from smart_basket.db.migrate import alembic_config

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


@pytest.fixture(scope="module")
def engine():
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine) -> Iterator[Connection]:
    """A connection whose work is always rolled back."""
    with engine.connect() as connection:
        tx = connection.begin()
        yield connection
        tx.rollback()


def scalar(conn: Connection, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def seed(conn: Connection) -> dict[str, int]:
    ids = {}
    ids["chain"] = scalar(
        conn, "insert into chain (code, name) values ('demo', 'Demo') returning id"
    )
    ids["zone"] = scalar(
        conn,
        "insert into zone (chain_id, kind, code) values (:c, 'chain', 'all') returning id",
        c=ids["chain"],
    )
    ids["category"] = scalar(
        conn,
        "insert into category (key, name, level) values ('lacteos', 'Lácteos', 1) returning id",
    )
    ids["canonical"] = scalar(
        conn,
        "insert into canonical_product (category_id, name, variant_key, base_unit) "
        "values (:cat, 'leche', 'semidesnatada', 'l') returning id",
        cat=ids["category"],
    )
    ids["product"] = scalar(
        conn,
        "insert into chain_product (chain_id, chain_sku, name, base_quantity, base_unit, "
        "canonical_id, match_method) values (:c, 'SKU1', 'Leche semi 1 l', 1, 'l', :can, "
        "'rule') returning id",
        c=ids["chain"],
        can=ids["canonical"],
    )
    return ids


def test_upgrade_creates_both_schemas(conn):
    tables = set(
        conn.execute(
            text(
                "select table_schema || '.' || table_name from information_schema.tables "
                "where table_schema in ('public', 'bi')"
            )
        ).scalars()
    )
    for name in [
        "public.chain",
        "public.store",
        "public.canonical_product",
        "public.chain_product",
        "public.price_current",
        "public.price_history",
        "public.promotion",
        "public.promotion_target",
        "public.recommendation",
        "public.ingest_run",
        "public.match_review",
        "bi.dim_date",
        "bi.dim_product",
        "bi.fact_price_category_daily",
        "bi.fact_price_index_daily",
        "bi.fact_promotion_daily",
        "bi.fact_recommendation",
        "bi.fact_recommendation_line",
        "bi.fact_usage_daily",
        "bi.v_price_asof",
    ]:
        assert name in tables, name
    exts = set(conn.execute(text("select extname from pg_extension")).scalars())
    assert {"postgis", "vector", "btree_gist"} <= exts
    assert scalar(conn, "select count(*) from bi.dim_date") == 2191  # 2025-2030
    assert scalar(conn, "select day_name from bi.dim_date where date = '2026-11-03'") == "martes"


def test_price_history_is_partitioned_by_year(conn):
    ids = seed(conn)
    conn.execute(
        text(
            "insert into price_history (chain_product_id, zone_id, price, valid_from, valid_to) "
            "values (:p, :z, 1.00, '2026-05-01 10:00+02', '2026-05-03 09:00+02'), "
            "       (:p, :z, 1.10, '2031-01-02 10:00+01', '2031-01-03 10:00+01')"
        ),
        {"p": ids["product"], "z": ids["zone"]},
    )
    parts = conn.execute(
        text("select tableoid::regclass::text from price_history order by valid_from")
    ).scalars()
    assert list(parts) == ["price_history_y2026", "price_history_default"]
    assert scalar(conn, "select create_price_history_partition(2029)") == "price_history_y2029"


def test_price_interval_must_be_positive(conn):
    ids = seed(conn)
    with pytest.raises(DBAPIError, match="check"):
        conn.execute(
            text(
                "insert into price_history (chain_product_id, zone_id, price, valid_from, valid_to)"
                " values (:p, :z, 1, '2026-05-02', '2026-05-01')"
            ),
            {"p": ids["product"], "z": ids["zone"]},
        )


@pytest.mark.parametrize(
    ("columns", "ok"),
    [
        ("kind, promo_price", "'promo_price', 0.99"),
        ("kind, percent", "'percent_off', 20"),
        ("kind, buy_n, pay_m", "'nxm', 3, 2"),
        ("kind, percent", "'second_unit', 50"),
        ("kind, tiers", "'volume_tier', '[{\"min_units\": 2, \"percent\": 10}]'"),
        ("kind, promo_price, requires_loyalty", "'loyalty_price', 0.89, true"),
        ("kind, coupon_code, amount", "'coupon', 'OTONO', 0.50"),
    ],
)
def test_promotion_kinds_accept_their_parameters(conn, columns, ok):
    ids = seed(conn)
    conn.execute(
        text(
            f"insert into promotion (chain_id, valid, source, {columns}) "
            f"values (:c, '[2026-11-01,2026-11-15)', 'web', {ok})"
        ),
        {"c": ids["chain"]},
    )


@pytest.mark.parametrize(
    ("columns", "bad"),
    [
        ("kind", "'promo_price'"),
        ("kind, percent", "'promo_price', 10"),
        ("kind, buy_n, pay_m", "'nxm', 2, 2"),
        ("kind, buy_n", "'nxm', 3"),
        ("kind", "'second_unit'"),
        ("kind, tiers", "'volume_tier', '[]'"),
        ("kind, promo_price", "'loyalty_price', 0.89"),
        ("kind, coupon_code", "'coupon', 'OTONO'"),
        ("kind, percent", "'percent_off', 120"),
        ("kind, promo_price", "'bogus', 1"),
    ],
)
def test_promotion_kinds_reject_wrong_parameters(conn, columns, bad):
    ids = seed(conn)
    with pytest.raises(DBAPIError, match="check"):
        conn.execute(
            text(
                f"insert into promotion (chain_id, valid, source, {columns}) "
                f"values (:c, '[2026-11-01,2026-11-15)', 'web', {bad})"
            ),
            {"c": ids["chain"]},
        )


def test_promotion_target_has_exactly_one_target(conn):
    ids = seed(conn)
    promo = scalar(
        conn,
        "insert into promotion (chain_id, kind, percent, valid, source) "
        "values (:c, 'percent_off', 10, '[2026-11-01,)', 'web') returning id",
        c=ids["chain"],
    )
    conn.execute(
        text("insert into promotion_target (promotion_id, canonical_id) values (:p, :c)"),
        {"p": promo, "c": ids["canonical"]},
    )
    for values in ["null, null", f"{ids['product']}, {ids['canonical']}"]:
        with pytest.raises(DBAPIError, match="exactly_one"), conn.begin_nested():
            conn.execute(
                text(
                    f"insert into promotion_target (promotion_id, chain_product_id, canonical_id) "
                    f"values ({promo}, {values})"
                )
            )


def test_recommendation_ids_are_uuidv7(conn):
    rid = scalar(
        conn,
        "insert into recommendation (data_as_of, engine_version, travel_mode, "
        "max_stores, lambda, request, result, total_cost, minutes) values "
        "(now(), 'basket-engine/1.0.0', 'walk', 2, 0.15, '{}', '{}', 10, 12) "
        "returning id::text",
    )
    assert rid[14] == "7"


def test_price_asof_view_steps_through_intervals(conn):
    ids = seed(conn)
    params = {"p": ids["product"], "z": ids["zone"]}
    conn.execute(
        text(
            "insert into price_history (chain_product_id, zone_id, price, valid_from, valid_to) "
            "values (:p, :z, 1.00, '2026-03-01 10:00 Europe/Madrid', "
            "'2026-03-03 09:00 Europe/Madrid')"
        ),
        params,
    )
    conn.execute(
        text(
            "insert into price_current (chain_product_id, zone_id, price, valid_from) "
            "values (:p, :z, 1.20, '2026-03-03 09:00 Europe/Madrid')"
        ),
        params,
    )
    rows = dict(
        conn.execute(
            text(
                "select date::text, price::text from bi.v_price_asof where chain_product_id = :p "
                "and date between '2026-02-28' and '2026-03-04' order by date"
            ),
            params,
        ).all()
    )
    assert rows == {
        "2026-03-01": "1.00",
        "2026-03-02": "1.00",
        "2026-03-03": "1.20",
        "2026-03-04": "1.20",
    }


def test_bi_reader_reads_bi_only(conn):
    seed(conn)
    conn.execute(text("set local role bi_reader"))
    assert scalar(conn, "select count(*) from bi.dim_promotion_kind") == 8
    with pytest.raises(DBAPIError, match="permission denied"), conn.begin_nested():
        conn.execute(text("select count(*) from public.chain"))
    with pytest.raises(DBAPIError, match="permission denied"), conn.begin_nested():
        conn.execute(text("insert into bi.fact_usage_daily values (20261103, 'x', 1)"))
    assert scalar(conn, "select count(*) from bi.v_price_asof") >= 0


def test_category_seed_columns_downgrade_and_upgrade(engine):
    cfg = alembic_config(URL)
    columns_sql = "select column_name from information_schema.columns where table_name = 'category'"
    command.downgrade(cfg, "0002")
    with engine.connect() as c:
        columns = set(c.execute(text(columns_sql)).scalars())
    assert "key" not in columns
    assert "forms" not in columns
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        columns = set(c.execute(text(columns_sql)).scalars())
        assert {"key", "base_unit", "default_quantity", "forms", "is_vague"} <= columns
        assert scalar(c, "select version_num from alembic_version") == "0004"


def test_category_seed_columns_downgrade_and_upgrade_with_rows(engine):
    cfg = alembic_config(URL)
    with engine.begin() as c:
        cat = c.execute(
            text(
                "insert into category (key, name, level, base_unit, forms, is_vague) "
                "values ('seeded', 'Seeded', 1, 'kg', array['semilla'], true) returning id"
            )
        ).scalar_one()
    command.downgrade(cfg, "0002")
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        row = c.execute(
            text("select key, forms, is_vague from category where id = :id"), {"id": cat}
        ).one()
    assert row.key == f"legacy_{cat}"
    assert row.forms == []
    assert row.is_vague is False


def test_brand_seed_columns_downgrade_and_upgrade(engine):
    cfg = alembic_config(URL)
    columns_sql = "select column_name from information_schema.columns where table_name = 'brand'"
    command.downgrade(cfg, "0003")
    with engine.connect() as c:
        columns = set(c.execute(text(columns_sql)).scalars())
    assert "aliases" not in columns
    assert "implies_category" not in columns
    assert "match_name" not in columns
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        columns = set(c.execute(text(columns_sql)).scalars())
    assert {"aliases", "implies_category", "match_name"} <= columns
    with engine.connect() as c:
        row = c.execute(
            text(
                "insert into brand (name) values ('Demo') "
                "returning aliases, implies_category, match_name, is_private_label"
            )
        ).one()
        c.rollback()
    assert row.aliases == []
    assert row.implies_category is None
    assert row.match_name is True
    assert row.is_private_label is False
    with engine.connect() as c:
        assert scalar(c, "select version_num from alembic_version") == "0004"


def test_downgrade_and_upgrade_again(engine):
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    with engine.connect() as c:
        assert scalar(c, "select to_regclass('public.chain') is null")
        assert scalar(c, "select to_regnamespace('bi') is null")
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert scalar(c, "select version_num from alembic_version") == "0004"
