"""Unit tests for the Alimerka Commerce Cloud HTML adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from smart_basket.ingestion.alimerka import (
    AlimerkaAdapter,
    parse_alimerka_categories,
    parse_alimerka_grid,
)
from smart_basket.ingestion.base import collect

SAMPLE_HOME = """
<nav>
  <a href="https://www.alimerkaonline.es/101">Alimentaci&oacute;n</a>
  <a href="https://www.alimerkaonline.es/10101">Aceite, Vinagre y Condimentos</a>
  <a href="https://www.alimerkaonline.es/10102">Arroz y Pasta</a>
</nav>
"""

SAMPLE_GRID = """
<div data-pid="10032140">
  <img class="tile-image" src="https://www.alimerkaonline.es/media/10032140.png" />
  <div class="card__body-title"><a class="link" href="#">&Ntilde;AMING</a></div>
  <div class="pdp-link">
    <a class="link" href="https://www.alimerkaonline.es/10032140.html">SANDWICH PAVO 200 G.</a>
  </div>
  <span class="value" content="2.99">2,99 &euro;</span>
  <span class="unit-price-per-unit">(14,95 &#8364;/kg)</span>
</div>
"""


def test_parse_alimerka_categories_extracts_l1_and_l2():
    cats = parse_alimerka_categories(SAMPLE_HOME)
    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("101", "Alimentación", None),
        ("10101", "Aceite, Vinagre y Condimentos", "101"),
        ("10102", "Arroz y Pasta", "101"),
    ]


def test_parse_alimerka_grid_extracts_price_brand_and_size():
    products = parse_alimerka_grid(SAMPLE_GRID, category_code="10101")
    assert len(products) == 1
    p = products[0]
    assert p.sku == "10032140"
    assert "Sandwich pavo 200 g" in p.name
    assert "Ñaming" in p.name
    assert p.price == Decimal("2.99")
    assert p.price_per_unit == Decimal("14.9500")
    assert p.base_quantity == Decimal("0.2000")
    assert p.base_unit == "kg"
    assert p.url == "https://www.alimerkaonline.es/10032140.html"


def test_alimerka_adapter_crawls_and_deduplicates():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "Stores-FindByZipcode" in url:
            return httpx.Response(200, json={"action": "Stores-FindByZipcode"})
        if url == "https://www.alimerkaonline.es/":
            return httpx.Response(200, text=SAMPLE_HOME)
        if "Search-UpdateGrid" in url:
            return httpx.Response(200, text=SAMPLE_GRID)
        return httpx.Response(404)

    adapter = AlimerkaAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)), delay=0)
    result = collect(adapter, "24001")
    assert result.status == "succeeded"
    assert [p.sku for p in result.products] == ["10032140"]
