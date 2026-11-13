"""The recommendation endpoint against a synthetic catalog (database tests)."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from smart_basket.api.recommendations import get_routing_engine
from smart_basket.optimizer import ENGINE_VERSION

from .conftest import FakeRouting

pytestmark = pytest.mark.db


def item(text: str, category_key: str, quantity: str, unit: str, **extra) -> dict:
    return {
        "text": text,
        "category_key": category_key,
        "quantity": quantity,
        "unit": unit,
        "brand": None,
        "private_label_ok": True,
        **extra,
    }


FIVE_ITEMS = [
    item("leche semidesnatada", "leche", "2", "l"),
    item("yogur natural", "yogur", "4", "ud"),
    item("plátano", "platano", "1", "kg"),
    item("queso curado", "queso", "0.5", "kg"),
    item("huevos", "huevos", "12", "ud"),
]


def payload(items: list[dict], **overrides) -> dict:
    body = {
        "items": items,
        "origin": {"lat": 42.5987, "lon": -5.5671},
        "mode": "walk",
        "max_stores": 2,
        "priority_mode": "balanced",
        "return_to_origin": True,
        "degraded": False,
    }
    body.update(overrides)
    return body


def test_five_item_basket_has_prices_minutes_and_route(world):
    response = world.client.post("/api/recommendations", json=payload(FIVE_ITEMS))
    assert response.status_code == 200
    body = response.json()

    assert body["engine_version"] == ENGINE_VERSION
    assert body["data_as_of"] == "2026-11-13T05:07:00Z"
    assert body["total_cost"] == "11.70"
    assert body["minutes"] == "8.5"
    assert body["missing"] == []
    assert body["degraded"] is False

    assert len(body["stores"]) == 1
    store = body["stores"][0]
    assert store["name"] == "Mercadona"
    assert store["chain"] == "Mercadona"
    assert store["position"] == 1
    assert store["lat"] == pytest.approx(42.6)
    assert store["lon"] == pytest.approx(-5.57)
    assert store["subtotal"] == "11.70"

    assert [line["text"] for line in store["lines"]] == [i["text"] for i in FIVE_ITEMS]
    lines = [
        (line["product_name"], line["packs"], line["quantity_bought"], line["cost"])
        for line in store["lines"]
    ]
    assert lines == [
        ("Leche semidesnatada Hacendado", 2, "2", "1.90"),
        ("Yogur natural Hacendado", 1, "4", "1.20"),
        ("Plátano de Canarias", 1, "1", "1.50"),
        ("Queso curado Hacendado", 1, "0.5", "5.00"),
        ("Huevos frescos Hacendado", 1, "12", "2.10"),
    ]

    assert body["route"] == [
        [42.5987, -5.5671],
        [42.6, -5.57],
        [42.5987, -5.5671],
    ]
    assert body["explanation"] == (
        "Compra en Mercadona. Total: 11,70 € y 9 min de trayecto (ida y vuelta)."
    )


def test_line_without_products_is_missing_with_its_reason(world):
    response = world.client.post(
        "/api/recommendations",
        json=payload([*FIVE_ITEMS, item("arroz redondo", "arroz", "1", "kg")]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["missing"] == [{"text": "arroz redondo", "reason": "not_available", "stop": None}]
    assert body["explanation"].endswith(
        "No hemos encontrado «arroz redondo» en las tiendas cercanas."
    )


def test_routing_failure_returns_503(world):
    world.client.app.dependency_overrides[get_routing_engine] = lambda: FakeRouting(fail=True)
    response = world.client.post("/api/recommendations", json=payload(FIVE_ITEMS))
    assert response.status_code == 503
    assert response.json() == {
        "detail": "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos."
    }


def test_no_stores_near_returns_422(world):
    response = world.client.post(
        "/api/recommendations", json=payload(FIVE_ITEMS, origin={"lat": 0.0, "lon": 0.0})
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "No hay tiendas con precios cerca de este punto."}


def test_empty_items_are_rejected(world):
    response = world.client.post("/api/recommendations", json=payload([]))
    assert response.status_code == 422


def test_same_request_twice_gives_the_same_basket(world):
    first = world.client.post("/api/recommendations", json=payload(FIVE_ITEMS)).json()
    second = world.client.post("/api/recommendations", json=payload(FIVE_ITEMS)).json()
    assert first["id"] != second["id"]
    for body in (first, second):
        body.pop("id")
    assert first == second


def test_recommendation_is_stored_with_a_rounded_origin(world):
    body = world.client.post("/api/recommendations", json=payload(FIVE_ITEMS)).json()
    row = (
        world.connection.execute(
            text(
                "select id::text as id, origin_cell, engine_version, travel_mode, priority_mode, "
                "max_stores, request, result from recommendation where id = cast(:id as uuid)"
            ),
            {"id": body["id"]},
        )
        .mappings()
        .one()
    )
    assert row["id"] == body["id"]
    assert row["origin_cell"] == "42.600,-5.565"
    assert "42.5987" not in row["origin_cell"]
    assert "-5.5671" not in row["origin_cell"]
    assert row["engine_version"] == ENGINE_VERSION
    assert (row["travel_mode"], row["priority_mode"], row["max_stores"]) == (
        "walk",
        "balanced",
        2,
    )
    assert row["request"]["items"][0]["category_key"] == "leche"
    assert row["result"]["total_cost"] == "11.70"

    parts = (
        world.connection.execute(
            text(
                "select count(*) as total, count(canonical_id) as with_canonical "
                "from recommendation_item where recommendation_id = cast(:id as uuid)"
            ),
            {"id": body["id"]},
        )
        .mappings()
        .one()
    )
    assert parts["total"] == 5
    assert parts["with_canonical"] == 0


def test_request_body_is_not_mutated_by_the_endpoint(world):
    body = payload(FIVE_ITEMS)
    original = copy.deepcopy(body)
    assert world.client.post("/api/recommendations", json=body).status_code == 200
    assert body == original
