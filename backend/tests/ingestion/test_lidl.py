"""Unit tests for the Lidl folletos adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

from decimal import Decimal as D

import httpx

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.http import Fetcher
from smart_basket.ingestion.lidl import (
    FOLLETOS_INDEX_URL,
    LidlAdapter,
    parse_lidl_flyer,
    parse_lidl_flyer_slugs,
    parse_lidl_page_keywords,
)

INDEX_HTML = """
<main>
  <a href="https://www.lidl.es/l/folletos/folleto-alimentacion">Alimentación</a>
  <a href="https://www.lidl.es/l/folletos/folleto-alimentacion">Alimentación ( repetida )</a>
  <a href="https://www.lidl.es/l/folletos/folleto-perfumeria">Otro</a>
  <a href="https://www.lidl.es/l/folletos/folleto-perfumeria">Otro ( repetido )</a>
  <a href="https://www.lidl.es/l/otra-cosa">No es un folleto</a>
</main>
"""

# OCR line shaped after Lidl Spain's `folleto-alimentacion` keyWords: prices in cents
# (`1175 945` = 11.75 € down to 9.45 €), banners between items, a single-price item with `€`.
PAGE_KEYWORDS = (
    "Lunes ¡Somos Súper Baja Precios! Bajadas Precio Productos Lidl Plus -19% -20% "
    "Alesto Nuez Natural 1175 945 Baresa Tomate Frito Cebolla 348 259 Aguacate "
    "Categoría Origen Brasil Colombia Kenia México Granel Redondo Cerdo Relleno Jamón "
    "999 799 Hamburguesa Vacuno 299 € 2ª 150 349 175 Bellarom Café Molido 956 756 -50% "
    "Hamburguesas Langostino Cocido 938 788 -30%"
)


def test_parse_lidl_flyer_slugs_prioritizes_food_flyers_and_deduplicates():
    slugs = parse_lidl_flyer_slugs(INDEX_HTML)
    assert slugs == ["folleto-alimentacion"]


def test_parse_lidl_flyer_slugs_falls_back_to_every_slug_without_food_flyers():
    html = '<a href="https://www.lidl.es/l/folletos/folleto-perfumeria">Perfumería</a>'
    assert parse_lidl_flyer_slugs(html) == ["folleto-perfumeria"]
    assert parse_lidl_flyer_slugs("<p>sin enlaces</p>") == []


def test_parse_lidl_flyer_reads_structured_products_and_dates():
    payload = {
        "flyer": {
            "id": 1001,
            "name": "Folleto Alimentación",
            "offerStartDate": "2026-11-16T00:00:00",
            "offerEndDate": "2026-11-22T23:59:59",
            "products": {
                "70001": {
                    "productId": 70001,
                    "title": "Milbona Café Molido 500 g",
                    "brand": "Milbona",
                    "price": 7.56,
                    "strokePrice": 9.56,
                    "url": "/c/cafe-molido/p70001",
                    "image": "https://img.lidl.example/70001.jpg",
                }
            },
        }
    }
    categories, products = parse_lidl_flyer(payload)

    assert [(category.code, category.name, category.parent_code) for category in categories] == [
        ("folletos", "Folletos Lidl", None),
        ("folletos/folleto-alimentacion", "Folleto Alimentación", "folletos"),
    ]
    assert len(products) == 1
    product = products[0]
    assert product.sku == "lidl-70001"
    assert product.name == "Milbona Café Molido 500 g"
    assert product.price == D("7.56")
    assert product.regular_price == D("9.56")
    assert product.is_temporary is False
    assert product.valid_from == "2026-11-16"
    assert product.valid_until == "2026-11-22"
    assert product.base_quantity == D("0.5000")
    assert product.base_unit == "kg"
    assert product.price_per_unit == D("15.1200")
    assert product.url == "https://www.lidl.es/c/cafe-molido/p70001"
    assert product.image_url == "https://img.lidl.example/70001.jpg"
    assert product.category_code == "folletos/folleto-alimentacion"


def test_parse_lidl_page_keywords_extracts_cents_prices_and_skips_noise():
    page = {"image": "https://img.lidl.example/p1.jpg", "keyWords": PAGE_KEYWORDS}
    products = parse_lidl_page_keywords(
        page,
        category_code="folletos/folleto-alimentacion",
        flyer_url="https://www.lidl.es/l/folletos/folleto-alimentacion",
        valid_from="2026-11-16",
        valid_until="2026-11-22",
    )

    by_name = {product.name: product for product in products}
    assert set(by_name) == {
        "Alesto Nuez Natural",
        "Baresa Tomate Frito Cebolla",
        "Redondo Cerdo Relleno Jamón",
        "Hamburguesa Vacuno",
        "Bellarom Café Molido",
        "Hamburguesas Langostino Cocido",
    }
    nut = by_name["Alesto Nuez Natural"]
    assert (nut.regular_price, nut.price) == (D("11.75"), D("9.45"))
    tomato = by_name["Baresa Tomate Frito Cebolla"]
    assert (tomato.regular_price, tomato.price) == (D("3.48"), D("2.59"))
    assert tomato.sku == "lidl-baresa-tomate-frito-cebolla"
    pork = by_name["Redondo Cerdo Relleno Jamón"]
    assert (pork.regular_price, pork.price) == (D("9.99"), D("7.99"))
    # A single cents group right after the name is an offer without a regular price, and the
    # orphan numbers of the previous item never leak into a name.
    burger = by_name["Hamburguesa Vacuno"]
    assert burger.regular_price is None
    assert burger.price == D("2.99")
    coffee = by_name["Bellarom Café Molido"]
    assert (coffee.regular_price, coffee.price) == (D("9.56"), D("7.56"))
    shrimp = by_name["Hamburguesas Langostino Cocido"]
    assert (shrimp.regular_price, shrimp.price) == (D("9.38"), D("7.88"))
    for product in products:
        assert product.category_code == "folletos/folleto-alimentacion"
        assert product.image_url == "https://img.lidl.example/p1.jpg"
        assert product.url == "https://www.lidl.es/l/folletos/folleto-alimentacion"
        assert product.valid_from == "2026-11-16"
        assert product.valid_until == "2026-11-22"
        assert product.is_temporary is False


def test_parse_lidl_page_keywords_flags_limited_editions_as_temporary():
    page = {
        "image": "https://img.lidl.example/p2.jpg",
        "keyWords": "Artículos Limitados Deluxe Tarta Queso 999 799 Pikok Pollo 199 €",
    }
    products = parse_lidl_page_keywords(
        page,
        category_code="folletos/folleto-alimentacion",
        flyer_url=None,
        valid_from=None,
        valid_until=None,
    )

    assert [product.is_temporary for product in products] == [True, True]
    assert [product.name for product in products] == ["Deluxe Tarta Queso", "Pikok Pollo"]
    deluxe = products[0]
    assert (deluxe.regular_price, deluxe.price) == (D("9.99"), D("7.99"))
    chicken = products[1]
    assert chicken.regular_price is None
    assert chicken.price == D("1.99")


def test_parse_lidl_flyer_merges_both_sources_deduplicating_by_sku():
    payload = {
        "flyer": {
            "name": "Folleto Alimentación",
            "products": [
                {"productId": "70001", "title": "Milbona Café Molido 500 g", "price": 7.56},
                {"productId": "70001", "title": "Milbona Café Molido 500 g", "price": 7.56},
            ],
            "pages": [
                {"image": "https://img.lidl.example/p1.jpg", "keyWords": PAGE_KEYWORDS},
                {"image": "https://img.lidl.example/p1.jpg", "keyWords": ""},
            ],
        }
    }
    categories, products = parse_lidl_flyer(payload, flyer_url="https://www.lidl.es/l/folletos/x")

    assert [category.code for category in categories] == [
        "folletos",
        "folletos/folleto-alimentacion",
    ]
    assert len(products) == 7
    assert products[0].sku == "lidl-70001"
    assert {product.name for product in products[1:]} == {
        "Alesto Nuez Natural",
        "Baresa Tomate Frito Cebolla",
        "Redondo Cerdo Relleno Jamón",
        "Hamburguesa Vacuno",
        "Bellarom Café Molido",
        "Hamburguesas Langostino Cocido",
    }


def test_lidl_adapter_crawls_the_flyers_of_one_chain_wide_zone():
    flyer_payload = {
        "flyer": {
            "name": "Folleto Alimentación",
            "offerStartDate": "2026-11-16",
            "offerEndDate": "2026-11-22",
            "products": [],
            "pages": [{"image": "https://img.lidl.example/p1.jpg", "keyWords": PAGE_KEYWORDS}],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == FOLLETOS_INDEX_URL:
            return httpx.Response(200, text=INDEX_HTML)
        if (
            url
            == "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=folleto-alimentacion&region_id=0&region_code=0"
        ):
            return httpx.Response(200, json=flyer_payload)
        if (
            url
            == "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=folleto-perfumeria&region_id=0&region_code=0"
        ):
            return httpx.Response(200, json={"flyer": {"name": "Perfumería", "products": []}})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LidlAdapter(fetcher=Fetcher(client, delay=0.0, backoff=0.0))
    result = collect(adapter, "es")

    assert result.status == "succeeded"
    assert result.complete is True
    assert result.errors == ()
    # The non-food flyer is never fetched because a food flyer was available.
    requested = {raw.url for raw in result.raw}
    unfetched = "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=folleto-perfumeria&region_id=0&region_code=0"
    assert unfetched not in requested
    assert {category.code for category in result.categories} == {
        "folletos",
        "folletos/folleto-alimentacion",
    }
    assert len(result.products) == 6
    assert result.products[0].sku == "lidl-alesto-nuez-natural"


def test_lidl_adapter_reports_a_failing_flyer_without_stopping_the_run():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == FOLLETOS_INDEX_URL:
            return httpx.Response(200, text=INDEX_HTML)
        if "flyer_identifier=folleto-alimentacion" in url:
            return httpx.Response(500)
        return httpx.Response(200, json={"flyer": {"name": "Otros", "products": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LidlAdapter(fetcher=Fetcher(client, delay=0.0, backoff=0.0, retries=0))
    result = collect(adapter, "es")

    assert result.status == "partial"
    assert result.complete is False
    assert [error.url for error in result.errors] == [
        "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=folleto-alimentacion&region_id=0&region_code=0"
    ]
    assert result.products == ()
