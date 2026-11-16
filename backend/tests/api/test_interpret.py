"""List interpretation through the API, with fake LLM providers (no network)."""

import os
from decimal import Decimal

import pytest
from sqlalchemy import text

from smart_basket.api.catalog import get_llm_provider
from smart_basket.llm import LLMError

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


class FakeProvider:
    name = "fake"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def generate_json(self, system, user, schema):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.answer

    def generate_text(self, prompt):
        return ""


def with_provider(client, provider):
    client.app.dependency_overrides[get_llm_provider] = lambda: provider


def test_rule_lines_are_interpreted_without_the_llm(client):
    provider = FakeProvider()
    with_provider(client, provider)
    response = client.post("/api/interpret", json={"text": "2 l de leche"})
    assert response.status_code == 200
    body = response.json()
    assert body["llm_used"] is False
    assert body["degraded"] is False
    assert provider.calls == []

    item = body["items"][0]
    assert set(item) == {
        "line",
        "text",
        "item",
        "quantity",
        "unit",
        "category_key",
        "category_name",
        "brand",
        "alternatives",
        "resolved",
        "needs_llm",
        "image_url",
        "options",
    }
    assert item["image_url"] is None
    assert item["options"] == []
    assert item["line"] == 0
    assert item["quantity"] == "2"
    assert item["unit"] == "l"
    assert item["category_key"] == "leche"
    assert item["category_name"] == "Leche"
    assert item["resolved"] is True
    assert item["needs_llm"] is False


def test_rule_lines_keep_the_category_of_their_own_match(client):
    provider = FakeProvider()
    with_provider(client, provider)
    body = client.post("/api/interpret", json={"text": "colacao, pasta/espaguetis"}).json()
    assert provider.calls == []

    colacao, pasta = body["items"]
    assert colacao["category_key"] == "cacao_soluble"
    assert colacao["category_name"] == "Cacao soluble"
    # "pasta" alone is vague; the specific alternative wins.
    assert pasta["category_key"] == "espaguetis"
    assert pasta["category_name"] == "Espaguetis"


def test_unresolved_lines_go_to_the_llm(client):
    provider = FakeProvider(
        {
            "items": [
                {
                    "item": "tortilla de patatas",
                    "quantity": 0.5,
                    "unit": "kg",
                    "ambiguous": False,
                }
            ]
        }
    )
    with_provider(client, provider)
    body = client.post("/api/interpret", json={"text": "leche, algo para la cena"}).json()
    assert provider.calls == ["algo para la cena"]
    assert body["llm_used"] is True
    assert body["degraded"] is False

    leche, tortilla = body["items"]
    assert leche["category_key"] == "leche"
    assert leche["resolved"] is True

    assert tortilla["line"] == 1
    assert tortilla["item"] == "tortilla de patatas"
    assert tortilla["quantity"] == "0.5"
    assert tortilla["unit"] == "kg"
    assert tortilla["category_key"] == "tortilla"
    assert tortilla["category_name"] == "Tortilla de patata"
    assert tortilla["resolved"] is True
    assert tortilla["needs_llm"] is False


def test_llm_items_keep_the_order_of_the_unresolved_lines(client):
    provider = FakeProvider(
        {
            "items": [
                {"item": "servilletas", "quantity": 1, "unit": "ud", "ambiguous": False},
                {"item": "algo para la cena", "quantity": 1, "unit": "ud", "ambiguous": True},
            ]
        }
    )
    with_provider(client, provider)
    body = client.post(
        "/api/interpret", json={"text": "leche, algo para la cena, cosas del finde"}
    ).json()
    assert provider.calls == ["algo para la cena\ncosas del finde"]

    items = body["items"]
    assert [item["line"] for item in items] == [0, 1, 2]
    assert [item["text"] for item in items] == [
        "leche",
        "servilletas",
        "algo para la cena",
    ]


def test_no_provider_leaves_the_unresolved_line_and_degrades(client):
    with_provider(client, None)
    body = client.post("/api/interpret", json={"text": "leche, algo para la cena"}).json()
    assert body["llm_used"] is False
    assert body["degraded"] is True

    leche, missing = body["items"]
    assert leche["resolved"] is True
    assert missing["text"] == "algo para la cena"
    assert missing["resolved"] is False
    assert missing["needs_llm"] is True
    assert missing["category_key"] is None


def test_llm_failure_degrades_instead_of_failing(client):
    with_provider(client, FakeProvider(error=LLMError("timeout")))
    body = client.post("/api/interpret", json={"text": "leche, algo para la cena"}).json()
    assert body["llm_used"] is False
    assert body["degraded"] is True
    assert body["items"][1]["needs_llm"] is True


def test_text_length_is_validated(client):
    with_provider(client, None)
    assert client.post("/api/interpret", json={"text": ""}).status_code == 422
    assert client.post("/api/interpret", json={"text": "x" * 2001}).status_code == 422
    assert client.post("/api/interpret", json={"text": "x" * 2000}).status_code == 200


def add_option_product(
    session,
    category_key: str,
    *,
    sku: str,
    base_quantity: str,
    base_unit: str,
    price: str,
    image_url: str,
) -> None:
    """A priced synthetic product in a seeded leaf, matched to a canonical product."""
    category_id = session.execute(
        text("select id from category where key = :key"), {"key": category_key}
    ).scalar_one()
    canonical_id = session.execute(
        text(
            "insert into canonical_product (category_id, name, variant_key, base_unit)"
            " values (:category, :name, '', :unit) returning id"
        ),
        {"category": category_id, "name": f"Canónico {sku}", "unit": base_unit},
    ).scalar_one()
    product_id = session.execute(
        text(
            "insert into chain_product (chain_id, chain_sku, name, base_quantity, base_unit,"
            " canonical_id, match_method, match_confidence, image_url)"
            " select c.id, :sku, :name, :quantity, :unit, :canonical, 'rule', 1.0, :image"
            " from chain c where c.code = 'mercadona' returning id"
        ),
        {
            "sku": sku,
            "name": f"Producto {sku}",
            "quantity": Decimal(base_quantity),
            "unit": base_unit,
            "canonical": canonical_id,
            "image": image_url,
        },
    ).scalar_one()
    zone_id = session.execute(
        text(
            "select z.id from zone z join chain c on c.id = z.chain_id"
            " where c.code = 'mercadona' order by z.id limit 1"
        )
    ).scalar_one()
    session.execute(
        text(
            "insert into chain_product_zone (chain_product_id, zone_id, is_available)"
            " values (:product, :zone, true)"
        ),
        {"product": product_id, "zone": zone_id},
    )
    session.execute(
        text(
            "insert into price_current (chain_product_id, zone_id, price, valid_from, last_seen_at)"
            " values (:product, :zone, :price, '2026-11-13 05:00:00+00',"
            " '2026-11-13 05:07:00+00')"
        ),
        {"product": product_id, "zone": zone_id, "price": Decimal(price)},
    )
    session.flush()


def test_an_interpreted_line_carries_the_photo_of_its_cheapest_product(client, session):
    add_option_product(
        session,
        "leche",
        sku="LECHE1",
        base_quantity="1",
        base_unit="l",
        price="0.95",
        image_url="https://example.test/leche.jpg",
    )
    session.commit()

    with_provider(client, FakeProvider())
    body = client.post("/api/interpret", json={"text": "leche"}).json()

    (item,) = body["items"]
    assert item["category_key"] == "leche"
    assert item["image_url"] == "https://example.test/leche.jpg"


def test_a_vague_category_offers_its_option_leaves_with_the_cheapest_price(client, session):
    for sku, quantity, price, image in (
        ("PECHUGA", "1", "5.00", "https://example.test/pechuga.jpg"),
        ("MUSLO", "0.5", "1.75", "https://example.test/muslo.jpg"),
        ("ALITAS", "1.5", "4.80", "https://example.test/alitas.jpg"),
        ("ENTERO", "2", "6.00", "https://example.test/entero.jpg"),
    ):
        key = {
            "PECHUGA": "pollo_pechuga",
            "MUSLO": "pollo_muslo_contramuslo",
            "ALITAS": "pollo_alitas",
            "ENTERO": "pollo_entero",
        }[sku]
        add_option_product(
            session,
            key,
            sku=sku,
            base_quantity=quantity,
            base_unit="kg",
            price=price,
            image_url=image,
        )
    session.commit()

    with_provider(client, FakeProvider())
    body = client.post("/api/interpret", json={"text": "pollo"}).json()

    (item,) = body["items"]
    assert item["category_key"] == "pollo"
    assert item["resolved"] is False
    assert [
        (option["category_key"], option["name"], option["from_unit_price"], option["base_unit"])
        for option in item["options"]
    ] == [
        ("pollo_pechuga", "Pechuga de pollo", "5", "kg"),
        ("pollo_muslo_contramuslo", "Muslos y contramuslos de pollo", "3.5", "kg"),
        ("pollo_alitas", "Alitas de pollo", "3.2", "kg"),
        ("pollo_entero", "Pollo entero y troceado", "3", "kg"),
    ]
    assert item["options"][0]["image_url"] == "https://example.test/pechuga.jpg"


def test_a_vague_node_without_an_option_list_offers_its_priced_children(client, session):
    add_option_product(
        session,
        "gamba_langostino",
        sku="GAMBA1",
        base_quantity="1",
        base_unit="kg",
        price="6.00",
        image_url="https://example.test/gamba1.jpg",
    )
    add_option_product(
        session,
        "gamba_langostino",
        sku="GAMBA2",
        base_quantity="1",
        base_unit="kg",
        price="7.00",
        image_url="https://example.test/gamba2.jpg",
    )
    add_option_product(
        session,
        "surimi",
        sku="SURIMI",
        base_quantity="1",
        base_unit="kg",
        price="2.00",
        image_url="https://example.test/surimi.jpg",
    )
    session.commit()

    with_provider(client, FakeProvider())
    body = client.post("/api/interpret", json={"text": "marisco"}).json()

    (item,) = body["items"]
    assert item["category_key"] == "marisco"
    assert item["resolved"] is False
    # Two products first; the child with none is not offered.
    assert [option["category_key"] for option in item["options"]] == [
        "gamba_langostino",
        "surimi",
    ]
    assert [option["from_unit_price"] for option in item["options"]] == ["6", "2"]
