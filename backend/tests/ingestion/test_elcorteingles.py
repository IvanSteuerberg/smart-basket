"""Unit tests for the El Corte Inglés Supermercado HTML adapter (synthetic HTML only, NFR-07)."""

from __future__ import annotations

from decimal import Decimal

from smart_basket.ingestion.base import CrawlError, collect
from smart_basket.ingestion.elcorteingles import (
    BASE_URL,
    ElCorteInglesAdapter,
    parse_eci_categories,
    parse_eci_products,
    parse_eci_total_pages,
)

TURRON_URL = (
    "/supermercado/B001020617700313-el-almendro-palitos-de-turron-"
    "tradicional-16-unidades-calidad-suprema-lata-136-g/"
)
TURRON_IMG = (
    "https://cdn.grupoelcorteingles.es/SGFM/dctm/MEDIA03/202210/21/00120944800984____6__325x325.jpg"
)

REAL_CARD = f"""
<div id="artwork-6a9524d2df6e8045566f2105" class="artwork product food-product-preview-responsive"
     data-name="/PDT/AL+AG/RISI/0120618800948/Risi/TURRONES/270/PEN">
  <div class="food-product-preview-responsive__image_block" data-lr-plp-to-pdp="{TURRON_URL}">
    <a class="food-product-preview-responsive__link" href="{TURRON_URL}">
      <div class="food-product-preview-responsive__image">
        <img src="{TURRON_IMG}"
             alt="palitos de turr&oacute;n tradicional 16 unidades Calidad Suprema lata 136 g" />
      </div>
    </a>
  </div>
  <div class="food-prices"><div class="food-prices__price">8,45 &euro;</div></div>
  <a class="food-product-preview-responsive__description" href="{TURRON_URL}">
    palitos de turr&oacute;n tradicional 16 unidades Calidad Suprema  EL ALMENDRO
  </a>
  <span class="food-product-preview-responsive__sale_type">
    lata <span class="lighter-gray">|</span> 136 g
  </span>
  <div data-bv-show="inline_rating" data-bv-product-id="0110120617700313___"></div>
</div>
"""

SIZELESS_CARD = """
<div id="artwork-2" class="artwork product" data-name="/PDT/X">
  <div class="food-product-preview-responsive__image_block"
       data-lr-plp-to-pdp="/supermercado/B2-papel-de-cocina/">
    <a class="food-product-preview-responsive__link" href="/supermercado/B2-papel-de-cocina/">
      <div class="food-product-preview-responsive__image">
        <img src="//cdn.example.com/papel.jpg" alt="papel de cocina" />
      </div>
    </a>
  </div>
  <div class="food-prices"><div class="food-prices__price">1,20 &euro;</div></div>
  <a class="food-product-preview-responsive__description" href="/supermercado/B2-papel-de-cocina/">
    papel de cocina
  </a>
  <span class="food-product-preview-responsive__sale_type">paquete</span>
</div>
"""


def _nav(total_pages: str, *subcategories: tuple[str, str]) -> str:
    links = "".join(
        f'<a href="/supermercado/alimentacion-general/{slug}/">{name}</a>'
        for slug, name in subcategories
    )
    return f"""
<nav>
  <a href="/supermercado/alimentacion-general/">Alimentaci&oacute;n General</a>
  {links}
  <a href="/supermercado/alimentacion-general/2/">2</a>
</nav>
<div class="plp_order_by__products" data-lr-plp-total-pages="{total_pages}"><p>( 3555 )</p></div>
"""


def _card(sku: str, slug: str, description: str, price: str, sale_type: str) -> str:
    url = f"/supermercado/{sku}-{slug}/"
    return f"""
<div id="artwork-{sku}" class="artwork product" data-name="/PDT/{sku}">
  <div class="food-product-preview-responsive__image_block" data-lr-plp-to-pdp="{url}">
    <a class="food-product-preview-responsive__link" href="{url}">
      <div class="food-product-preview-responsive__image">
        <img src="https://cdn.example.com/{sku}.jpg" alt="{description}" />
      </div>
    </a>
  </div>
  <div class="food-prices"><div class="food-prices__price">{price}</div></div>
  <a class="food-product-preview-responsive__description" href="{url}">{description}</a>
  <span class="food-product-preview-responsive__sale_type">{sale_type}</span>
  <div data-bv-show="inline_rating" data-bv-product-id="011{sku}___"></div>
</div>
"""


class FakeElCorteInglesTransport:
    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self._pages = pages
        self.requested: list[str] = []

    def fetch_html(self, path_and_query: str) -> tuple[int, bytes]:
        self.requested.append(path_and_query)
        status, html = self._pages.get(path_and_query, (404, ""))
        return status, html.encode("utf-8")

    def close(self) -> None:
        pass


def test_parse_eci_categories_extracts_subcategories_and_ignores_page_numbers():
    html = _nav("149", ("aceites", "Aceites"), ("arroz-y-pasta", "Arroz y pasta"))
    cats = parse_eci_categories(
        html, l1_code="alimentacion-general", l1_name="Alimentación General"
    )
    assert [(c.code, c.name, c.parent_code) for c in cats] == [
        ("alimentacion-general", "Alimentación General", None),
        ("alimentacion-general/aceites", "Aceites", "alimentacion-general"),
        ("alimentacion-general/arroz-y-pasta", "Arroz y pasta", "alimentacion-general"),
        ("alimentacion-general/general", "Alimentación General general", "alimentacion-general"),
    ]


def test_parse_eci_total_pages_reads_data_attribute():
    assert parse_eci_total_pages(_nav("149")) == 149
    assert parse_eci_total_pages("<div>no badge here</div>") == 1


def test_parse_eci_products_extracts_sku_name_packaging_price_size_and_image():
    products = parse_eci_products(
        REAL_CARD + SIZELESS_CARD, category_code="alimentacion-general/aceites"
    )
    assert len(products) == 2

    p = products[0]
    assert p.sku == "B001020617700313"
    assert p.name == "Palitos de turrón tradicional 16 unidades Calidad Suprema EL ALMENDRO"
    assert p.packaging == "lata | 136 g"
    assert p.price == Decimal("8.45")
    assert p.base_quantity == Decimal("16.0000")
    assert p.base_unit == "ud"
    assert p.pack_count == 1
    assert p.price_per_unit == Decimal("0.5281")
    assert p.url == f"{BASE_URL}{TURRON_URL}"
    assert p.image_url == TURRON_IMG

    # A card without any recognizable size keeps the `chain_product_check` invariant:
    # quantity and unit are both empty and no unit price is guessed.
    plain = products[1]
    assert plain.sku == "B2"
    assert plain.name == "Papel de cocina"
    assert plain.packaging == "paquete"
    assert plain.price == Decimal("1.20")
    assert plain.base_quantity is None
    assert plain.base_unit is None
    assert plain.price_per_unit is None
    assert plain.image_url == "https://cdn.example.com/papel.jpg"


def test_elcorteingles_adapter_crawls_sections_and_paginates():
    milk = _card(
        "B9001", "leche-entera-pack-6-x-1-l", "leche entera pack 6 x 1 l", "6,30 €", "pack 6 x 1 l"
    )
    yogurt = _card(
        "B9002", "yogur-natural-pack-4-x-125-g", "yogur natural 125 g", "1,10 €", "pack 4 x 125 g"
    )
    transport = FakeElCorteInglesTransport(
        {
            "/supermercado/alimentacion-general/": (200, _nav("2", ("aceites", "Aceites")) + milk),
            # Page 2 repeats the milk card; only the yogurt is new.
            "/supermercado/alimentacion-general/2/": (200, milk + yogurt),
        }
    )
    adapter = ElCorteInglesAdapter(
        transport=transport,
        delay=0.0,
        sections=(("alimentacion-general", "Alimentación General"),),
    )
    result = collect(adapter, "24009")
    assert result.status == "succeeded"
    assert result.complete is True
    assert transport.requested == [
        "/supermercado/alimentacion-general/",
        "/supermercado/alimentacion-general/2/",
    ]
    assert [c.code for c in result.categories] == [
        "alimentacion-general",
        "alimentacion-general/aceites",
        "alimentacion-general/general",
    ]
    assert [p.sku for p in result.products] == ["B9001", "B9002"]
    milk_p, yogurt_p = result.products
    assert (milk_p.base_quantity, milk_p.base_unit, milk_p.pack_count) == (
        Decimal("1.0000"),
        "l",
        6,
    )
    assert milk_p.price_per_unit == Decimal("1.0500")
    assert (yogurt_p.base_quantity, yogurt_p.base_unit, yogurt_p.pack_count) == (
        Decimal("0.1250"),
        "kg",
        4,
    )


def test_elcorteingles_adapter_respects_max_categories_and_handles_http_errors():
    baby = _card("B8001", "potito-de-fruta", "potito de fruta 130 g", "0,95 €", "tarro | 130 g")
    bread = _card("B7001", "pan-de-barra", "pan de barra 250 g", "1,05 €", "ud")
    pages = {
        "/supermercado/frescos/": (200, _nav("3") + bread),
        "/supermercado/bebes/": (200, _nav("1") + baby),
    }
    sections = (("frescos", "Frescos"), ("bebes", "Bebés"))

    # A bounded run crawls one section, one page: no pagination of a 3-page listing.
    bounded_transport = FakeElCorteInglesTransport(pages)
    bounded = ElCorteInglesAdapter(transport=bounded_transport, delay=0.0, sections=sections)
    bounded_result = collect(bounded, "24009", max_categories=1)
    assert bounded_transport.requested == ["/supermercado/frescos/"]
    assert [p.sku for p in bounded_result.products] == ["B7001"]
    assert bounded_result.complete is False

    # A failing section is reported and the crawl keeps going with the next one.
    failing_transport = FakeElCorteInglesTransport(
        {"/supermercado/frescos/": (500, ""), "/supermercado/bebes/": pages["/supermercado/bebes/"]}
    )
    failing = ElCorteInglesAdapter(transport=failing_transport, delay=0.0, sections=sections)
    result = collect(failing, "24009")
    assert result.status == "partial"
    assert [p.sku for p in result.products] == ["B8001"]
    crawl_error = next(e for e in result.errors if isinstance(e, CrawlError))
    assert crawl_error.url == "/supermercado/frescos/"
