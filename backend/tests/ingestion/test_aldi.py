"""Unit tests for the Aldi Algolia and weekly-offers adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx

from smart_basket.ingestion.aldi import (
    OFFERS_CURRENT_URL,
    AldiAdapter,
    parse_aldi_categories,
    parse_aldi_product,
)
from smart_basket.ingestion.base import collect

CATEGORY_PAYLOAD = {
    "facets": {
        "hierarchicalCategories.lvl0": {"Fruta y verdura": 171, "Panadería": 20},
        "hierarchicalCategories.lvl1": {
            "Fruta y verdura > Verduras y hortalizas": 91,
            "Fruta y verdura > Fruta fresca": 80,
            "Panadería > Bollos y magdalenas": 20,
        },
        "categoryIDs": {"23": 171},
    }
}

CRAWL_PAYLOAD = {
    "facets": {
        "hierarchicalCategories.lvl0": {"Congelados": 3},
        "hierarchicalCategories.lvl1": {
            "Congelados > Pescado y marisco congelado": 3,
            "Congelados > Helados": 0,
        },
        "categoryIDs": {"8123": 3},
    }
}

FISH = {
    "objectID": "A1",
    "name": "Gambas cocidas congeladas",
    "salesUnit": "600 g",
    "currentPrice": {"priceValue": 5.39},
}
HAKE = {
    "objectID": "B1",
    "name": "Merluza congelada",
    "currentPrice": {"priceValue": 3.10},
}
CATEGORY_ONLY = {
    "objectID": "C1",
    "name": "Sorpresa semanal",
    "currentPrice": {"priceValue": 1.00},
}
OFFER = {
    "name": "Oferta especial de la semana",
    "salesUnit": "1 l",
    "currentPrice": {"priceValue": 2.00},
}


def test_parse_aldi_categories_builds_l1_and_l2_tree():
    cats = parse_aldi_categories(CATEGORY_PAYLOAD)
    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("lvl0:fruta-y-verdura", "Fruta y verdura", None),
        ("lvl0:panaderia", "Panadería", None),
        (
            "lvl1:fruta-y-verdura/verduras-y-hortalizas",
            "Verduras y hortalizas",
            "lvl0:fruta-y-verdura",
        ),
        ("lvl1:fruta-y-verdura/fruta-fresca", "Fruta fresca", "lvl0:fruta-y-verdura"),
        ("lvl1:panaderia/bollos-y-magdalenas", "Bollos y magdalenas", "lvl0:panaderia"),
        ("lvl0:otros", "Otros", None),
        ("lvl1:otros/general", "General", "lvl0:otros"),
    ]


def test_parse_aldi_product_extracts_brand_price_size_and_image():
    raw = {
        "objectID": "000000000000400123",
        "name": "Gambas cocidas congeladas",
        "brandName": "GOLDEN SEAFOOD®",
        "salesUnit": "600 g unidad",
        "productSlug": "gambas-cocidas-congeladas-600g",
        "currentPrice": {
            "priceValue": 5.39,
            "basePrice": [{"basePriceValue": 8.98, "basePriceScale": "kg"}],
        },
        "hierarchicalCategories": {
            "lvl0": ["Congelados"],
            "lvl1": ["Marcas > Golden Seafood ", "Congelados > Pescado y marisco congelado"],
        },
        "assets": [
            {"type": "thumbnail", "url": "https://www.aldi.es/media/thumb.jpg"},
            {"type": "primary", "url": "https://www.aldi.es/media/full.jpg"},
        ],
    }
    product = parse_aldi_product(raw)
    assert product is not None
    assert product.sku == "000000000000400123"
    assert product.name == "Gambas cocidas congeladas GOLDEN SEAFOOD"
    assert product.price == Decimal("5.39")
    assert product.price_per_unit == Decimal("8.9800")
    assert product.base_quantity == Decimal("0.6000")
    assert product.base_unit == "kg"
    assert product.pack_count == 1
    assert product.category_code == "lvl1:congelados/pescado-y-marisco-congelado"
    assert product.url == "https://www.aldi.es/productos/gambas-cocidas-congeladas-600g.html"
    assert product.image_url == "https://www.aldi.es/media/full.jpg"


def test_parse_aldi_product_infers_quantity_from_base_price_and_handles_100g_scale():
    oranges = parse_aldi_product(
        {
            "objectID": "777",
            "name": "Naranjas de mesa",
            "currentPrice": {
                "priceValue": 1.20,
                "basePrice": [{"basePriceValue": 0.60, "basePriceScale": "100 g"}],
            },
        }
    )
    assert oranges is not None
    assert oranges.price_per_unit == Decimal("6.0000")
    assert oranges.base_quantity == Decimal("0.2000")
    assert oranges.base_unit == "kg"

    milk = parse_aldi_product(
        {
            "objectID": "778",
            "name": "Leche entera",
            "currentPrice": {
                "priceValue": 0.99,
                "basePrice": [{"basePriceValue": 0.10, "basePriceScale": "100 ml"}],
            },
        }
    )
    assert milk is not None
    assert milk.price_per_unit == Decimal("1.0000")
    assert milk.base_quantity == Decimal("0.9900")
    assert milk.base_unit == "l"
    assert milk.url is None
    assert milk.category_code == "lvl1:otros/general"


def test_parse_aldi_product_skips_unpriced_or_recalled_items():
    base = {"objectID": "1", "name": "Producto", "currentPrice": {"priceValue": 1.00}}
    assert parse_aldi_product({**base, "isRecall": True}) is None
    assert parse_aldi_product({**base, "isAvailable": False}) is None
    assert parse_aldi_product({**base, "currentPrice": None}) is None
    assert parse_aldi_product({**base, "currentPrice": {"priceValue": 0}}) is None
    assert parse_aldi_product({**base, "objectID": ""}) is None
    assert parse_aldi_product({**base, "name": "   "}) is None


def test_aldi_adapter_crawls_categories_paginates_and_merges_offers():
    calls: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == OFFERS_CURRENT_URL
            return httpx.Response(200, json={"algoliaDataMap": {"OFFER-9": OFFER}})
        if not request.url.query:
            body = json.loads(request.content)
            assert body["hitsPerPage"] == 0
            assert body["facets"] == [
                "hierarchicalCategories.lvl0",
                "hierarchicalCategories.lvl1",
                "categoryIDs",
            ]
            return httpx.Response(200, json=CRAWL_PAYLOAD)
        body = json.loads(request.content)
        assert body["numericFilters"] == ["currentPrice.priceValue > 0"]
        assert body["hitsPerPage"] == 100
        facet = body["facetFilters"][0][0]
        if facet == "hierarchicalCategories.lvl1:Congelados > Pescado y marisco congelado":
            calls.append(("pescado", body["page"]))
            # The second page repeats the first SKU to check deduplication across pages.
            hits = [FISH] if body["page"] == 0 else [FISH, HAKE]
            return httpx.Response(200, json={"hits": hits, "nbPages": 2})
        if facet == "hierarchicalCategories.lvl1:Congelados > Helados":
            calls.append(("helados", body["page"]))
            return httpx.Response(200, json={"hits": [], "nbPages": 1})
        if facet == "categoryIDs:8123":
            calls.append(("category", body["page"]))
            return httpx.Response(200, json={"hits": [CATEGORY_ONLY, FISH], "nbPages": 1})
        return httpx.Response(200, json={"hits": [], "nbPages": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AldiAdapter(client=client, delay=0.0)
    result = collect(adapter, "all")

    assert calls == [("pescado", 0), ("pescado", 1), ("helados", 0), ("category", 0)]
    assert result.status == "succeeded"
    assert result.complete is True
    assert [p.sku for p in result.products] == ["A1", "B1", "C1", "OFFER-9"]
    assert len(result.categories) == 5
    assert {c.code for c in result.categories} >= {"lvl1:congelados/helados", "lvl0:otros"}
    # One facets response, four listing pages and the offers response are archived.
    assert len(result.raw) == 6
    offers = next(p for p in result.products if p.sku == "OFFER-9")
    assert offers.category_code == "lvl1:otros/general"
    assert offers.price == Decimal("2.00")
    assert offers.base_quantity == Decimal("1.0000")


def test_aldi_adapter_respects_max_categories_and_reports_errors():
    listings: list[str] = []

    def limited_handler(request: httpx.Request) -> httpx.Response:
        if not request.url.query:
            return httpx.Response(200, json=CRAWL_PAYLOAD)
        if request.method == "GET":
            raise AssertionError("offers must not be fetched in a limited run")
        body = json.loads(request.content)
        listings.append(body["facetFilters"][0][0])
        return httpx.Response(200, json={"hits": [FISH], "nbPages": 1})

    limited = AldiAdapter(
        client=httpx.Client(transport=httpx.MockTransport(limited_handler)), delay=0.0
    )
    result = collect(limited, "all", max_categories=1)
    assert listings == ["hierarchicalCategories.lvl1:Congelados > Pescado y marisco congelado"]
    assert result.status == "succeeded"
    assert result.complete is False
    assert [p.sku for p in result.products] == ["A1"]

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if not request.url.query:
            return httpx.Response(200, json=CRAWL_PAYLOAD)
        return httpx.Response(500, text="boom")

    failing = AldiAdapter(
        client=httpx.Client(transport=httpx.MockTransport(failing_handler)), delay=0.0
    )
    failed = collect(failing, "all", max_categories=1)
    assert failed.status == "partial"
    assert failed.products == ()
    assert len(failed.errors) == 1
    assert "page=0" in failed.errors[0].url
    assert len(failed.categories) == 5
