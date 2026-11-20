"""Unit tests for the Froiz Hydra JSON-LD REST adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.froiz import (
    FroizAdapter,
    parse_froiz_categories,
    parse_froiz_product,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _product(sku: int, **fields: object) -> dict:
    base = {
        "id": sku,
        "enabled": True,
        "name": "Leche entera 1 l",
        "order_price": 1.2,
        "base_price": 1.2,
        "category_id": 5,
        "category_name": "Alimentación",
        "section_id": 8,
        "section_name": "Aceites y vinagres",
        "slug": f"leche-{sku}",
        "image": "",
    }
    return {**base, **fields}


def _coverage() -> dict:
    return {
        "result": "success",
        "data": {
            "coverage": True,
            "postalcode": "24001",
            "store_info": {"cod_ent": 1, "cod_subent": 198},
        },
    }


def test_parse_froiz_categories_flattens_categories_and_sections():
    payload = {
        "hydra:member": [
            {
                "id": 5,
                "name": "Alimentación",
                "sections": [
                    {"id": 8, "name": "Aceites y vinagres"},
                    {"id": 9, "name": "Arroz y pasta"},
                ],
            },
            {"id": 6, "name": "Bebidas"},
        ]
    }

    cats = parse_froiz_categories(payload)

    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("cat:5", "Alimentación", None),
        ("sec:8", "Aceites y vinagres", "cat:5"),
        ("sec:9", "Arroz y pasta", "cat:5"),
        ("cat:6", "Bebidas", None),
    ]


def test_parse_froiz_product_with_brand_size_and_offer():
    raw = {
        "id": 1001,
        "enabled": True,
        "name": "Aceite de oliva virgen extra 1 l",
        "brand_name": "Borges",
        "offer": {"price": 8.45, "quantity": 1},
        "order_price": 9.95,
        "base_price": 9.95,
        "section_id": 8,
        "category_id": 5,
        "slug": "aceite-oliva-virgen-extra-borges-1-l",
        "image": "/img/aceite.jpg",
    }

    product = parse_froiz_product(raw)

    assert product is not None
    assert product.sku == "1001"
    assert product.name == "Aceite de oliva virgen extra 1 l Borges"
    assert product.price == Decimal("8.45")
    assert product.base_quantity == Decimal("1.0000")
    assert product.base_unit == "l"
    assert product.pack_count == 1
    assert product.price_per_unit == Decimal("8.4500")
    assert product.category_code == "sec:8"
    assert product.url == (
        "https://supermercado.froiz.com/producto/aceite-oliva-virgen-extra-borges-1-l"
    )
    assert product.image_url == "https://supermercado.froiz.com/images/img/aceite.jpg"

    # An offer that only applies to a bundle (quantity 3) does not set the unit price.
    bundle = dict(raw, offer={"price": 12.0, "quantity": 3}, base_price=None)
    product = parse_froiz_product(bundle)
    assert product is not None
    assert product.price == Decimal("9.95")


def test_parse_froiz_product_fractional_weight_and_unit_ratio_fallback():
    fractional = {
        "id": 2001,
        "name": "Queso tetilla",
        "order_price": 1.8,
        "fractional": True,
        "measurement_unit": "kilogramo",
        "per_unit_weight": 0.25,
        "measurement_unit_ratio": 1,
    }

    product = parse_froiz_product(fractional)

    assert product is not None
    assert product.base_quantity == Decimal("0.2500")
    assert product.base_unit == "kg"
    assert product.pack_count == 1
    assert product.price_per_unit == Decimal("7.2000")

    by_ratio = {
        "id": 2002,
        "name": "Leche entera sin size en el nombre",
        "order_price": 3.0,
        "measurement_unit": "litro",
        "measurement_unit_ratio": 1.5,
    }

    product = parse_froiz_product(by_ratio)

    assert product is not None
    assert product.base_quantity == Decimal("1.5000")
    assert product.base_unit == "l"
    assert product.price_per_unit == Decimal("2.0000")

    bare = {"id": 2003, "name": "Pan de molde", "order_price": 1.1}

    product = parse_froiz_product(bare)

    assert product is not None
    assert product.base_quantity is None
    assert product.base_unit is None
    assert product.price_per_unit is None
    assert product.category_code == "cat:0"


def test_parse_froiz_product_drops_disabled_or_unusable_entries():
    disabled = {"id": 1, "name": "Leche entera 1 l", "order_price": 1.0, "enabled": False}
    priceless = {"id": 2, "name": "Leche entera 1 l", "order_price": 0, "base_price": 0}
    nameless = {"id": 3, "order_price": 1.0}

    assert parse_froiz_product(disabled) is None
    assert parse_froiz_product(priceless) is None
    assert parse_froiz_product(nameless) is None


def test_froiz_adapter_checks_coverage_and_paginates_hydra_products():
    seen: dict[str, list] = {"paths": [], "pages": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen["paths"].append(path)
        if path == "/api/storescoverage/coverage/24001":
            return httpx.Response(200, json=_coverage())
        if path == "/api/categories":
            return httpx.Response(
                200,
                json={
                    "hydra:member": [
                        {
                            "id": 5,
                            "name": "Alimentación",
                            "sections": [{"id": 8, "name": "Aceites y vinagres"}],
                        }
                    ]
                },
            )
        if path == "/api/products":
            page = int(request.url.params["page"])
            seen["pages"].append(page)
            assert request.url.params["size"] == "100"
            if page == 1:
                rows = [_product(1001), _product(1002)]
                meta = {
                    "pageNumber": 1,
                    "productTotal": 3,
                    "productsPerPage": 100,
                    "productsInPage": 2,
                    "totalPages": 2,
                }
                return httpx.Response(200, json={"hydra:member": [rows, [], [], [], [], meta]})
            if page == 2:
                # A flat product list, as the family endpoints answer it, with a seen sku again.
                rows = [
                    _product(
                        1003,
                        section_id=9,
                        section_name="Bebidas",
                        category_id=6,
                        category_name="Bebidas",
                    ),
                    _product(1001),
                ]
                return httpx.Response(200, json={"hydra:member": rows})
            return httpx.Response(200, json={"hydra:member": []})
        return httpx.Response(404)

    adapter = FroizAdapter(client=_mock_client(handler), delay=0.0)
    result = collect(adapter, "24001")

    assert seen["paths"][0] == "/api/storescoverage/coverage/24001"
    assert seen["paths"][1] == "/api/categories"
    assert seen["pages"] == [1, 2, 3]
    assert result.status == "succeeded"
    assert result.complete is True
    assert [p.sku for p in result.products] == ["1001", "1002", "1003"]
    codes = {c.code: c for c in result.categories}
    assert codes["cat:5"].name == "Alimentación"
    assert codes["sec:8"].parent_code == "cat:5"
    assert codes["cat:6"].name == "Bebidas"
    assert codes["sec:9"].parent_code == "cat:6"
    assert len(result.raw) == 5  # coverage, categories and three product pages
    assert result.errors == ()


def test_froiz_adapter_reports_error_when_postal_code_not_covered():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/storescoverage/coverage/24001"
        return httpx.Response(200, json={"result": "error", "data": {"coverage": False}})

    adapter = FroizAdapter(client=_mock_client(handler), delay=0.0)
    result = collect(adapter, "24001")

    assert result.status == "partial"
    assert result.categories == ()
    assert result.products == ()
    assert len(result.raw) == 1
    assert result.errors[0].error == "postal code 24001 not covered"


def test_froiz_adapter_respects_max_categories():
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/storescoverage/coverage/24001":
            return httpx.Response(200, json=_coverage())
        if path == "/api/categories":
            return httpx.Response(
                200, json={"hydra:member": [{"id": 5, "name": "Alimentación", "sections": []}]}
            )
        if path == "/api/products":
            page = int(request.url.params["page"])
            seen.append(page)
            rows = [_product(1001), _product(1002)]
            meta = {
                "pageNumber": page,
                "productTotal": 7106,
                "productsPerPage": 100,
                "productsInPage": 2,
                "totalPages": 72,
            }
            return httpx.Response(200, json={"hydra:member": [rows, [], [], [], [], meta]})
        return httpx.Response(404)

    adapter = FroizAdapter(client=_mock_client(handler), delay=0.0)
    result = collect(adapter, "24001", max_categories=1)

    assert seen == [1]
    assert result.status == "succeeded"
    assert result.complete is False
    assert [p.sku for p in result.products] == ["1001", "1002"]
    assert result.errors == ()
