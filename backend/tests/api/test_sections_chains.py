"""Fast sections, active chains and multipack unit prices (iteration 17, Wave 0)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.products import SectionsCache, SectionsResponse, default_sections_cache
from tests.api.conftest import FakeClock
from tests.api.test_products import (
    IMAGE_ONE,
    IMAGE_PAN_ONE,
    IMAGE_YOGUR,
    Catalog,
    _canonical,
    _chain_category,
    _product,
    _scalar,
    seed_catalog,
)

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


@pytest.fixture
def catalog(session: Session) -> Catalog:
    return seed_catalog(session)


def _mercadona(session: Session) -> tuple[int, int]:
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    return chain_id, zone_id


def _zone_of(session: Session, code: str) -> int:
    return _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = :code order by z.id limit 1",
        code=code,
    )


def _add_store(session: Session, code: str, *, name: str, active: bool = True) -> None:
    session.execute(
        text(
            "insert into store (chain_id, zone_id, name, geom, is_active)"
            " select c.id, :zone, :name,"
            "  st_setsrid(st_makepoint(-5.57, 42.6), 4326)::geography, :active"
            " from chain c where c.code = :code"
        ),
        {"zone": _zone_of(session, code), "name": name, "active": active, "code": code},
    )


def _add_priced_product(session: Session, code: str, *, sku: str) -> int:
    """A priced, active product in the chain's first zone, with no store to sell it."""
    zone_id = _zone_of(session, code)
    product_id = _scalar(
        session,
        "insert into chain_product (chain_id, chain_sku, name)"
        " select id, :sku, :name from chain where code = :code returning id",
        sku=sku,
        name=f"Producto {sku}",
        code=code,
    )
    session.execute(
        text(
            "insert into chain_product_zone (chain_product_id, zone_id, is_available)"
            " values (:product, :zone, true)"
        ),
        {"product": product_id, "zone": zone_id},
    )
    session.execute(
        text(
            "insert into price_current (chain_product_id, zone_id, price, valid_from)"
            " values (:product, :zone, 1.00, '2026-11-13 05:00:00+00')"
        ),
        {"product": product_id, "zone": zone_id},
    )
    return product_id


def _add_pack(
    session: Session,
    *,
    chain_id: int,
    chain_category_id: int,
    zone_id: int,
    sku: str,
    name: str,
    price: str,
    quantity: str,
    pack_count: int,
    canonical_id: int | None = None,
) -> int:
    product_id = _product(
        session,
        chain_id=chain_id,
        chain_category_id=chain_category_id,
        zone_id=zone_id,
        sku=sku,
        name=name,
        price=price,
        quantity=quantity,
        unit="kg",
        canonical_id=canonical_id,
    )
    session.execute(
        text("update chain_product set pack_count = :pack where id = :id"),
        {"pack": pack_count, "id": product_id},
    )
    return product_id


def test_sections_summary_comes_from_sql_and_is_cached(client, session: Session, catalog: Catalog):
    first = client.get("/api/sections")
    assert first.status_code == 200
    by_key = {section["key"]: section for section in first.json()["sections"]}
    assert by_key["fruta_verdura"]["products"] == 4
    assert by_key["fruta_verdura"]["image_url"] == IMAGE_ONE
    assert by_key["lacteos_huevos"]["image_url"] == IMAGE_YOGUR
    assert by_key["panaderia"]["image_url"] == IMAGE_PAN_ONE

    chain_id, zone_id = _mercadona(session)
    category_id = _chain_category(session, chain_id, "T-FRUTA-EXTRA", "platano")
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=category_id,
        zone_id=zone_id,
        sku="platano-extra",
        name="Plátano extra",
        price="1.00",
    )
    session.flush()

    # The short-lived cache keeps serving the summary until it is reset.
    assert client.get("/api/sections").json() == first.json()
    default_sections_cache.reset()
    refreshed = {
        section["key"]: section for section in client.get("/api/sections").json()["sections"]
    }
    assert refreshed["fruta_verdura"]["products"] == 5


def test_sections_cache_expires_after_its_ttl():
    clock = FakeClock()
    cache = SectionsCache(ttl_seconds=60.0, clock=clock)
    value = SectionsResponse(sections=[])
    assert cache.get() is None
    cache.set(value)
    assert cache.get() is value
    clock.sleep(59.0)
    assert cache.get() is value
    clock.sleep(2.0)
    assert cache.get() is None


def test_chains_lists_only_chains_with_an_active_store(client, session: Session, catalog: Catalog):
    _add_store(session, "mercadona", name="Mercadona León 2")
    # Carrefour has priced products but no active store: it must stay hidden.
    _add_priced_product(session, "carrefour", sku="carrefour-1")
    # Dia has a store, but it is inactive.
    _add_store(session, "dia", name="Dia León", active=False)
    session.flush()

    response = client.get("/api/chains")
    assert response.status_code == 200, response.text
    chains = response.json()["chains"]
    assert [chain["code"] for chain in chains] == ["mercadona"]
    only = chains[0]
    assert only["name"] == "Mercadona"
    assert only["store_count"] == 2
    assert only["product_count"] == 10
    assert datetime.fromisoformat(only["last_price_at"]) == datetime(2026, 11, 13, 5, tzinfo=UTC)


def test_chains_are_ordered_by_name_and_include_store_only_chains(
    client, session: Session, catalog: Catalog
):
    _add_store(session, "dia", name="Dia León")
    session.flush()

    chains = client.get("/api/chains").json()["chains"]
    assert [chain["code"] for chain in chains] == ["dia", "mercadona"]
    dia = chains[0]
    assert dia["store_count"] == 1
    assert dia["product_count"] == 0
    assert dia["last_price_at"] is None


def test_multipack_unit_price_in_products(client, session: Session, catalog: Catalog):
    chain_id, zone_id = _mercadona(session)
    category_id = _chain_category(session, chain_id, "T-ACTIMEL", "yogur_natural")
    canonical = _canonical(session, "yogur_natural", "Actimel natural")
    multipack = _add_pack(
        session,
        chain_id=chain_id,
        chain_category_id=category_id,
        zone_id=zone_id,
        sku="actimel-12",
        name="Actimel natural pack 12",
        price="5.99",
        quantity="0.1",
        pack_count=12,
        canonical_id=canonical,
    )
    session.execute(
        text("update chain_product set dietary_tags = array['vegetariano'] where id = :id"),
        {"id": multipack},
    )
    _add_pack(
        session,
        chain_id=chain_id,
        chain_category_id=category_id,
        zone_id=zone_id,
        sku="actimel-1",
        name="Actimel natural botella",
        price="5.00",
        quantity="1",
        pack_count=1,
        canonical_id=canonical,
    )
    session.flush()

    items = client.get(
        "/api/products", params={"q": "actimel", "sort": "unit_price", "size": 60}
    ).json()["items"]
    assert [item["name"] for item in items] == [
        "Actimel natural pack 12",
        "Actimel natural botella",
    ]
    by_name = {item["name"]: item for item in items}
    assert by_name["Actimel natural pack 12"]["unit_price"] == "4.9917"
    assert by_name["Actimel natural botella"]["unit_price"] == "5"
    assert by_name["Actimel natural pack 12"]["dietary_tags"] == ["vegetariano"]
    assert by_name["Actimel natural pack 12"]["on_promo"] is False

    detail = client.get(f"/api/products/{multipack}").json()
    assert detail["unit_price"] == "4.9917"
    assert detail["dietary_tags"] == ["vegetariano"]


def test_multipack_unit_price_in_canonicals(client, session: Session, catalog: Catalog):
    chain_id, zone_id = _mercadona(session)
    category_id = _chain_category(session, chain_id, "T-ACTIMEL", "yogur_natural")
    canonical = _canonical(session, "yogur_natural", "Actimel natural")
    _add_pack(
        session,
        chain_id=chain_id,
        chain_category_id=category_id,
        zone_id=zone_id,
        sku="actimel-12",
        name="Actimel natural pack 12",
        price="5.99",
        quantity="0.1",
        pack_count=12,
        canonical_id=canonical,
    )
    _add_pack(
        session,
        chain_id=chain_id,
        chain_category_id=category_id,
        zone_id=zone_id,
        sku="actimel-1",
        name="Actimel natural botella",
        price="5.00",
        quantity="1",
        pack_count=1,
        canonical_id=canonical,
    )
    session.flush()

    items = client.get("/api/canonicals", params={"q": "actimel", "size": 60}).json()["items"]
    item = next(entry for entry in items if entry["name"] == "Actimel natural")
    assert item["from_unit_price"] == "4.9917"

    detail = client.get(f"/api/canonicals/{canonical}").json()
    assert detail["from_unit_price"] == "4.9917"
    assert [product["unit_price"] for product in detail["products"]] == ["4.9917", "5"]
