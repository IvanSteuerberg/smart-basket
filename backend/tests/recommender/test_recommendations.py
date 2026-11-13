"""The recommendation endpoint against a synthetic catalog (database tests)."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.recommendations import get_routing_engine
from smart_basket.config import get_settings
from smart_basket.optimizer import ENGINE_VERSION, PriorityMode, Unit
from smart_basket.recommender import RecommendationQuery, recommend
from smart_basket.recommender.catalog import Item
from smart_basket.routing import GeoPoint, TravelMode

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
    assert store["address"] == "Calle Ancha 1, León"
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
    assert row["request"]["origin"] == "42.600,-5.565"
    assert row["result"]["total_cost"] == "11.70"
    assert "route" not in row["result"]

    request_text = world.connection.execute(
        text("select request::text from recommendation where id = cast(:id as uuid)"),
        {"id": body["id"]},
    ).scalar_one()
    result_text = world.connection.execute(
        text("select result::text from recommendation where id = cast(:id as uuid)"),
        {"id": body["id"]},
    ).scalar_one()
    for exact in ("42.5987", "-5.5671"):
        assert exact not in request_text
        assert exact not in result_text

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


def test_brand_filter_matches_whole_words_only(world):
    response = world.client.post(
        "/api/recommendations",
        json=payload([item("refresco dia", "refresco", "1", "ud", brand="Dia")]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["missing"] == []
    assert body["stores"][0]["lines"][0]["product_name"] == "Refresco Dia cola"
    assert body["total_cost"] == "2.00"


def test_private_label_from_the_brand_table_is_excluded(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("yogur natural", "yogur", "4", "ud", private_label_ok=False)]),
    ).json()
    assert body["stores"] == []
    assert body["total_cost"] == "0"
    assert body["minutes"] == "0"
    assert body["route"] == []
    assert body["data_as_of"] is None
    assert body["missing"] == [{"text": "yogur natural", "reason": "not_available", "stop": None}]


def test_short_item_does_not_fall_back_to_a_substring(world):
    body = world.client.post(
        "/api/recommendations", json=payload([item("pan", "pan", "1", "kg")])
    ).json()
    assert body["missing"] == []
    assert body["stores"][0]["lines"][0]["product_name"] == "Pan de pueblo"
    assert body["total_cost"] == "2.00"


def test_no_line_with_products_gives_an_empty_answer(world):
    body = world.client.post(
        "/api/recommendations", json=payload([item("arroz redondo", "arroz", "1", "kg")])
    ).json()
    assert body["stores"] == []
    assert body["total_cost"] == "0"
    assert body["minutes"] == "0"
    assert body["route"] == []
    assert body["data_as_of"] is None
    assert body["missing"] == [{"text": "arroz redondo", "reason": "not_available", "stop": None}]
    assert body["explanation"] == (
        "No hemos encontrado nada de tu lista en las tiendas cercanas. "
        "No hemos encontrado «arroz redondo» en las tiendas cercanas."
    )


def test_unknown_categories_give_an_empty_answer(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("producto misterioso", "no-existe", "1", "ud")]),
    ).json()
    assert body["stores"] == []
    assert body["total_cost"] == "0"
    assert body["minutes"] == "0"
    assert body["route"] == []
    assert body["data_as_of"] is None
    assert body["missing"] == [
        {"text": "producto misterioso", "reason": "not_available", "stop": None}
    ]
    assert body["explanation"].startswith(
        "No hemos encontrado nada de tu lista en las tiendas cercanas."
    )


def test_lines_of_the_same_leaf_keep_their_own_brand(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload(
            [
                item("leche semidesnatada", "leche", "2", "l"),
                item("leche pascual", "leche", "1", "l", brand="Pascual"),
            ]
        ),
    ).json()
    assert body["missing"] == []
    lines = [(line["text"], line["product_name"]) for line in body["stores"][0]["lines"]]
    assert lines == [
        ("leche semidesnatada", "Leche semidesnatada Hacendado"),
        ("leche pascual", "Leche entera Pascual"),
    ]


def test_a_brand_without_products_is_reported_as_missing(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("leche puleva", "leche", "1", "l", brand="Puleva")]),
    ).json()
    assert body["missing"] == [{"text": "leche puleva", "reason": "not_available", "stop": None}]


def test_brand_alias_finds_the_brand_products(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("refresco", "refresco", "1", "ud", brand="cocacola")]),
    ).json()
    assert body["missing"] == []
    assert body["stores"][0]["lines"][0]["product_name"] == "Coca Cola Zero"


def test_product_of_another_dimension_is_not_offered(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("leche", "leche", "1", "ud")]),
    ).json()
    assert body["missing"] == []
    assert body["stores"][0]["lines"][0]["product_name"] == "Leche semidesnatada Hacendado"
    assert body["total_cost"] == "0.95"


def test_product_named_like_the_line_wins(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("papel de horno", "papel_horno", "1", "ud")]),
    ).json()
    assert body["stores"][0]["lines"][0]["product_name"] == "Papel de horno Bosque Verde"
    assert body["total_cost"] == "1.20"


def test_products_sharing_most_words_win(world):
    # No product has both words; the ones with "papel" beat the raffia bag.
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("papel d encerado", "papel_horno", "1", "ud")]),
    ).json()
    assert body["stores"][0]["lines"][0]["product_name"] != "Bolsa de rafia"


def test_counted_leaf_accepts_weighed_products(world):
    # Bread or paper sold by kg still answers a leaf counted in units.
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("papel vegetal", "papel_horno", "1", "ud")]),
    ).json()
    assert body["missing"] == []
    assert body["stores"][0]["lines"][0]["product_name"] == "Papel vegetal a granel"


def test_line_without_a_matching_name_keeps_every_product(world):
    body = world.client.post(
        "/api/recommendations",
        json=payload([item("pollo", "aves", "1", "kg")]),
    ).json()
    assert body["stores"][0]["lines"][0]["product_name"] == "Muslo de pavo"
    assert body["total_cost"] == "2.50"


def _query(return_to_origin: bool) -> RecommendationQuery:
    return RecommendationQuery(
        items=tuple(
            Item(
                text=line["text"],
                category_key=line["category_key"],
                quantity=Decimal(line["quantity"]),
                unit=Unit(line["unit"]),
            )
            for line in FIVE_ITEMS
        ),
        origin=GeoPoint(42.5987, -5.5671),
        mode=TravelMode.WALK,
        max_stores=2,
        priority_mode=PriorityMode.BALANCED,
        return_to_origin=return_to_origin,
        degraded=False,
        payload={},
    )


def test_route_goes_origin_stores_origin_when_returning(world):
    session = Session(bind=world.connection)
    body = recommend(session, _query(True), FakeRouting(), date(2026, 11, 13), get_settings())
    assert body.route == [
        [42.5987, -5.5671],
        [42.6, -5.57],
        [42.5987, -5.5671],
    ]


def test_route_goes_origin_store_when_not_returning(world):
    session = Session(bind=world.connection)
    body = recommend(session, _query(False), FakeRouting(), date(2026, 11, 13), get_settings())
    assert body.route == [
        [42.5987, -5.5671],
        [42.6, -5.57],
    ]
