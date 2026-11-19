"""Dia crawls against a fake transport, never the real site or a real browser."""

import json
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

from smart_basket.config import Settings
from smart_basket.ingestion import __main__ as cli
from smart_basket.ingestion.base import CrawlError, RawResponse, collect
from smart_basket.ingestion.dia import DiaAdapter, PlaywrightDiaTransport


class FakeDiaTransport:
    """Serves synthetic pages keyed by (`path`, `navigation`, `page`) or (`navigation`, `page`)."""

    def __init__(self, responses: dict[tuple[Any, ...], tuple[int, Any]]) -> None:
        self.responses = responses
        self.postal_codes: list[str] = []
        self.calls: list[str] = []
        self.closed = False

    def set_postal_code(self, postal_code: str) -> None:
        self.postal_codes.append(postal_code)

    def fetch_json(self, path_and_query: str) -> tuple[int, bytes]:
        self.calls.append(path_and_query)
        parsed = urlparse(path_and_query)
        query = parse_qs(parsed.query)
        navigation = query.get("navigation", [""])[0]
        page = int(query.get("page", ["1"])[0])
        status, payload = self.responses.get(
            (parsed.path, navigation, page),
            self.responses.get(
                (navigation, page), (200, {"page_product_analytics": {"products": []}})
            ),
        )
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return status, body

    def close(self) -> None:
        self.closed = True


def menu_payload() -> dict[str, Any]:
    return {
        "menu_analytics": {
            "menu": [
                {
                    "code": "L1_bebidas",
                    "name": "Bebidas",
                    "children": [
                        {"code": "L2_agua", "name": "Agua"},
                        {"code": "L2_refrescos", "name": "Refrescos"},
                        {"code": "L2_todo_bebidas", "name": "Todo en bebidas"},
                    ],
                },
                {
                    "code": "L1_limpieza",
                    "name": "Limpieza",
                    "children": [{"code": "L2_hogar", "name": "Hogar"}],
                },
            ]
        }
    }


def product(sku: str, name: str, price: str, *, stock: bool = True) -> dict[str, Any]:
    return {
        "object_id": sku,
        "display_name": name,
        "prices_price": price,
        "stock_availability": stock,
        "url": f"/supermercado/{sku}",
    }


def real_menu_payload() -> dict[str, Any]:
    """The dict-keyed `menu_analytics` the live `plp-insight` endpoint returns."""
    return {
        "menu_analytics": {
            "L101": {
                "parameter": "L1_quesos",
                "path": "/quesos/c/L101",
                "children": {
                    "L101": {"parameter": "L2_todo quesos", "path": "/quesos/c/L101"},
                    "L2007": {"parameter": "L2_curado", "path": "/quesos/curado/c/L2007"},
                },
            }
        }
    }


def real_product(sku: str, name: str, price: str, *, stock: bool = True) -> dict[str, Any]:
    """One entry of the dict-keyed `page_product_analytics` of the live endpoint."""
    return {
        "item_id": sku,
        "item_name": name,
        "item_brand": "dia ramblers",
        "price": price,
        "stock_availability": stock,
    }


def pages(
    overrides: dict[tuple[str, int], tuple[int, Any]] | None = None,
) -> dict[tuple[str, int], tuple[int, Any]]:
    responses: dict[tuple[str, int], tuple[int, Any]] = {
        ("L2007", 1): (200, menu_payload()),
        ("L2_agua", 1): (
            200,
            {
                "page_product_analytics": {
                    "products": [
                        product("1", "Agua 1,5 l", "0,65"),
                        product("2", "Agua 33 cl", "0,25"),
                    ]
                }
            },
        ),
        ("L2_agua", 2): (200, {"page_product_analytics": {"products": []}}),
        ("L2_refrescos", 1): (
            200,
            {"page_product_analytics": {"products": [product("3", "Refresco 6 x 33 cl", "1,80")]}},
        ),
        ("L2_hogar", 1): (
            200,
            {"page_product_analytics": {"products": [product("4", "Detergente 1 l", "2,50")]}},
        ),
    }
    if overrides:
        responses.update(overrides)
    return responses


def crawl(
    transport: FakeDiaTransport,
    *,
    max_categories: int | None = None,
    max_pages: int = 50,
):
    adapter = DiaAdapter(transport=transport, delay_seconds=0.0, max_pages=max_pages)
    return collect(adapter, "24001", max_categories=max_categories)


def test_crawl_binds_the_postal_code_and_walks_the_whole_tree():
    transport = FakeDiaTransport(pages())

    result = crawl(transport)

    assert transport.postal_codes == ["24001"]
    assert result.status == "succeeded"
    assert result.complete is True
    assert result.errors == ()
    assert {category.code for category in result.categories} == {
        "bebidas",
        "agua",
        "refrescos",
        "limpieza",
        "hogar",
    }
    prices = {entry.sku: str(entry.price) for entry in result.products}
    assert prices == {"1": "0.65", "2": "0.25", "3": "1.80", "4": "2.50"}
    assert next(raw.url for raw in result.raw) == (
        "/api/v1/plp-insight/initial_analytics/quesos/curado/c/L2007?navigation=L2007&page=1"
    )
    assert len(result.raw) == 7


def test_pagination_stops_on_an_empty_page():
    transport = FakeDiaTransport(pages())

    result = crawl(transport)

    assert any("navigation=L2_agua&page=1" in call for call in transport.calls)
    assert any("navigation=L2_agua&page=2" in call for call in transport.calls)
    assert not any("navigation=L2_agua&page=3" in call for call in transport.calls)
    assert {entry.sku for entry in result.products} == {"1", "2", "3", "4"}


def test_pagination_continues_past_a_page_with_only_out_of_stock_products():
    transport = FakeDiaTransport(
        pages(
            {
                ("L2_agua", 1): (
                    200,
                    {
                        "page_product_analytics": {
                            "products": [
                                product("1", "Agua 1,5 l", "0,65", stock=False),
                                product("2", "Agua 33 cl", "0,25", stock=False),
                            ]
                        }
                    },
                ),
                ("L2_agua", 2): (
                    200,
                    {"page_product_analytics": {"products": [product("5", "Agua 2 l", "0,80")]}},
                ),
            }
        )
    )

    result = crawl(transport)

    assert any("navigation=L2_agua&page=2" in call for call in transport.calls)
    assert "5" in {entry.sku for entry in result.products}
    assert {"1", "2"}.isdisjoint({entry.sku for entry in result.products})


CURO_PATH = "/api/v1/plp-insight/initial_analytics/quesos/curado/c/L2007"


def test_real_dict_keyed_payload_walks_path_based_plp_urls():
    first_page = {
        **real_menu_payload(),
        "page_product_analytics": {
            "192": real_product("192", "cerveza clasica dia ramblers 33 cl", "0.32"),
        },
    }
    transport = FakeDiaTransport(
        {
            (CURO_PATH, "L2007", 1): (200, first_page),
            (CURO_PATH, "L2007", 2): (200, {"page_product_analytics": {}}),
        }
    )

    result = crawl(transport)

    assert result.status == "succeeded"
    found = {(category.code, category.name, category.parent_code) for category in result.categories}
    assert found == {
        ("L101", "quesos", None),
        ("L2007", "curado", "L101"),
    }
    assert {entry.sku for entry in result.products} == {"192"}
    assert str(result.products[0].price) == "0.32"
    assert transport.calls == [
        f"{CURO_PATH}?navigation=L2007&page=1",
        f"{CURO_PATH}?navigation=L2007&page=1",
        f"{CURO_PATH}?navigation=L2007&page=2",
    ]
    assert [raw.url for raw in result.raw] == transport.calls


def test_pagination_stops_when_a_page_repeats_every_sku():
    transport = FakeDiaTransport(
        pages(
            {
                ("L2_agua", 2): (
                    200,
                    {"page_product_analytics": {"products": [product("1", "Agua 1,5 l", "0,65")]}},
                )
            }
        )
    )

    result = crawl(transport)

    assert [call for call in transport.calls if "navigation=L2_agua" in call] == [
        "/api/v1/plp-insight/initial_analytics?navigation=L2_agua&page=1",
        "/api/v1/plp-insight/initial_analytics?navigation=L2_agua&page=2",
    ]
    assert {entry.sku for entry in result.products} == {"1", "2", "3", "4"}


def test_max_pages_caps_a_listing_that_never_ends():
    transport = FakeDiaTransport(
        {
            ("L2007", 1): (200, menu_payload()),
            **{
                ("L2_agua", page): (
                    200,
                    {
                        "page_product_analytics": {
                            "products": [product(str(page), f"Agua {page} l", "1,00")]
                        }
                    },
                )
                for page in range(1, 10)
            },
        }
    )

    result = crawl(transport, max_pages=3)

    agua_calls = [call for call in transport.calls if "navigation=L2_agua" in call]
    assert len(agua_calls) == 3
    assert {entry.sku for entry in result.products} >= {"1", "2", "3"}
    assert "9" not in {entry.sku for entry in result.products}


def test_max_categories_limits_the_level_two_pages():
    transport = FakeDiaTransport(pages())

    result = crawl(transport, max_categories=1)

    assert result.status == "succeeded"
    assert result.complete is False
    assert not any("navigation=L2_refrescos" in call for call in transport.calls)
    assert not any("navigation=L2_hogar" in call for call in transport.calls)
    assert {entry.sku for entry in result.products} == {"1", "2"}
    # The tree is still reported: only the paging is limited.
    assert {category.code for category in result.categories} == {
        "bebidas",
        "agua",
        "refrescos",
        "limpieza",
        "hogar",
    }


def test_a_non_200_menu_ends_the_run_with_a_crawl_error():
    transport = FakeDiaTransport({("L2007", 1): (500, b"")})

    result = crawl(transport)

    assert result.status == "partial"
    assert result.complete is False
    assert result.categories == ()
    assert result.products == ()
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], CrawlError)
    assert "HTTP 500" in result.errors[0].error


def test_a_non_200_listing_page_is_reported_and_the_next_category_continues():
    transport = FakeDiaTransport(pages({("L2_agua", 1): (500, b"")}))

    result = crawl(transport)

    assert result.status == "partial"
    assert result.complete is False
    assert "navigation=L2_agua&page=1" in result.errors[0].url
    assert {entry.sku for entry in result.products} == {"3", "4"}


def test_invalid_json_is_reported_as_a_crawl_error():
    transport = FakeDiaTransport({("L2007", 1): (200, b"not json")})

    result = crawl(transport)

    assert result.status == "partial"
    assert result.errors[0].error == "invalid JSON"


def test_close_closes_the_injected_transport():
    transport = FakeDiaTransport(pages())
    adapter = DiaAdapter(transport=transport, delay_seconds=0.0)

    adapter.close()

    assert transport.closed is True


def test_dia_is_registered_in_the_cli_with_its_postal_code_zones():
    entry = cli.ADAPTERS["dia"]
    settings = Settings(_env_file=None, dia_zones="24001, 03001")

    assert entry.adapter is DiaAdapter
    assert entry.zones(settings) == ["24001", "03001"]
    assert DiaAdapter.zone_kind == "postal_code"


def test_importing_the_adapter_does_not_need_playwright():
    assert "playwright.sync_api" not in sys.modules
    adapter = DiaAdapter(delay=0.0)
    try:
        assert isinstance(adapter._transport, PlaywrightDiaTransport)
    finally:
        adapter.close()


def test_raw_response_archives_carry_the_body_bytes():
    transport = FakeDiaTransport(pages())

    result = crawl(transport)

    menu = result.raw[0]
    assert isinstance(menu, RawResponse)
    assert menu.status_code == 200
    assert b"menu_analytics" in menu.body
