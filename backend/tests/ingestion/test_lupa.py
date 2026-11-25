"""Unit tests for the Lupa Magento 2 HTML adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

from decimal import Decimal

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.lupa import (
    LupaAdapter,
    parse_lupa_categories,
    parse_lupa_products,
)

SAMPLE_HOME = """
<nav>
  <a href="https://www.lupaonline.com/santander/alimentacion"><span>Alimentaci&oacute;n</span></a>
  <a href="https://www.lupaonline.com/santander/alimentacion/aceites">Aceites</a>
  <a href="https://www.lupaonline.com/santander/ofertas">Ofertas</a>
</nav>
"""

SAMPLE_PLP = """
<ul>
  <li class="item product product-item">
    <img class="product-image-photo" src="https://www.lupaonline.com/media/101220.jpg" />
    <a class="product-item-link" href="https://www.lupaonline.com/santander/aceite-101220">
      Aceite Abril De Oliva Virgen 1 l
    </a>
    <span data-price-amount="3.95">3,95 €</span>
    <form data-product-sku="101220"></form>
  </li>
</ul>
"""


class FakeLupaTransport:
    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self._pages = pages
        self.closed = False

    def fetch_html(self, path_and_query: str) -> tuple[int, bytes]:
        status, html = self._pages.get(path_and_query, (200, "<ul></ul>"))
        return status, html.encode("utf-8")

    def close(self) -> None:
        self.closed = True


def test_parse_lupa_categories_filters_non_catalog_links():
    cats = parse_lupa_categories(SAMPLE_HOME)
    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("alimentacion", "Alimentación", None),
        ("alimentacion/aceites", "Aceites", "alimentacion"),
    ]


def test_parse_lupa_products_extracts_sku_price_and_size():
    prods = parse_lupa_products(SAMPLE_PLP, category_code="alimentacion/aceites")
    assert len(prods) == 1
    p = prods[0]
    assert p.sku == "101220"
    assert p.name == "Aceite Abril De Oliva Virgen 1 l"
    assert p.price == Decimal("3.95")
    assert p.base_quantity == Decimal("1.0000")
    assert p.base_unit == "l"
    assert p.image_url == "https://www.lupaonline.com/media/101220.jpg"


def test_lupa_adapter_stops_when_page_repeats():
    transport = FakeLupaTransport(
        {
            "/santander/": (200, SAMPLE_HOME),
            "/santander/alimentacion/aceites?p=1": (200, SAMPLE_PLP),
            "/santander/alimentacion/aceites?p=2": (200, SAMPLE_PLP),
        }
    )
    result = collect(LupaAdapter(transport=transport, delay=0.0), "24001")
    assert result.status == "succeeded"
    assert [p.sku for p in result.products] == ["101220"]
