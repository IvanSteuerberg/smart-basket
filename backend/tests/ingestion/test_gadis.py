"""Unit tests for the Gadisline v3 REST adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.gadis import (
    CATEGORIES_API_URL,
    SEARCH_API_URL,
    STORE_API_URL,
    GadisAdapter,
    parse_gadis_categories,
    parse_gadis_products,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_gadis_categories_flattens_two_levels():
    payload = {
        "categories": [
            {
                "id": "cat-l1",
                "name": "Alimentación",
                "nested_categories": {
                    "categories": [
                        {"id": "cat-l2-a", "name": "Aceites y vinagres"},
                        {"id": "cat-l2-b", "name": "Arroz y pasta"},
                    ]
                },
            }
        ]
    }
    cats = parse_gadis_categories(payload)
    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("cat-l1", "Alimentación", None),
        ("cat-l2-a", "Aceites y vinagres", "cat-l1"),
        ("cat-l2-b", "Arroz y pasta", "cat-l1"),
    ]


def test_parse_gadis_products_extracts_spanish_text_decimal_and_image():
    payload = {
        "elements": [
            {
                "product_code": 7204271,
                "commercial_description": [
                    {"language": "GL", "value": "Aceite oliva galego"},
                    {"language": "ES", "value": "Aceite oliva 0,4º ABRIL botella 1 l"},
                ],
                "price": 3.65,
                "price_kilo_litre": 3.65,
                "price_kilo_litre_suffix": [{"language": "ES", "value": "el litro"}],
                "slug": "/aceite-oliva-0-4-abril-botella-1-l",
                "image": {
                    "image": "https://storage.gadisline.com/catalog/full",
                    "image_thumbnails": "https://storage.gadisline.com/catalog/thumb",
                },
            }
        ]
    }
    products = parse_gadis_products(payload, category_code="cat-l2-a")
    assert len(products) == 1
    p = products[0]
    assert p.sku == "7204271"
    assert p.name == "Aceite oliva 0,4º ABRIL botella 1 l"
    assert p.price == Decimal("3.65")
    assert p.price_per_unit == Decimal("3.6500")
    assert p.base_quantity == Decimal("1.0000")
    assert p.base_unit == "l"
    assert p.url == "https://www.gadisline.com/aceite-oliva-0-4-abril-botella-1-l"
    assert p.image_url == "https://storage.gadisline.com/catalog/thumb"


def test_gadis_adapter_crawls_postal_code_and_deduplicates_skus():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == STORE_API_URL:
            return httpx.Response(
                200,
                json={"elements": [{"postal_code": "24001", "store_id": "store-leon"}]},
            )
        if url == CATEGORIES_API_URL:
            assert request.headers.get("store-id") == "store-leon"
            return httpx.Response(
                200,
                json={
                    "categories": [
                        {
                            "id": "l1",
                            "name": "Despensa",
                            "nested_categories": {"categories": [{"id": "l2", "name": "Aceites"}]},
                        }
                    ]
                },
            )
        if url.startswith(SEARCH_API_URL):
            body = json.loads(request.content.decode())
            assert body["category_ids"] == ["l2"]
            return httpx.Response(
                200,
                json={
                    "page": {"number": 0, "total_pages": 1, "total_elements": 1},
                    "elements": [
                        {
                            "product_code": 1001,
                            "commercial_description": [{"language": "ES", "value": "Aceite 1 l"}],
                            "price": 4.2,
                            "price_kilo_litre": 4.2,
                            "slug": "/aceite-1-l",
                        }
                    ],
                },
            )
        return httpx.Response(404)

    adapter = GadisAdapter(client=_mock_client(handler), delay=0.0)
    result = collect(adapter, "24001")
    assert result.status == "succeeded"
    assert len(result.categories) == 2
    assert [p.sku for p in result.products] == ["1001"]
