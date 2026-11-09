"""Full and partial Mercadona crawls against `httpx.MockTransport` (never the real network)."""

from collections import Counter
from decimal import Decimal as D
from typing import Any

import httpx

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.http import Fetcher
from smart_basket.ingestion.mercadona import MercadonaAdapter


def make_adapter(load_fixture, *, failing: frozenset[str] = frozenset()) -> tuple[Any, Counter]:
    attempts: Counter[str] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        attempts[path] += 1
        if path.endswith("/categories/"):
            return httpx.Response(200, json=load_fixture("tree.json"))
        code = path.rstrip("/").rsplit("/", 1)[-1]
        if code in failing:
            return httpx.Response(500)
        return httpx.Response(200, json=load_fixture(f"category-{code}.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(client, delay=0.0, backoff=0.0)
    return MercadonaAdapter(fetcher=fetcher), attempts


def product_prices(result) -> dict[str, D]:
    return {product.sku: product.price for product in result.products}


def test_full_crawl_yields_categories_products_and_raw_responses(load_fixture):
    adapter, attempts = make_adapter(load_fixture)
    result = collect(adapter, "3683")

    assert result.status == "succeeded"
    assert result.complete is True
    assert result.errors == ()
    assert {category.code for category in result.categories} == {
        "12",
        "13",
        "112",
        "113",
        "130",
        "420",
        "421",
        "430",
        "440",
    }
    # The duplicate product keeps the price of the first section seen.
    assert product_prices(result) == {
        "4241": D("5.10"),
        "4242": D("9.00"),
        "4243": D("1.20"),
        "5000": D("0.80"),
        "6000": D("3.00"),
    }
    assert len(result.raw) == 4
    assert attempts == {
        "/api/categories/": 1,
        "/api/categories/112/": 1,
        "/api/categories/113/": 1,
        "/api/categories/130/": 1,
    }


def test_a_failing_subcategory_ends_the_run_partial(load_fixture):
    adapter, attempts = make_adapter(load_fixture, failing=frozenset({"113"}))
    result = collect(adapter, "3683")

    assert result.status == "partial"
    assert result.complete is False
    assert len(result.errors) == 1
    assert "/api/categories/113/" in result.errors[0].url
    assert product_prices(result) == {
        "4241": D("5.10"),
        "4242": D("9.00"),
        "4243": D("1.20"),
        "6000": D("3.00"),
    }
    assert attempts["/api/categories/113/"] == 4  # initial call plus three retries


def test_max_categories_limits_the_level_two_pages(load_fixture):
    adapter, attempts = make_adapter(load_fixture)
    result = collect(adapter, "3683", max_categories=1)

    assert result.status == "succeeded"
    assert result.complete is False
    assert product_prices(result) == {"4241": D("5.10"), "4242": D("9.00"), "4243": D("1.20")}
    assert "/api/categories/112/" in attempts
    assert "/api/categories/113/" not in attempts
    assert "/api/categories/130/" not in attempts


def test_network_error_on_a_subcategory_is_reported(load_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/113/"):
            raise httpx.ConnectError("refused", request=request)
        if request.url.path.endswith("/categories/"):
            return httpx.Response(200, json=load_fixture("tree.json"))
        code = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(200, json=load_fixture(f"category-{code}.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MercadonaAdapter(fetcher=Fetcher(client, delay=0.0, backoff=0.0))
    result = collect(adapter, "3683")

    assert result.status == "partial"
    assert [error.url for error in result.errors] == [
        "https://tienda.mercadona.es/api/categories/113/?lang=es&wh=3683"
    ]
    assert "5000" not in product_prices(result)
