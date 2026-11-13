"""Store persistence against a real PostgreSQL, per the criteria of task E1.

Skipped unless TEST_DATABASE_URL points at a disposable database (CI sets it). The chains and
their zones are seeded with plain SQL, the way `smart-basket-seed` will, and the Overpass answer
comes from a fake transport: no real network.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from smart_basket.db.migrate import alembic_config
from smart_basket.stores import (
    BoundingBox,
    OverpassClient,
    StoreObservation,
    fetch_stores,
    import_stores,
)
from smart_basket.stores import (
    store as store_module,
)

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

BBOX = BoundingBox.parse("42.56,-5.62,42.63,-5.52")

# The seed layout the import relies on: Mercadona has warehouse 3683, Dia one León zone, the rest
# only their chain-wide zone (`kind = 'chain'`, code `all`).
ZONES = {
    "mercadona": [("chain", "all"), ("warehouse", "3683")],
    "dia": [("chain", "all"), ("postal_code", "24001")],
    "lidl": [("chain", "all")],
    "alimerka": [("chain", "all")],
}


@dataclass(frozen=True)
class Db:
    url: str
    engine: Engine
    chains: dict[str, int]


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
        chains = {}
        for code, zones in ZONES.items():
            chain_id = conn.execute(
                text("insert into chain (code, name) values (:code, :name) returning id"),
                {"code": code, "name": code.title()},
            ).scalar_one()
            for kind, zone_code in zones:
                conn.execute(
                    text("insert into zone (chain_id, kind, code) values (:chain, :kind, :code)"),
                    {"chain": chain_id, "kind": kind, "code": zone_code},
                )
            chains[code] = chain_id
    return Db(url=URL, engine=engine, chains=chains)


def rows(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def scalar(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def element(osm_id: int, brand: str, *, kind: str = "node", name: str | None = None, **tags: str):
    """One synthetic Overpass element of the given brand."""
    element_tags = {"shop": "supermarket", "brand": brand, **tags}
    if name is not None:
        element_tags["name"] = name
    body: dict[str, Any] = {"type": kind, "id": osm_id, "tags": element_tags}
    if kind == "node":
        body.update(lat=42.6, lon=-5.57)
    else:
        body["center"] = {"lat": 42.6, "lon": -5.57}
    return body


def load(db: Db, elements: list[dict[str, Any]]):
    """Run the whole path: a fake Overpass answer, its parsing and the import."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"elements": elements})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with OverpassClient(client, url="https://overpass.test/api") as overpass:
        observations = fetch_stores(overpass, BBOX)
    return import_stores(observations, mercadona_warehouse="3683", database_url=db.url)


def test_the_same_answer_loaded_twice_does_not_duplicate_stores(db):
    elements = [element(1, "Mercadona"), element(2, "Lidl")]

    first = load(db, elements)
    ids = [row.id for row in rows(db, "select id from store order by osm_id")]
    second = load(db, elements)

    assert (first.inserted, first.updated) == (2, 0)
    assert (second.inserted, second.updated) == (0, 2)
    assert scalar(db, "select count(*) from store") == 2
    assert [row.id for row in rows(db, "select id from store order by osm_id")] == ids
    assert scalar(db, "select count(*) from store where is_active") == 2
    assert scalar(db, "select count(*) from ingest_run where kind = 'stores'") == 4


def test_a_second_load_updates_the_tags_of_the_store(db):
    load(db, [element(1, "Lidl", name="Lidl antiguo")])
    load(db, [element(1, "Lidl", name="Lidl nuevo", **{"addr:street": "Calle Ancha"})])

    stored = rows(db, "select name, address from store")[0]
    assert stored.name == "Lidl nuevo"
    assert stored.address == "Calle Ancha"


def test_brands_outside_the_ten_chains_are_not_loaded(db):
    summary = load(db, [element(1, "Mercadona"), element(2, "Eroski"), element(3, "Consum")])

    assert summary.per_chain == {"mercadona": 1}
    assert scalar(db, "select count(*) from store") == 1
    assert scalar(db, "select osm_id from store") == "node/1"


def test_a_store_that_disappears_is_deactivated_and_not_deleted(db):
    load(db, [element(1, "Mercadona"), element(2, "Mercadona")])
    second = load(db, [element(1, "Mercadona")])

    assert second.deactivated == 1
    assert dict(rows(db, "select osm_id, is_active from store")) == {
        "node/1": True,
        "node/2": False,
    }


def test_a_store_that_reappears_becomes_active_again(db):
    load(db, [element(1, "Mercadona"), element(2, "Mercadona")])
    load(db, [element(1, "Mercadona")])
    third = load(db, [element(1, "Mercadona"), element(2, "Mercadona")])

    assert third.inserted == 0
    assert third.updated == 2
    assert scalar(db, "select count(*) from store where is_active") == 2


def test_the_chain_zones_follow_the_seed(db):
    load(
        db,
        [
            element(1, "Mercadona"),
            element(2, "Dia"),
            element(3, "Lidl"),
            element(4, "Alimerka"),
        ],
    )

    zones = {
        row.osm_id: (row.kind, row.code)
        for row in rows(
            db,
            "select s.osm_id, z.kind, z.code from store s join zone z on z.id = s.zone_id",
        )
    }
    assert zones == {
        "node/1": ("warehouse", "3683"),
        "node/2": ("postal_code", "24001"),
        "node/3": ("chain", "all"),
        "node/4": ("chain", "all"),
    }


def test_each_chain_with_stores_gets_its_own_store_run(db):
    summary = load(db, [element(1, "Mercadona"), element(2, "Dia"), element(3, "Lidl")])

    assert len(summary.run_ids) == 3
    runs = rows(
        db,
        "select c.code, z.kind, r.status, r.products_seen from ingest_run r "
        "join chain c on c.id = r.chain_id join zone z on z.id = r.zone_id "
        "where r.kind = 'stores' order by c.code",
    )
    assert [(run.code, run.kind, run.status, run.products_seen) for run in runs] == [
        ("dia", "postal_code", "succeeded", 1),
        ("lidl", "chain", "succeeded", 1),
        ("mercadona", "warehouse", "succeeded", 1),
    ]


def test_a_missing_chain_asks_for_the_seed_loader(db):
    observation = StoreObservation(
        osm_id="node/9",
        chain_code="aldi",
        name="Aldi",
        format="supermarket",
        address=None,
        lon=-5.57,
        lat=42.6,
        opening_hours=None,
    )

    with pytest.raises(store_module.StoreSetupError, match="smart-basket-seed"):
        import_stores((observation,), database_url=db.url)


def test_a_missing_mercadona_warehouse_asks_for_the_seed_loader(db):
    with db.engine.begin() as conn:
        conn.execute(text("delete from zone where kind = 'warehouse'"))

    with pytest.raises(store_module.StoreSetupError, match="warehouse zone '3683'"):
        load(db, [element(1, "Mercadona")])


def test_a_failed_persistence_closes_the_run_as_failed(db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(store_module, "_upsert_stores", boom)

    with pytest.raises(RuntimeError, match="database gone"):
        load(db, [element(1, "Lidl")])

    row = rows(db, "select status, finished_at, errors from ingest_run")[0]
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "database gone" in row.errors[0]["error"]
