"""List interpretation through the API, with fake LLM providers (no network)."""

import os

import pytest

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
    }
    assert item["line"] == 0
    assert item["quantity"] == "2"
    assert item["unit"] == "l"
    assert item["category_key"] == "leche"
    assert item["category_name"] == "Leche"
    assert item["resolved"] is True
    assert item["needs_llm"] is False


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
