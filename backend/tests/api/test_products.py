"""Sections, product listing and product detail over a small synthetic catalog.

Chains, zones and taxonomy come from the packaged seed; the products, their prices and photos
exist only in the test database and are rolled back after each test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

IMAGE_ONE = "https://cdn.example/platano-1.jpg"
IMAGE_TWO = "https://cdn.example/platano-2.jpg"
IMAGE_PAN_ONE = "https://cdn.example/pan-1.jpg"
IMAGE_PAN_TWO = "https://cdn.example/pan-2.jpg"
IMAGE_YOGUR = "https://cdn.example/yogur-1.jpg"


@dataclass(frozen=True)
class Catalog:
    products: dict[str, int]
    canonicals: dict[str, int]


def _scalar(session: Session, sql: str, **params):
    return session.execute(text(sql), params).scalar_one()


def _chain_category(session: Session, chain_id: int, code: str, category_key: str) -> int:
    return _scalar(
        session,
        "insert into chain_category (chain_id, code, name, category_id)"
        " select :chain, :code, :code, id from category where key = :key returning id",
        chain=chain_id,
        code=code,
        key=category_key,
    )


def _canonical(session: Session, category_key: str, name: str) -> int:
    return _scalar(
        session,
        "insert into canonical_product (category_id, name, base_unit)"
        " select id, :name, 'kg' from category where key = :key returning id",
        key=category_key,
        name=name,
    )


def _product(
    session: Session,
    *,
    chain_id: int,
    chain_category_id: int,
    zone_id: int,
    sku: str,
    name: str,
    price: str | None,
    quantity: str | None = "1",
    unit: str | None = "kg",
    packaging: str | None = None,
    image_url: str | None = None,
    canonical_id: int | None = None,
    active: bool = True,
    available: bool = True,
) -> int:
    product_id = _scalar(
        session,
        "insert into chain_product"
        " (chain_id, chain_sku, name, base_quantity, base_unit, packaging, image_url,"
        "  chain_category_id, canonical_id, match_method, is_active)"
        " values (:chain, :sku, :name, :quantity, :unit, :packaging, :image,"
        "  :category, :canonical, :method, :active) returning id",
        chain=chain_id,
        sku=sku,
        name=name,
        quantity=Decimal(quantity) if quantity is not None else None,
        unit=unit if quantity is not None else None,
        packaging=packaging,
        image=image_url,
        category=chain_category_id,
        canonical=canonical_id,
        method="rule" if canonical_id is not None else None,
        active=active,
    )
    session.execute(
        text(
            "insert into chain_product_zone (chain_product_id, zone_id, is_available)"
            " values (:product, :zone, :available)"
        ),
        {"product": product_id, "zone": zone_id, "available": available},
    )
    if price is not None:
        session.execute(
            text(
                "insert into price_current (chain_product_id, zone_id, price, valid_from)"
                " values (:product, :zone, :price, '2026-11-13 05:00:00+00')"
            ),
            {"product": product_id, "zone": zone_id, "price": Decimal(price)},
        )
    return product_id


@pytest.fixture
def catalog(session: Session) -> Catalog:
    chain_id = _scalar(session, "select id from chain where code = 'mercadona'")
    zone_id = _scalar(
        session,
        "select z.id from zone z join chain c on c.id = z.chain_id"
        " where c.code = 'mercadona' and z.kind = 'warehouse' order by z.id limit 1",
    )
    session.execute(
        text(
            "insert into store (chain_id, zone_id, name, geom)"
            " values (:chain, :zone, 'Mercadona León',"
            "  st_setsrid(st_makepoint(-5.57, 42.6), 4326)::geography)"
        ),
        {"chain": chain_id, "zone": zone_id},
    )
    platanos = _chain_category(session, chain_id, "T-PLATANO", "platano")
    pan = _chain_category(session, chain_id, "T-PAN", "pan_molde")
    yogur = _chain_category(session, chain_id, "T-YOGUR", "yogur_natural")
    canonicals = {
        "platano": _canonical(session, "platano", "Plátano de Canarias"),
        "pan": _canonical(session, "pan_molde", "Pan de molde integral"),
        "yogur": _canonical(session, "yogur_natural", "Yogur natural"),
    }

    products: dict[str, int] = {}

    def add(sku: str, name: str, price: str | None, category: int, **fields) -> None:
        products[sku] = _product(
            session,
            chain_id=chain_id,
            chain_category_id=category,
            zone_id=zone_id,
            sku=sku,
            name=name,
            price=price,
            **fields,
        )

    add(
        "platano-1",
        "Plátano de Canarias",
        "1.50",
        platanos,
        image_url=IMAGE_ONE,
        canonical_id=canonicals["platano"],
    )
    add(
        "platano-2",
        "Plátano ecológico",
        "2.00",
        platanos,
        image_url=IMAGE_TWO,
        canonical_id=canonicals["platano"],
    )
    add("platano-3", "Fruta de temporada", "3.00", platanos)
    add(
        "platano-4",
        "Plátano de Canarias bolsa",
        "1.20",
        platanos,
        packaging="bolsa",
        canonical_id=canonicals["platano"],
    )
    add("platano-hidden", "Plátano no disponible", "1.00", platanos, available=False)
    add("platano-inactive", "Plátano retirado", "1.00", platanos, active=False)
    add("platano-noprice", "Plátano sin precio", None, platanos)
    add(
        "pan-1",
        "Pan de molde Hacendado",
        "2.00",
        pan,
        quantity="0.45",
        packaging="bolsa",
        image_url=IMAGE_PAN_ONE,
    )
    add(
        "pan-2",
        "Pan de molde integral Bimbo",
        "1.80",
        pan,
        quantity="0.45",
        image_url=IMAGE_PAN_TWO,
        canonical_id=canonicals["pan"],
    )
    add("pan-3", "Pan Bimbollos", "1.00", pan, quantity="0.45")
    add(
        "yogur-1",
        "Yogur natural Pascual",
        "2.10",
        yogur,
        image_url=IMAGE_YOGUR,
        canonical_id=canonicals["yogur"],
    )
    add("yogur-2", "Yogur griego", "1.00", yogur, quantity=None)
    add("yogur-alias", "Yogur natural Central Lechera", "1.50", yogur)
    session.flush()
    return Catalog(products=products, canonicals=canonicals)


def _items(client, **params) -> list[dict]:
    response = client.get("/api/products", params={"size": 60, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _names(client, **params) -> list[str]:
    return [item["name"] for item in _items(client, **params)]


def test_sections_count_products_and_choose_a_photo(client, catalog):
    response = client.get("/api/sections")
    assert response.status_code == 200
    sections = response.json()["sections"]
    assert [section["key"] for section in sections] == [
        "fruta_verdura",
        "lacteos_huevos",
        "panaderia",
    ]
    by_key = {section["key"]: section for section in sections}
    assert set(by_key["fruta_verdura"]) == {"key", "name", "products", "image_url"}
    assert by_key["fruta_verdura"]["products"] == 4
    assert by_key["fruta_verdura"]["image_url"] == IMAGE_ONE
    assert by_key["lacteos_huevos"]["products"] == 3
    assert by_key["lacteos_huevos"]["image_url"] == IMAGE_YOGUR
    assert by_key["panaderia"]["products"] == 3
    assert by_key["panaderia"]["image_url"] == IMAGE_PAN_ONE


def test_section_filter_uses_the_subtree(client, catalog):
    assert _names(client, section="fruta_verdura") == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Plátano ecológico",
        "Fruta de temporada",
    ]
    assert len(_names(client, section="panaderia")) == 3
    assert len(_names(client, section="lacteos_huevos")) == 3


def test_category_filter_uses_the_subtree(client, catalog):
    assert len(_items(client, category="fruta")) == 4
    assert len(_items(client, category="platano")) == 4
    assert len(_items(client, category="lacteos_huevos")) == 3
    assert len(_items(client, category="yogures")) == 3


def test_search_tolerates_accents_plurals_and_connectors(client, catalog):
    assert _names(client, q="platanos") == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Plátano ecológico",
    ]
    assert _names(client, q="plátano de canarias") == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
    ]
    assert _names(client, q="pan hacendado") == ["Pan de molde Hacendado"]


def test_search_matches_the_forms_of_the_category(client, catalog):
    assert len(_items(client, q="banana")) == 4
    assert _names(client, q="banana") == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Plátano ecológico",
        "Fruta de temporada",
    ]


def test_sorts_and_paging(client, catalog):
    assert _names(client, sort="unit_price") == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Yogur natural Central Lechera",
        "Plátano ecológico",
        "Yogur natural Pascual",
        "Pan Bimbollos",
        "Fruta de temporada",
        "Pan de molde integral Bimbo",
        "Pan de molde Hacendado",
        "Yogur griego",
    ]
    assert _names(client, sort="price") == [
        "Pan Bimbollos",
        "Yogur griego",
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
        "Yogur natural Central Lechera",
        "Pan de molde integral Bimbo",
        "Pan de molde Hacendado",
        "Plátano ecológico",
        "Yogur natural Pascual",
        "Fruta de temporada",
    ]
    assert _names(client, sort="name") == [
        "Fruta de temporada",
        "Pan Bimbollos",
        "Pan de molde Hacendado",
        "Pan de molde integral Bimbo",
        "Plátano de Canarias",
        "Plátano de Canarias bolsa",
        "Plátano ecológico",
        "Yogur griego",
        "Yogur natural Central Lechera",
        "Yogur natural Pascual",
    ]

    first = client.get(
        "/api/products",
        params={"section": "fruta_verdura", "sort": "name", "page": 1, "size": 2},
    ).json()
    assert first["total"] == 4
    assert first["page"] == 1
    assert first["size"] == 2
    assert [item["name"] for item in first["items"]] == [
        "Fruta de temporada",
        "Plátano de Canarias",
    ]
    second = client.get(
        "/api/products",
        params={"section": "fruta_verdura", "sort": "name", "page": 2, "size": 2},
    ).json()
    assert [item["name"] for item in second["items"]] == [
        "Plátano de Canarias bolsa",
        "Plátano ecológico",
    ]


def test_product_fields(client, catalog):
    items = {item["name"]: item for item in _items(client)}
    banana = items["Plátano de Canarias"]
    assert banana["id"] == catalog.products["platano-1"]
    assert banana["chain"] == "Mercadona"
    assert banana["price"] == "1.5"
    assert banana["unit_price"] == "1.5"
    assert banana["base_quantity"] == "1"
    assert banana["base_unit"] == "kg"
    assert banana["packaging"] is None
    assert banana["image_url"] == IMAGE_ONE

    pan = items["Pan de molde Hacendado"]
    assert pan["price"] == "2"
    assert pan["unit_price"] == "4.4444"
    assert pan["base_quantity"] == "0.45"
    assert pan["packaging"] == "bolsa"
    assert pan["canonical"] is None

    loose = items["Yogur griego"]
    assert loose["base_quantity"] is None
    assert loose["base_unit"] is None
    assert loose["unit_price"] is None


def test_brand_and_private_label_come_from_the_name(client, catalog):
    items = {item["name"]: item for item in _items(client)}
    assert items["Pan de molde Hacendado"]["brand"] == "Hacendado"
    assert items["Pan de molde Hacendado"]["private_label"] is True
    assert items["Pan de molde integral Bimbo"]["brand"] == "Bimbo"
    assert items["Pan de molde integral Bimbo"]["private_label"] is False
    assert items["Pan Bimbollos"]["brand"] is None
    assert items["Yogur natural Pascual"]["brand"] == "Pascual"
    assert items["Yogur natural Pascual"]["private_label"] is False
    assert items["Yogur natural Central Lechera"]["brand"] == "Central Lechera Asturiana"


def test_canonical_is_shown_when_set(client, catalog):
    items = {item["name"]: item for item in _items(client)}
    canonical = items["Plátano ecológico"]["canonical"]
    assert canonical == {
        "id": catalog.canonicals["platano"],
        "name": "Plátano de Canarias",
        "category_key": "platano",
        "category_name": "Plátano",
    }
    assert items["Fruta de temporada"]["canonical"] is None


def test_product_detail_lists_the_cheapest_alternatives(client, catalog):
    response = client.get(f"/api/products/{catalog.products['platano-2']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["name"] == "Plátano ecológico"
    assert [item["name"] for item in detail["alternatives"]] == [
        "Plátano de Canarias bolsa",
        "Plátano de Canarias",
    ]
    assert all(item["id"] != catalog.products["platano-2"] for item in detail["alternatives"])

    loose = client.get(f"/api/products/{catalog.products['yogur-2']}").json()
    assert loose["canonical"] is None
    assert loose["alternatives"] == []


def test_unknown_or_unavailable_products_are_404(client, catalog):
    for product_id in (999_999, catalog.products["platano-hidden"]):
        response = client.get(f"/api/products/{product_id}")
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)


def test_invalid_parameters_are_422_with_a_spanish_detail(client, catalog):
    cases = [
        {"size": 0},
        {"size": 61},
        {"page": 0},
        {"sort": "cheapest"},
        {"section": "no-existe"},
        {"category": "no-existe"},
    ]
    for params in cases:
        response = client.get("/api/products", params=params)
        assert response.status_code == 422, params
        assert isinstance(response.json()["detail"], str), params
