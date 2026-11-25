"""Contract tests for the Carrefour RadarSuper plain-HTTP adapter."""

from __future__ import annotations

from decimal import Decimal

import httpx

from smart_basket.ingestion.base import CategoryObservation, ProductObservation, RawResponse
from smart_basket.ingestion.carrefour import (
    CarrefourAdapter,
    has_next_page,
    parse_carrefour_category_links,
    parse_carrefour_product,
    parse_carrefour_rsc_items,
    parse_category_title,
)

INDEX_HTML = """
<html><body>
  <a href="/carrefour/c/aceite-especias-salsas-12">Aceite, especias y salsas</a>
  <a href="/carrefour/c/fruta-27">Fruta</a>
  <a href="/carrefour/c/aceite-vinagre-sal-112">Aceite, vinagre y sal</a>
  <a href="/carrefour/c/aceite-vinagre-sal-112">Duplicate</a>
</body></html>
"""

CAT_PAGE_1_HTML = (
    "<html><body><h1>Aceite, vinagre y sal en Carrefour</h1>"
    r'<script>self.__next_f.push([1,"{\"item\":{'
    r"\"key\":\"/carrefour/p/aceite-de-aguacate-la-masia-250-ml-carrefour\","
    r"\"name\":\"Aceite de Aguacate La Masía 250 ml.\","
    r"\"brand\":\"La Masia\",\"price\":6.89,\"unit\":\"ml\",\"size\":250,"
    r"\"chain\":\"Carrefour\",\"image\":\"/img/p/aceite-aguacate.jpg\","
    r'\"url\":\"/carrefour/p/aceite-de-aguacate-la-masia-250-ml-carrefour\"}}"])</script>'
    '<a href="/carrefour/c/aceite-vinagre-sal-112/pagina/2">Siguiente</a></body></html>'
)

CAT_PAGE_2_HTML = (
    "<html><body><h1>Aceite, vinagre y sal en Carrefour</h1>"
    r'<script>self.__next_f.push([1,"{\"item\":{'
    r"\"key\":\"/carrefour/p/aceite-girasol-5-l-carrefour\","
    r"\"name\":\"Aceite de girasol Capicua 5 l.\","
    r"\"brand\":\"Capicua\",\"price\":14.25,\"unit\":\"L\",\"size\":5,"
    r"\"chain\":\"Carrefour\",\"image\":\"/img/p/aceite-girasol.jpg\","
    r'\"url\":\"/carrefour/p/aceite-girasol-5-l-carrefour\"}}"])</script>'
    "</body></html>"
)


def test_parse_carrefour_category_links_filters_l1_and_deduplicates():
    cats = parse_carrefour_category_links(INDEX_HTML)
    assert cats == [
        ("fruta-27", "/carrefour/c/fruta-27"),
        ("aceite-vinagre-sal-112", "/carrefour/c/aceite-vinagre-sal-112"),
    ]


def test_parse_category_title_strips_chain_suffix():
    assert (
        parse_category_title(CAT_PAGE_1_HTML, "aceite-vinagre-sal-112") == "Aceite, vinagre y sal"
    )


def test_parse_rsc_items_and_product_unit_prices():
    items = parse_carrefour_rsc_items(CAT_PAGE_1_HTML)
    assert len(items) == 1
    obs = parse_carrefour_product(items[0], category_code="aceite-vinagre-sal-112")
    assert obs is not None
    assert obs.sku == "aceite-de-aguacate-la-masia-250-ml-carrefour"
    assert obs.name == "Aceite de Aguacate La Masía 250 ml."
    assert obs.price == Decimal("6.89")
    assert obs.base_unit == "l"
    assert obs.base_quantity == Decimal("0.2500")
    assert obs.price_per_unit == Decimal("27.5600")
    assert obs.image_url == "https://radarsuper.com/img/p/aceite-aguacate.jpg"
    fallback = parse_carrefour_product(
        {
            "key": "/carrefour/p/manzana-1-kg-carrefour",
            "name": "Manzana roja 1 kg",
            "price": 2.49,
            "url": "/carrefour/p/manzana-1-kg-carrefour",
        },
        category_code="fruta-27",
    )
    assert fallback is not None
    assert fallback.base_unit == "kg"
    assert fallback.base_quantity == Decimal("1")
    no_size = parse_carrefour_product(
        {
            "key": "/carrefour/p/pan-fricopan-carrefour",
            "name": "Pan campeonato Fricopan Spanien",
            "price": 1.25,
            "url": "/carrefour/p/pan-fricopan-carrefour",
        },
        category_code="pan-1",
    )
    assert no_size is not None
    assert no_size.base_unit is None
    assert no_size.base_quantity is None
    assert has_next_page(CAT_PAGE_1_HTML, "/carrefour/c/aceite-vinagre-sal-112", 1) is True
    assert has_next_page(CAT_PAGE_2_HTML, "/carrefour/c/aceite-vinagre-sal-112", 2) is False


def test_carrefour_adapter_crawls_paginated_categories():
    routes = {
        "https://radarsuper.com/carrefour": INDEX_HTML,
        "https://radarsuper.com/carrefour/c/fruta-27": "<html><h1>Fruta</h1></html>",
        "https://radarsuper.com/carrefour/c/aceite-vinagre-sal-112": CAT_PAGE_1_HTML,
        "https://radarsuper.com/carrefour/c/aceite-vinagre-sal-112/pagina/2": CAT_PAGE_2_HTML,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = CarrefourAdapter(delay=0.0, client=client)
    observations = list(adapter.crawl("0000GV"))

    cats = [o for o in observations if isinstance(o, CategoryObservation)]
    prods = [o for o in observations if isinstance(o, ProductObservation)]
    raws = [o for o in observations if isinstance(o, RawResponse)]

    assert len(cats) == 2
    assert len(raws) == 3
    assert [p.sku for p in prods] == [
        "aceite-de-aguacate-la-masia-250-ml-carrefour",
        "aceite-girasol-5-l-carrefour",
    ]
    assert prods[1].price_per_unit == Decimal("2.8500")
