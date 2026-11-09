"""Persistence of catalog runs against a real PostgreSQL, per the criteria of task E3.

Skipped unless TEST_DATABASE_URL points at a disposable database (CI sets it). The chain and the
warehouse zone are seeded with plain SQL, the way `smart-basket-seed` will.
"""

import gzip
import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from smart_basket.db.migrate import alembic_config
from smart_basket.ingestion import (
    CategoryObservation,
    CrawlError,
    IngestSetupError,
    ProductObservation,
    RawResponse,
    ingest_catalog,
    store,
)

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

T1 = datetime(2026, 1, 1, 10, tzinfo=UTC)
T2 = datetime(2026, 1, 2, 10, tzinfo=UTC)
T3 = datetime(2026, 1, 3, 10, tzinfo=UTC)

CATEGORIES = (
    CategoryObservation(code="112", name="Aceite, vinagre y sal", parent_code=None),
    CategoryObservation(code="420", name="Aceite de oliva", parent_code="112"),
)


class FakeAdapter:
    """An adapter with a fixed script; the store must not care where observations come from."""

    chain_code = "mercadona"

    def __init__(self, observations: tuple = (), chain_code: str = "mercadona") -> None:
        self.observations = observations
        self.chain_code = chain_code

    def crawl(self, zone_code: str, *, max_categories: int | None = None):
        yield from self.observations


@dataclass(frozen=True)
class Db:
    url: str
    engine: Engine
    chain_id: int
    zone_id: int


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    cfg = alembic_config(URL)
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Db:
    with engine.begin() as conn:
        conn.execute(text("truncate table chain restart identity cascade"))
        chain_id = conn.execute(
            text("insert into chain (code, name) values ('mercadona', 'Mercadona') returning id")
        ).scalar_one()
        zone_id = conn.execute(
            text(
                "insert into zone (chain_id, kind, code) "
                "values (:chain, 'warehouse', 'W1') returning id"
            ),
            {"chain": chain_id},
        ).scalar_one()
    return Db(url=URL, engine=engine, chain_id=chain_id, zone_id=zone_id)


def rows(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def scalar(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def product(
    sku: str,
    price: str,
    *,
    price_per_unit: str | None = None,
    category: str = "420",
    base_quantity: str = "1",
    base_unit: str = "l",
    pack_count: int = 1,
) -> ProductObservation:
    return ProductObservation(
        sku=sku,
        name=f"Producto {sku}",
        packaging="Botella",
        url=f"https://example.test/product/{sku}",
        category_code=category,
        base_quantity=D(base_quantity),
        base_unit=base_unit,
        pack_count=pack_count,
        price=D(price),
        price_per_unit=D(price_per_unit or price),
    )


def run(db: Db, observations: tuple, now: datetime, data_dir: Path, **kwargs):
    return ingest_catalog(
        FakeAdapter(observations),
        "W1",
        data_dir=data_dir,
        now=now,
        database_url=db.url,
        **kwargs,
    )


def test_same_price_twice_keeps_one_current_row_and_no_history(db, tmp_path):
    observations = (*CATEGORIES, product("100", "1.00"))
    first = run(db, observations, T1, tmp_path)
    second = run(db, observations, T2, tmp_path)

    assert first.prices_changed == 1
    assert second.prices_changed == 0
    assert scalar(db, "select count(*) from price_current") == 1
    assert scalar(db, "select count(*) from price_history") == 0
    assert scalar(db, "select valid_from from price_current") == T1


def test_price_change_closes_the_old_interval(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)
    second = run(db, (*CATEGORIES, product("100", "1.20")), T2, tmp_path)

    assert second.prices_changed == 1
    current = rows(db, "select price, valid_from from price_current")[0]
    assert current.price == D("1.20")
    assert current.valid_from == T2
    history = rows(db, "select price, valid_from, valid_to from price_history")[0]
    assert history.price == D("1.00")
    assert history.valid_from == T1
    assert history.valid_to == T2


def test_partial_run_records_the_error_and_marks_nothing_unavailable(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)
    failing = (
        *CATEGORIES,
        product("200", "2.00"),
        CrawlError(url="https://example.test/api/categories/113/", error="HTTP 500"),
    )
    second = run(db, failing, T2, tmp_path)

    assert second.status == "partial"
    assert second.errors == (
        {"url": "https://example.test/api/categories/113/", "error": "HTTP 500"},
    )
    stored = scalar(db, "select errors from ingest_run where id = :id", id=second.run_id)
    assert stored == [{"url": "https://example.test/api/categories/113/", "error": "HTTP 500"}]
    assert scalar(
        db,
        "select is_available from chain_product_zone z "
        "join chain_product p on p.id = z.chain_product_id where p.chain_sku = '100'",
    )
    assert scalar(db, "select count(*) from chain_product where is_active") == 2


def test_complete_run_marks_unseen_products_unavailable(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00"), product("200", "2.00")), T1, tmp_path)
    run(db, (*CATEGORIES, product("100", "1.00")), T2, tmp_path)

    available = dict(
        rows(
            db,
            "select p.chain_sku, z.is_available from chain_product p "
            "join chain_product_zone z on z.chain_product_id = p.id",
        )
    )
    assert available == {"100": True, "200": False}
    active = dict(rows(db, "select chain_sku, is_active from chain_product"))
    assert active == {"100": True, "200": False}


def test_product_available_in_another_zone_stays_active(db, tmp_path):
    with db.engine.begin() as conn:
        second_zone = conn.execute(
            text(
                "insert into zone (chain_id, kind, code) "
                "values (:chain, 'warehouse', 'W2') returning id"
            ),
            {"chain": db.chain_id},
        ).scalar_one()

    observations = (*CATEGORIES, product("100", "1.00"), product("200", "2.00"))
    run(db, observations, T1, tmp_path)
    ingest_catalog(FakeAdapter(observations), "W2", data_dir=tmp_path, now=T2, database_url=db.url)
    run(db, (*CATEGORIES, product("100", "1.00")), T3, tmp_path)

    assert (
        scalar(
            db,
            "select is_available from chain_product_zone z "
            "join chain_product p on p.id = z.chain_product_id "
            "where p.chain_sku = '200' and z.zone_id = :zone",
            zone=db.zone_id,
        )
        is False
    )
    assert scalar(
        db,
        "select is_available from chain_product_zone z "
        "join chain_product p on p.id = z.chain_product_id "
        "where p.chain_sku = '200' and z.zone_id = :zone",
        zone=second_zone,
    )
    assert scalar(db, "select is_active from chain_product where chain_sku = '200'") is True


def test_limited_run_never_marks_products_unavailable(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00"), product("200", "2.00")), T1, tmp_path)
    run(db, (*CATEGORIES, product("100", "1.00")), T2, tmp_path, max_categories=1)

    assert scalar(
        db,
        "select is_available from chain_product_zone z "
        "join chain_product p on p.id = z.chain_product_id where p.chain_sku = '200'",
    )


def test_raw_responses_are_gzipped_and_recorded(db, tmp_path):
    body = b'{"results": []}'
    summary = run(
        db,
        (*CATEGORIES, RawResponse("https://example.test/api/categories/", 200, body)),
        T1,
        tmp_path,
    )

    digest = hashlib.sha256(body).hexdigest()
    expected = f"raw/mercadona/2026-01-01/{digest}.json.gz"
    stored_path = scalar(db, "select path from raw_response where run_id = :id", id=summary.run_id)
    assert stored_path == expected
    assert scalar(db, "select sha256 from raw_response where run_id = :id", id=summary.run_id) == (
        digest
    )
    with gzip.open(tmp_path / expected, "rb") as archived:
        assert archived.read() == body


def test_categories_are_upserted_without_overwriting_category_id(db, tmp_path):
    with db.engine.begin() as conn:
        category_id = conn.execute(
            text("insert into category (name, level) values ('Aceite', 3) returning id")
        ).scalar_one()
        conn.execute(
            text(
                "insert into chain_category (chain_id, code, name, parent_code, category_id) "
                "values (:chain, '420', 'Nombre viejo', '112', :category)"
            ),
            {"chain": db.chain_id, "category": category_id},
        )

    run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)

    stored = rows(
        db,
        "select name, parent_code, category_id from chain_category where code = '420'",
    )[0]
    assert stored.name == "Aceite de oliva"
    assert stored.parent_code == "112"
    assert stored.category_id == category_id


def test_sizes_are_stored_normalized(db, tmp_path):
    run(
        db,
        (
            *CATEGORIES,
            product("100", "9.00", base_quantity="0.25", pack_count=4),
        ),
        T1,
        tmp_path,
    )

    stored = rows(
        db,
        "select base_quantity, base_unit, pack_count from chain_product where chain_sku = '100'",
    )[0]
    assert stored.base_quantity == D("0.25")
    assert stored.base_unit == "l"
    assert stored.pack_count == 4


def test_price_per_unit_change_closes_the_old_interval(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00", price_per_unit="1.00")), T1, tmp_path)
    second = run(db, (*CATEGORIES, product("100", "1.00", price_per_unit="1.10")), T2, tmp_path)

    assert second.prices_changed == 1
    current = rows(db, "select price, price_per_unit, valid_from from price_current")[0]
    assert current.price == D("1.00")
    assert current.price_per_unit == D("1.10")
    assert current.valid_from == T2
    history = rows(db, "select price, price_per_unit, valid_from, valid_to from price_history")[0]
    assert history.price_per_unit == D("1.00")
    assert (history.price, history.valid_from, history.valid_to) == (D("1.00"), T1, T2)


def test_product_reappearing_after_unavailable_becomes_available(db, tmp_path):
    # The price interval stays open while a product is unavailable: a reappearance with the
    # same price keeps it, and a changed price closes it as any other change would.
    observations = (*CATEGORIES, product("100", "1.00"), product("200", "2.00"))
    run(db, observations, T1, tmp_path)
    run(db, (*CATEGORIES, product("100", "1.00")), T2, tmp_path)

    def availability(sku: str) -> bool:
        return scalar(
            db,
            "select is_available from chain_product_zone z "
            "join chain_product p on p.id = z.chain_product_id where p.chain_sku = :sku",
            sku=sku,
        )

    assert availability("200") is False

    third = run(db, observations, T3, tmp_path)

    assert third.status == "succeeded"
    assert availability("200") is True
    assert (
        scalar(
            db,
            "select valid_from from price_current c "
            "join chain_product p on p.id = c.chain_product_id where p.chain_sku = '200'",
        )
        == T1
    )
    assert (
        scalar(
            db,
            "select count(*) from price_history h "
            "join chain_product p on p.id = h.chain_product_id where p.chain_sku = '200'",
        )
        == 0
    )


def test_run_whose_tree_request_fails_ends_failed_and_keeps_its_row(db, tmp_path):
    class BrokenAdapter:
        chain_code = "mercadona"

        def crawl(self, zone_code, *, max_categories=None):
            raise RuntimeError("tree request failed")

    summary = ingest_catalog(BrokenAdapter(), "W1", data_dir=tmp_path, now=T1, database_url=db.url)

    assert summary.status == "failed"
    assert summary.complete is False
    row = rows(db, "select status, finished_at from ingest_run where id = :id", id=summary.run_id)
    assert row[0].status == "failed"
    assert row[0].finished_at is not None


def test_persistence_failure_closes_the_run_as_failed(db, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_persist", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)

    row = rows(db, "select status, finished_at, errors from ingest_run")[0]
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "disk full" in row.errors[0]["error"]


def test_interrupted_crawl_closes_the_run_as_failed(db, tmp_path):
    class InterruptedAdapter:
        chain_code = "mercadona"

        def crawl(self, zone_code, *, max_categories=None):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ingest_catalog(InterruptedAdapter(), "W1", data_dir=tmp_path, now=T1, database_url=db.url)

    row = rows(db, "select status, finished_at from ingest_run")[0]
    assert row.status == "failed"
    assert row.finished_at is not None


def test_a_failing_close_does_not_hide_the_original_error(db, tmp_path, monkeypatch, caplog):
    def broken_persist(*args, **kwargs):
        raise RuntimeError("disk full")

    def broken_close(*args, **kwargs):
        raise RuntimeError("database gone")

    caplog.set_level("ERROR", logger="smart_basket.ingestion")
    monkeypatch.setattr(store, "_persist", broken_persist)
    monkeypatch.setattr(store, "_close_run", broken_close)

    with pytest.raises(RuntimeError, match="disk full"):
        run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)

    assert "could not close run" in caplog.text


def test_abandoned_running_run_is_closed_when_the_next_one_starts(db, tmp_path):
    with db.engine.begin() as conn:
        old_id = conn.execute(
            text(
                "insert into ingest_run (chain_id, zone_id, kind, started_at, status) "
                "values (:chain, :zone, 'catalog', now() - interval '7 hours', 'running') "
                "returning id"
            ),
            {"chain": db.chain_id, "zone": db.zone_id},
        ).scalar_one()
        recent_id = conn.execute(
            text(
                "insert into ingest_run (chain_id, zone_id, kind, started_at, status) "
                "values (:chain, :zone, 'catalog', now() - interval '1 hour', 'running') "
                "returning id"
            ),
            {"chain": db.chain_id, "zone": db.zone_id},
        ).scalar_one()

    summary = run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)

    statuses = dict(rows(db, "select id, status from ingest_run"))
    assert statuses[old_id] == "failed"
    assert statuses[recent_id] == "running"
    assert statuses[summary.run_id] == "succeeded"
    assert scalar(db, "select errors from ingest_run where id = :id", id=old_id) == [
        {"url": None, "error": "abandoned run"}
    ]
    assert scalar(db, "select finished_at from ingest_run where id = :id", id=old_id) is not None


def test_below_threshold_run_ends_partial_and_marks_nothing_unavailable(db, tmp_path):
    observations = (
        *CATEGORIES,
        product("100", "1.00"),
        product("200", "2.00"),
        product("300", "3.00"),
        product("400", "4.00"),
    )
    run(db, observations, T1, tmp_path)
    second = run(db, (*CATEGORIES, product("100", "1.00")), T2, tmp_path)

    assert second.status == "partial"
    assert second.complete is False
    assert any("available products seen" in error["error"] for error in second.errors)
    assert scalar(db, "select count(*) from chain_product_zone where is_available") == 4
    stored = rows(db, "select status, errors from ingest_run where id = :id", id=second.run_id)[0]
    assert stored.status == "partial"
    assert any("available products seen" in error["error"] for error in stored.errors)


def test_empty_run_ends_partial_and_marks_nothing_unavailable(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00"), product("200", "2.00")), T1, tmp_path)
    second = run(db, CATEGORIES, T2, tmp_path)

    assert second.status == "partial"
    assert second.complete is False
    assert any("available products seen" in error["error"] for error in second.errors)
    assert scalar(db, "select count(*) from chain_product_zone where is_available") == 2


def test_product_listed_in_two_sections_is_stored_once(db, tmp_path):
    observations = (
        *CATEGORIES,
        product("100", "1.00", category="420"),
        product("100", "1.00", category="421"),
    )
    summary = run(db, observations, T1, tmp_path)

    assert summary.products_seen == 1
    assert scalar(db, "select count(*) from chain_product where chain_sku = '100'") == 1


def test_observation_at_the_interval_start_does_not_replace_the_price(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00")), T1, tmp_path)
    second = run(db, (*CATEGORIES, product("100", "1.20")), T1, tmp_path)

    assert second.prices_changed == 0
    current = rows(db, "select price, valid_from from price_current")[0]
    assert current.price == D("1.00")
    assert current.valid_from == T1
    assert scalar(db, "select count(*) from price_history") == 0


def test_older_observation_refreshes_last_seen_without_replacing_the_price(db, tmp_path):
    run(db, (*CATEGORIES, product("100", "1.00")), T2, tmp_path)
    older = run(db, (*CATEGORIES, product("100", "1.20")), T1, tmp_path)

    assert older.prices_changed == 0
    current = rows(
        db,
        "select price, valid_from, last_seen_run from price_current",
    )[0]
    assert current.price == D("1.00")
    assert current.valid_from == T2
    assert current.last_seen_run == older.run_id
    assert scalar(db, "select count(*) from price_history") == 0


def test_missing_chain_or_zone_asks_for_the_seed_loader(tmp_path):
    adapter = FakeAdapter((), chain_code="other")
    with pytest.raises(IngestSetupError, match="smart-basket-seed"):
        ingest_catalog(adapter, "W1", data_dir=tmp_path, database_url=URL)
    with pytest.raises(IngestSetupError, match="smart-basket-seed"):
        ingest_catalog(FakeAdapter(()), "W9", data_dir=tmp_path, database_url=URL)
