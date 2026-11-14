"""Canonical catalog and canonical detail over a synthetic catalog (iteration 12, task E6b)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.orm import Session

from tests.api.test_products import (
    Catalog,
    _canonical,
    _chain_category,
    _product,
    _scalar,
    seed_catalog,
)

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

IMAGE_MANZANA = "https://cdn.example/manzana-1.jpg"
IMAGE_BEBIDA = "https://cdn.example/bebida-platano.jpg"


@pytest.fixture
def catalog(session: Session) -> Catalog:
    return seed_catalog(session)


def test_canonicals_listing_category_filter_and_fields(client, session: Session, catalog: Catalog):
    # Add a second canonical in fruta ("Manzana Golden") so category=fruta has at least 2 items
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    manzana_cat = _chain_category(session, chain_id, "T-MANZANA", "manzana")
    manzana_canon = _canonical(session, "manzana", "Manzana Golden")

    _product(
        session,
        chain_id=chain_id,
        chain_category_id=manzana_cat,
        zone_id=zone_id,
        sku="manzana-1",
        name="Manzana Golden",
        price="1.80",
        quantity="1",
        unit="kg",
        image_url=IMAGE_MANZANA,
        canonical_id=manzana_canon,
    )
    session.flush()

    response = client.get("/api/canonicals", params={"category": "fruta", "size": 2})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["size"] == 2
    assert len(data["items"]) == 2

    by_name = {item["name"]: item for item in data["items"]}
    assert "Plátano de Canarias" in by_name
    assert "Manzana Golden" in by_name

    platano_item = by_name["Plátano de Canarias"]
    assert platano_item["category_key"] == "platano"
    assert platano_item["category_name"] == "Plátano"
    assert platano_item["from_price"] == "1.2"
    assert platano_item["from_unit_price"] == "1.2"
    assert platano_item["base_unit"] == "kg"
    assert platano_item["product_count"] == 3
    assert platano_item["chains"] == ["mercadona"]

    manzana_item = by_name["Manzana Golden"]
    assert manzana_item["category_key"] == "manzana"
    assert manzana_item["from_price"] == "1.8"
    assert manzana_item["from_unit_price"] == "1.8"
    assert manzana_item["image_url"] == IMAGE_MANZANA
    assert manzana_item["product_count"] == 1


def test_canonicals_detail_returns_products_sorted_by_unit_price(client, catalog: Catalog):
    platano_id = catalog.canonicals["platano"]
    response = client.get(f"/api/canonicals/{platano_id}")
    assert response.status_code == 200, response.text
    detail = response.json()

    assert detail["id"] == platano_id
    assert detail["name"] == "Plátano de Canarias"
    assert detail["category_key"] == "platano"
    assert detail["category_name"] == "Plátano"
    assert detail["from_price"] == "1.2"
    assert detail["from_unit_price"] == "1.2"
    assert detail["base_unit"] == "kg"
    assert detail["product_count"] == 3
    assert detail["chains"] == ["mercadona"]

    # Products sorted by unit price ascending
    products = detail["products"]
    assert len(products) == 3
    assert [p["name"] for p in products] == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Plátano ecológico",
    ]
    # Each product conforms to ProductOut structure from /api/products
    p1 = products[0]
    for key in (
        "id",
        "name",
        "brand",
        "private_label",
        "packaging",
        "image_url",
        "chain",
        "price",
        "unit_price",
        "base_unit",
        "base_quantity",
        "canonical",
    ):
        assert key in p1
    assert p1["packaging"] == "bolsa"
    assert p1["price"] == "1.2"
    assert p1["unit_price"] == "1.2"


def test_canonicals_detail_404_when_missing_or_no_priced_products(
    client, session: Session, catalog: Catalog
):
    # Non-existent canonical ID
    res1 = client.get("/api/canonicals/999999")
    assert res1.status_code == 404
    assert res1.json()["detail"] == "Producto no encontrado."

    # Existing canonical but no active priced products
    empty_canon = _canonical(session, "platano", "Plátano sin productos")
    session.flush()
    res2 = client.get(f"/api/canonicals/{empty_canon}")
    assert res2.status_code == 404
    assert res2.json()["detail"] == "Producto no encontrado."


def test_canonicals_chain_filter(client, catalog: Catalog):
    res_mercadona = client.get("/api/canonicals", params={"chain": "mercadona"})
    assert res_mercadona.status_code == 200
    names_mercadona = [item["name"] for item in res_mercadona.json()["items"]]
    assert "Plátano de Canarias" in names_mercadona

    res_otra = client.get("/api/canonicals", params={"chain": "otra"})
    assert res_otra.status_code == 200
    assert res_otra.json()["total"] == 0
    assert res_otra.json()["items"] == []


def test_canonicals_search_relevance_ranks_prefix_and_category_first(
    client, session: Session, catalog: Catalog
):
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    yogur_cat = _scalar(session, "select id from chain_category where code = 'T-YOGUR'")
    bebida_canon = _canonical(session, "yogur_natural", "Bebida de plátano")

    _product(
        session,
        chain_id=chain_id,
        chain_category_id=yogur_cat,
        zone_id=zone_id,
        sku="bebida-platano-canon",
        name="Bebida de plátano",
        price="0.50",
        quantity="1",
        unit="l",
        image_url=IMAGE_BEBIDA,
        canonical_id=bebida_canon,
    )
    session.flush()

    response = client.get("/api/canonicals", params={"q": "platanos"})
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "Plátano de Canarias" in names
    assert "Bebida de plátano" in names
    # "Plátano de Canarias" has relevance rank 0; "Bebida de plátano" has rank 1.
    assert names.index("Plátano de Canarias") < names.index("Bebida de plátano")


def test_canonicals_validation_errors(client, catalog: Catalog):
    cases = [
        {"size": 0},
        {"size": 61},
        {"page": 0},
        {"section": "no-existe"},
        {"category": "no-existe"},
    ]
    for params in cases:
        response = client.get("/api/canonicals", params=params)
        assert response.status_code == 422, params
        assert isinstance(response.json()["detail"], str), params
