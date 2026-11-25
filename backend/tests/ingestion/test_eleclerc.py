"""Unit tests for the E.Leclerc León folletos adapter (synthetic payloads only, NFR-07)."""

from __future__ import annotations

import json
from decimal import Decimal as D

import httpx

from smart_basket.ingestion.base import collect
from smart_basket.ingestion.eleclerc import (
    FOLLETOS_LEON_URL,
    ELeclercAdapter,
    parse_eleclerc_flyer_urls,
    parse_eleclerc_ipaper_html,
    parse_eleclerc_page_text,
)
from smart_basket.ingestion.http import Fetcher

LEON_HTML = """
<div class="folletos">
  <a href="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/del-9-a-21-de-nov/">H.O. 20</a>
  <a href="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/del-9-a-21-de-nov/">H.O. 20</a>
  <a href="https://folletos.e-leclerc.es/eleclerc-spain/leon-perfumeria/">Perfumería</a>
  <a href="https://www.e-leclerc.es/leon/ofertas">No es un folleto</a>
</div>
"""

# OCR lines shaped after the real E.Leclerc León `pageTexts` (`ho20`): a split euro price with
# the kilo reference in parentheses, a two-alternative line whose price belongs to the last
# one, a scrambled ANTES/AHORA pair, and a price-only banner with no product name.
PAGE_TEXTS = [
    "2 € PAN DE MOLDE NATURAL 100% SIN CORTEZA “BIMBO”. Original o integral. 450 g. "
    "(El kg a 6,64 € ). ,99 LA UNIDAD",
    "CHAPATA RÚSTICA Original, 180 g (1) O PAN DE HOGAZA “RECONDO”. "
    "100% integral pipas o cereales, 240 g (2) . (1)(El kg a 13,28 € ). 2 € (2)(El kg a 9,96 € ). "
    ",39 LA UNIDAD",
    "14 11 € ANTES: EL PACK AHORA: € ,95 ,95 EL PACK PACK DE 12 VASOS MOD TOKIO PASABAHCE",
    "5 € ANTES: ,95 LA UNIDAD 5 € AHORA: ,80 LA UNIDAD",
]


def ipaper_html(name: str, page_texts: list[str]) -> str:
    settings = json.dumps({"name": name, "pageTexts": page_texts}, ensure_ascii=False)
    return f"<script>window.staticSettings = {settings};</script>"


def test_parse_eleclerc_flyer_urls_deduplicates_preserving_order():
    urls = parse_eleclerc_flyer_urls(LEON_HTML)
    assert urls == [
        "https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/del-9-a-21-de-nov/",
        "https://folletos.e-leclerc.es/eleclerc-spain/leon-perfumeria/",
    ]
    assert parse_eleclerc_flyer_urls("<p>sin folletos</p>") == []


def test_parse_eleclerc_page_text_rebuilds_the_split_unit_price():
    products = parse_eleclerc_page_text(
        PAGE_TEXTS[0],
        category_code="folletos/h-o-20",
        flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/",
    )
    assert len(products) == 1
    product = products[0]
    assert product.name == (
        "PAN DE MOLDE NATURAL 100% SIN CORTEZA “BIMBO”. Original o integral. 450 g"
    )
    assert product.price == D("2.99")
    assert product.regular_price is None
    assert product.base_quantity == D("0.4500")
    assert product.base_unit == "kg"
    assert product.pack_count == 1
    assert product.price_per_unit == D("6.6400")
    assert product.sku == (
        "eleclerc-pan-de-molde-natural-100-sin-corteza-bimbo-original-o-integral-450-g"
    )
    assert product.url == "https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/"
    assert product.category_code == "folletos/h-o-20"


def test_parse_eleclerc_page_text_keeps_the_alternative_the_price_belongs_to():
    products = parse_eleclerc_page_text(
        PAGE_TEXTS[1],
        category_code="folletos/h-o-20",
        flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/",
    )
    assert len(products) == 1
    product = products[0]
    assert product.name == "PAN DE HOGAZA “RECONDO”. 100% integral pipas o cereales, 240 g"
    assert product.price == D("2.39")
    assert product.base_quantity == D("0.2400")
    assert product.base_unit == "kg"
    assert product.price_per_unit == D("9.9600")


def test_parse_eleclerc_page_text_reads_the_scrambled_antes_ahora_pair():
    products = parse_eleclerc_page_text(
        PAGE_TEXTS[2],
        category_code="folletos/h-o-20",
        flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/",
    )
    assert len(products) == 1
    product = products[0]
    assert product.name == "PACK DE 12 VASOS MOD TOKIO PASABAHCE"
    assert product.regular_price == D("14.95")
    assert product.price == D("11.95")
    assert product.sku == "eleclerc-pack-de-12-vasos-mod-tokio-pasabahce"


def test_parse_eleclerc_page_text_skips_a_price_only_banner():
    products = parse_eleclerc_page_text(
        PAGE_TEXTS[3],
        category_code="folletos/h-o-20",
        flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/",
    )
    assert products == []


def test_parse_eleclerc_ipaper_html_reads_static_settings_and_page_texts():
    html = ipaper_html("H.O. 20 Del 9 al 21 de nov. de 2026", PAGE_TEXTS)
    categories, products = parse_eleclerc_ipaper_html(
        html, flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/"
    )

    assert [(category.code, category.name, category.parent_code) for category in categories] == [
        ("folletos", "Folletos E.Leclerc", None),
        (
            "folletos/h-o-20-del-9-al-21-de-nov-de-2026",
            "H.O. 20 Del 9 al 21 de nov. de 2026",
            "folletos",
        ),
    ]
    assert [product.sku for product in products] == [
        "eleclerc-pan-de-molde-natural-100-sin-corteza-bimbo-original-o-integral-450-g",
        "eleclerc-pan-de-hogaza-recondo-100-integral-pipas-o-cereales-240-g",
        "eleclerc-pack-de-12-vasos-mod-tokio-pasabahce",
    ]


def test_parse_eleclerc_ipaper_html_survives_a_page_without_settings():
    categories, products = parse_eleclerc_ipaper_html(
        "<html><body>folleto roto</body></html>",
        flyer_url="https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/",
    )
    assert categories == []
    assert products == []


def test_eleclerc_adapter_crawls_the_leon_flyers_of_the_chain_wide_zone():
    flyer_url = "https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/del-9-a-21-de-nov/"
    index_html = f'<a href="{flyer_url}">H.O. 20</a>'

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == FOLLETOS_LEON_URL:
            return httpx.Response(200, text=index_html)
        if url == flyer_url:
            return httpx.Response(
                200, text=ipaper_html("H.O. 20 Del 9 al 21 de nov. de 2026", PAGE_TEXTS)
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = ELeclercAdapter(fetcher=Fetcher(client, delay=0.0, backoff=0.0))
    result = collect(adapter, "es")

    assert result.status == "succeeded"
    assert result.complete is True
    assert result.errors == ()
    requested = {raw.url for raw in result.raw}
    assert requested == {FOLLETOS_LEON_URL, flyer_url}
    assert {category.code for category in result.categories} == {
        "folletos",
        "folletos/h-o-20-del-9-al-21-de-nov-de-2026",
    }
    assert [product.sku for product in result.products] == [
        "eleclerc-pan-de-molde-natural-100-sin-corteza-bimbo-original-o-integral-450-g",
        "eleclerc-pan-de-hogaza-recondo-100-integral-pipas-o-cereales-240-g",
        "eleclerc-pack-de-12-vasos-mod-tokio-pasabahce",
    ]


def test_eleclerc_adapter_reports_a_failing_flyer_without_stopping_the_run():
    flyer_url = "https://folletos.e-leclerc.es/eleclerc-spain/leon-ho20/del-9-a-21-de-nov/"
    other_url = "https://folletos.e-leclerc.es/eleclerc-spain/leon-perfumeria/"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == FOLLETOS_LEON_URL:
            return httpx.Response(200, text=LEON_HTML)
        if url == flyer_url:
            return httpx.Response(500)
        if url == other_url:
            return httpx.Response(200, text=ipaper_html("Perfumería", []))
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = ELeclercAdapter(fetcher=Fetcher(client, delay=0.0, backoff=0.0, retries=0))
    result = collect(adapter, "es")

    assert result.status == "partial"
    assert result.complete is False
    assert [error.url for error in result.errors] == [flyer_url]
    assert result.products == ()
