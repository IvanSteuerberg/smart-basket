"""Canonical catalog and canonical detail over a synthetic catalog (iteration 12, task E6b)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
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

    # Product 1: cheaper package price ("1.00"), but higher unit price ("2.00") and no photo
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=manzana_cat,
        zone_id=zone_id,
        sku="manzana-small",
        name="Manzana Golden pequeña",
        price="1.00",
        quantity="0.5",
        unit="kg",
        canonical_id=manzana_canon,
    )
    # Product 2: higher package price ("1.80"), but lowest unit price ("0.90") with photo
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=manzana_cat,
        zone_id=zone_id,
        sku="manzana-big",
        name="Manzana Golden bolsa grande",
        price="1.80",
        quantity="2",
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
    assert platano_item["exact_only"] is False

    manzana_item = by_name["Manzana Golden"]
    assert manzana_item["category_key"] == "manzana"
    assert manzana_item["from_price"] == "1"
    assert manzana_item["from_unit_price"] == "0.9"
    assert manzana_item["image_url"] == IMAGE_MANZANA
    assert manzana_item["base_unit"] == "kg"
    assert manzana_item["product_count"] == 2


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
    assert detail["exact_only"] is False

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


def test_canonicals_of_an_exact_only_leaf_are_marked(client, session: Session, catalog: Catalog):
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    tinte_cat = _chain_category(session, chain_id, "T-TINTE", "tinte")
    tinte = _canonical(session, "tinte", "Tinte castaño")
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=tinte_cat,
        zone_id=zone_id,
        sku="tinte-castano",
        name="Tinte castaño",
        price="4.00",
        quantity="1",
        unit="kg",
        canonical_id=tinte,
    )
    session.commit()

    items = client.get("/api/canonicals", params={"category": "tinte"}).json()["items"]
    assert [(item["name"], item["exact_only"]) for item in items] == [("Tinte castaño", True)]
    detail = client.get(f"/api/canonicals/{tinte}").json()
    assert detail["exact_only"] is True


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

    # Canonical whose products have no size (base_quantity is None)
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    platano_cat = _scalar(session, "select id from chain_category where code = 'T-PLATANO'")
    no_size_canon = _canonical(session, "platano", "Plátano sin tamaño")
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=platano_cat,
        zone_id=zone_id,
        sku="platano-no-size",
        name="Plátano sin tamaño",
        price="1.00",
        quantity=None,
        unit=None,
        canonical_id=no_size_canon,
    )
    session.flush()
    res3 = client.get(f"/api/canonicals/{no_size_canon}")
    assert res3.status_code == 404
    assert res3.json()["detail"] == "Producto no encontrado."

    # And it must be excluded from the listing
    res_list = client.get("/api/canonicals", params={"category": "platano"})
    assert res_list.status_code == 200
    listed_names = [item["name"] for item in res_list.json()["items"]]
    assert "Plátano sin tamaño" not in listed_names


def test_canonicals_chain_filter(client, session: Session, catalog: Catalog):
    platano_canon = catalog.canonicals["platano"]
    dia_chain_id = _scalar(session, "select id from chain where code = 'dia'")
    dia_zone_id = _scalar(
        session,
        "select id from zone where chain_id = :chain order by id limit 1",
        chain=dia_chain_id,
    )
    session.execute(
        text(
            "insert into store (chain_id, zone_id, name, geom)"
            " values (:chain, :zone, 'Dia León',"
            "  st_setsrid(st_makepoint(-5.57, 42.6), 4326)::geography)"
        ),
        {"chain": dia_chain_id, "zone": dia_zone_id},
    )
    dia_cat = _chain_category(session, dia_chain_id, "T-DIA-PLATANO", "platano")
    _product(
        session,
        chain_id=dia_chain_id,
        chain_category_id=dia_cat,
        zone_id=dia_zone_id,
        sku="dia-platano-1",
        name="Plátano Dia",
        price="0.80",
        quantity="1",
        unit="kg",
        canonical_id=platano_canon,
    )
    session.flush()

    # Without filter, lists both chains and product_count is 4
    res_all = client.get("/api/canonicals", params={"category": "platano"})
    assert res_all.status_code == 200
    item_all = res_all.json()["items"][0]
    assert item_all["from_price"] == "0.8"
    assert item_all["from_unit_price"] == "0.8"
    assert item_all["product_count"] == 4
    assert item_all["chains"] == ["dia", "mercadona"]

    # Filtered by mercadona: from_* and product_count trim to mercadona, but chains lists both
    res_mercadona = client.get(
        "/api/canonicals", params={"chain": "mercadona", "category": "platano"}
    )
    assert res_mercadona.status_code == 200
    items_mercadona = res_mercadona.json()["items"]
    assert len(items_mercadona) == 1
    item_mercadona = items_mercadona[0]
    assert item_mercadona["name"] == "Plátano de Canarias"
    assert item_mercadona["from_price"] == "1.2"
    assert item_mercadona["from_unit_price"] == "1.2"
    assert item_mercadona["product_count"] == 3
    assert item_mercadona["chains"] == ["dia", "mercadona"]

    # Filtered by dia: from_* and product_count trim to dia, chains lists both
    res_dia = client.get("/api/canonicals", params={"chain": "dia", "category": "platano"})
    assert res_dia.status_code == 200
    items_dia = res_dia.json()["items"]
    assert len(items_dia) == 1
    item_dia = items_dia[0]
    assert item_dia["from_price"] == "0.8"
    assert item_dia["from_unit_price"] == "0.8"
    assert item_dia["product_count"] == 1
    assert item_dia["chains"] == ["dia", "mercadona"]

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
    # Put "Bebida de plátano" in category "bebidas" (alphabetically before "Plátano")
    # and cheaper (0.50 < 1.20)
    bebidas_cat = _chain_category(session, chain_id, "T-BEBIDAS", "bebidas")
    bebida_canon = _canonical(session, "bebidas", "Bebida de plátano")

    _product(
        session,
        chain_id=chain_id,
        chain_category_id=bebidas_cat,
        zone_id=zone_id,
        sku="bebida-platano-canon",
        name="Bebida de plátano",
        price="0.50",
        quantity="1",
        unit="l",
        image_url=IMAGE_BEBIDA,
        canonical_id=bebida_canon,
    )

    # Category-form branch case: "Banana de Canarias" in category "platano".
    # Its name does not start with "platano" and does not contain the word "platano",
    # but the query "platanos" matches category "platano" (forms include "plátano" and "banana").
    platano_cat = _scalar(session, "select id from chain_category where code = 'T-PLATANO'")
    banana_canon = _canonical(session, "platano", "Banana de Canarias")
    _product(
        session,
        chain_id=chain_id,
        chain_category_id=platano_cat,
        zone_id=zone_id,
        sku="banana-canon",
        name="Banana de Canarias",
        price="2.50",
        quantity="1",
        unit="kg",
        canonical_id=banana_canon,
    )
    session.flush()

    response = client.get("/api/canonicals", params={"q": "platano"})
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "Plátano de Canarias" in names
    assert "Banana de Canarias" in names
    assert "Bebida de plátano" in names
    # Name prefix relevance (rank 0) beats non-matching category (rank 1),
    # despite "Bebidas" < "Plátano"
    assert names.index("Plátano de Canarias") < names.index("Bebida de plátano")
    # Category form branch relevance (rank 0) beats non-matching category (rank 1),
    # despite "Bebidas" < "Plátano"
    assert names.index("Banana de Canarias") < names.index("Bebida de plátano")

    # Prefix match without category form: plural "platanos"
    res_prefix = client.get("/api/canonicals", params={"q": "platanos"})
    assert res_prefix.status_code == 200
    names_prefix = [item["name"] for item in res_prefix.json()["items"]]
    assert "Plátano de Canarias" in names_prefix
    assert "Bebida de plátano" in names_prefix
    assert names_prefix.index("Plátano de Canarias") < names_prefix.index("Bebida de plátano")


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
