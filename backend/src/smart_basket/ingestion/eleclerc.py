"""E.Leclerc adapter: the León store folletos on the ipaper viewer, plain HTTP (ADR 0006).

`https://www.e-leclerc.es/leon/folletos` links the ipaper documents under
`https://folletos.e-leclerc.es/eleclerc-spain/...`; each document carries a
`window.staticSettings = {...}` blob whose `pageTexts` are the OCR text of every page. Those
lines use two shapes: a split euro price (`2 € ... ,99 LA UNIDAD` = 2.99 € per unit, with the
reference kilo price in `(El kg a 6,64 €)`) and an `ANTES:`/`AHORA:` pair where the regular and
offer prices come as integers before each label and cents after it. Prices and quantities stay
`Decimal` (decision 0016).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from smart_basket.ingestion.base import (
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)
from smart_basket.ingestion.dia import parse_dia_size
from smart_basket.ingestion.http import Fetcher, FetchError

FOLLETOS_LEON_URL = "https://www.e-leclerc.es/leon/folletos"

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

_FLYER_URL_RE = re.compile(r"https://folletos\.e-leclerc\.es/eleclerc-spain/[^\"'\s>]+")
_STATIC_SETTINGS_RE = re.compile(r"window\.staticSettings\s*=\s*")

# A price whose integer part floats apart from its cents: `2 € ... ,99 LA UNIDAD`.
_STANDALONE_INT_EUR_RE = re.compile(r"(?<![\d,])(\d+)\s*€")
# The closing cents of a price line, always exactly two digits before a space or the end.
_CENTS_RE = re.compile(r",\s*(\d{2})(?=\s|$)")
# `(El kg a 6,64 € )` and its numbered variants `(1)(El kg a 13,28 € )`.
_KG_PRICE_RE = re.compile(r"El\s+kg\s+a\s+(\d+(?:[.,]\d{1,2})?)\s*€", re.IGNORECASE)
_KG_PARENS_RE = re.compile(r"\(\s*\d*\s*\)?\s*\(?\s*El\s+kg\s+a\s+[\d.,]+\s*€?\s*\)", re.IGNORECASE)
_MARKER_RE = re.compile(r"\(\s*\d\s*\)")
_UNIT_LABELS_RE = re.compile(r"\b(?:LA UNIDAD|LA PIEZA|EL PACK|EL KILO)\b")
_PRICE_TERMINAL_RE = re.compile(r",\s*(\d{2})\s*(LA UNIDAD|LA PIEZA|EL PACK|EL KILO)")
# `14 11 € ANTES:` keeps both integer parts together; `5 € ANTES:` carries only its own.
_B_PAIR_INTS_RE = re.compile(r"(?<![\d,])(\d+)\s+(\d+)\s*€\s*ANTES", re.IGNORECASE)
_B_BEFORE_RE = re.compile(r"(?<![\d,])(\d+)\s*€?\s*ANTES", re.IGNORECASE)
_B_NOW_RE = re.compile(r"(?<![\d,])(\d+)\s*€?\s*AHORA", re.IGNORECASE)
_B_LABELS_RE = re.compile(r"ANTES\s*:|AHORA\s*:", re.IGNORECASE)


def parse_eleclerc_flyer_urls(html_text: str) -> list[str]:
    """Extract the ipaper flyer URLs from the León folletos page, order preserved."""
    urls: list[str] = []
    for url in _FLYER_URL_RE.findall(html_text):
        if url not in urls:
            urls.append(url)
    return urls


def parse_eleclerc_ipaper_html(
    html_text: str, *, flyer_url: str
) -> tuple[list[CategoryObservation], list[ProductObservation]]:
    """Parse one ipaper document: the folletos root, one L2 per flyer and its page items.

    The ipaper viewer embeds its settings as a JSON object right after
    `window.staticSettings = `; only `name` (the flyer title) and `pageTexts` (the OCR text
    of each page) matter here. Products are deduplicated by sku across pages.
    """
    settings = _static_settings(html_text)
    if settings is None:
        return [], []
    flyer_name = str(settings.get("name") or "Folleto E.Leclerc León").strip()
    if not flyer_name:
        flyer_name = "Folleto E.Leclerc León"
    category_code = f"folletos/{_slug(flyer_name)}"
    categories = [
        CategoryObservation(code="folletos", name="Folletos E.Leclerc", parent_code=None),
        CategoryObservation(code=category_code, name=flyer_name, parent_code="folletos"),
    ]

    products: list[ProductObservation] = []
    seen_skus: set[str] = set()
    page_texts = settings.get("pageTexts")
    if isinstance(page_texts, list):
        for raw in page_texts:
            if not isinstance(raw, str):
                continue
            for observation in parse_eleclerc_page_text(
                raw, category_code=category_code, flyer_url=flyer_url
            ):
                if observation.sku not in seen_skus:
                    seen_skus.add(observation.sku)
                    products.append(observation)
    return categories, products


def parse_eleclerc_page_text(
    text: str, *, category_code: str, flyer_url: str
) -> list[ProductObservation]:
    """Parse one OCR page line into at most one product observation.

    A line with `ANTES:` is a regular-vs-offer pair; without it, the line is a plain offer
    with an optional `(El kg a ... €)` reference used for `price_per_unit`. Lines without a
    recognizable price or without a product name (price-only banners) yield nothing.
    """
    if _B_LABELS_RE.search(text):
        return _parse_antes_ahora(text, category_code=category_code, flyer_url=flyer_url)
    return _parse_unit_price(text, category_code=category_code, flyer_url=flyer_url)


class ELeclercAdapter:
    """Crawls the E.Leclerc León folletos for the chain-wide zone over plain HTTP."""

    chain_code = "eleclerc"
    zone_kind = "chain"
    retention_policy = "controlled_staples"

    def __init__(self, *, fetcher: Fetcher | None = None, delay: float = 1.5) -> None:
        self._fetcher = fetcher or Fetcher(delay=delay)
        self._owns_fetcher = fetcher is None

    def close(self) -> None:
        if self._owns_fetcher:
            self._fetcher.close()

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        try:
            response = self._fetcher.get(FOLLETOS_LEON_URL)
        except FetchError as exc:
            yield CrawlError(url=FOLLETOS_LEON_URL, error=exc.error)
            return
        yield RawResponse(FOLLETOS_LEON_URL, response.status_code, response.content)
        if response.status_code != 200:
            yield CrawlError(url=FOLLETOS_LEON_URL, error=f"HTTP {response.status_code}")
            return

        urls = parse_eleclerc_flyer_urls(response.text)
        if not urls:
            yield CrawlError(url=FOLLETOS_LEON_URL, error="no flyer links found")
            return
        if max_categories is not None:
            urls = urls[:max_categories]

        seen_skus: set[str] = set()
        for flyer_url in urls:
            try:
                flyer_response = self._fetcher.get(flyer_url)
            except FetchError as exc:
                yield CrawlError(url=flyer_url, error=exc.error)
                continue
            yield RawResponse(flyer_url, flyer_response.status_code, flyer_response.content)
            if flyer_response.status_code != 200:
                yield CrawlError(url=flyer_url, error=f"HTTP {flyer_response.status_code}")
                continue
            categories, products = parse_eleclerc_ipaper_html(
                flyer_response.text, flyer_url=flyer_url
            )
            yield from categories
            for product in products:
                if product.sku not in seen_skus:
                    seen_skus.add(product.sku)
                    yield product


def _static_settings(html_text: str) -> Mapping[str, Any] | None:
    """Decode the `window.staticSettings` JSON object embedded in an ipaper document."""
    match = _STATIC_SETTINGS_RE.search(html_text)
    if match is None:
        return None
    try:
        settings, _ = json.JSONDecoder().raw_decode(html_text[match.end() :])
    except ValueError:
        return None
    return settings if isinstance(settings, Mapping) else None


def _parse_unit_price(text: str, *, category_code: str, flyer_url: str) -> list[ProductObservation]:
    """Parse `2 € NAME ... (El kg a 6,64 € ) ... ,99 LA UNIDAD` into one observation."""
    terminals = list(_PRICE_TERMINAL_RE.finditer(text))
    if not terminals:
        return []
    terminal = terminals[-1]
    cents = Decimal(terminal.group(1)) / Decimal(100)
    integers = [
        match for match in _STANDALONE_INT_EUR_RE.finditer(text) if match.end() <= terminal.start()
    ]
    price = (Decimal(integers[-1].group(1)) + cents).quantize(PRICE_STEP) if integers else cents
    kg_price = _kg_price_before(text, terminal.start())
    name = _clean_product_text(text)
    if not name:
        return []
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    if base_quantity is None and base_unit is None and kg_price is not None and price > 0:
        # No readable weight, but the kilo price is enough to infer it.
        base_quantity = (price / kg_price).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)
        base_unit = "kg"
    return [
        _eleclerc_observation(
            name,
            price=price,
            regular_price=None,
            price_per_unit=kg_price,
            base_quantity=base_quantity,
            base_unit=base_unit,
            pack_count=pack_count,
            category_code=category_code,
            flyer_url=flyer_url,
        )
    ]


def _parse_antes_ahora(
    text: str, *, category_code: str, flyer_url: str
) -> list[ProductObservation]:
    """Parse `ANTES:`/`AHORA:` lines: integer parts before each label, cents after them.

    The OCR of two-column layouts sometimes scrambles the order into `14 11 € ANTES:`; the
    two integers then arrive together (regular first) and the cents list `,,95 ,95` supplies
    the decimals in the same order. A line whose scaffold removal leaves no name (a pure
    price banner) yields nothing, because there is no sku to key the product by.
    """
    pair = _B_PAIR_INTS_RE.search(text)
    if pair is not None:
        antes_int, ahora_int = int(pair.group(1)), int(pair.group(2))
        scaffold = _B_PAIR_INTS_RE.sub(" ", text, count=1)
    else:
        antes = _B_BEFORE_RE.search(text)
        ahora = _B_NOW_RE.search(text)
        if antes is None or ahora is None:
            return []
        antes_int, ahora_int = int(antes.group(1)), int(ahora.group(1))
        scaffold = _B_NOW_RE.sub(" ", _B_BEFORE_RE.sub(" ", text, count=1), count=1)
    cents = [match.group(1) for match in _CENTS_RE.finditer(scaffold)]
    if len(cents) < 2:
        return []
    regular = (Decimal(antes_int) + Decimal(cents[0]) / Decimal(100)).quantize(PRICE_STEP)
    price = (Decimal(ahora_int) + Decimal(cents[1]) / Decimal(100)).quantize(PRICE_STEP)
    name = _clean_product_text(scaffold)
    if not name:
        return []
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    return [
        _eleclerc_observation(
            name,
            price=price,
            regular_price=regular,
            price_per_unit=None,
            base_quantity=base_quantity,
            base_unit=base_unit,
            pack_count=pack_count,
            category_code=category_code,
            flyer_url=flyer_url,
        )
    ]


def _kg_price_before(text: str, position: int) -> Decimal | None:
    """The last `(El kg a X €)` reference before `position`, as a per-kilo price."""
    references = [match for match in _KG_PRICE_RE.finditer(text) if match.end() <= position]
    if not references:
        return None
    return _decimal(references[-1].group(1), PER_UNIT_STEP)


def _clean_product_text(text: str) -> str:
    """Strip the price scaffold from an OCR line, keeping the product name.

    Unit prices in parentheses, `(1)`/`(2)` item markers, split euro integers, cents and
    unit labels disappear; in two-alternative lines (`... O ...`) the price at the end
    belongs to the last alternative, so only that one is kept.
    """
    cleaned = _KG_PARENS_RE.sub(" ", text)
    cleaned = _STANDALONE_INT_EUR_RE.sub(" ", cleaned)
    cleaned = _MARKER_RE.sub(" ", cleaned)
    cleaned = _CENTS_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("€", " ")
    cleaned = _UNIT_LABELS_RE.sub(" ", cleaned)
    cleaned = _B_LABELS_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:;·-")
    if " O " in cleaned:
        cleaned = cleaned.rsplit(" O ", 1)[-1].strip(" .:;·-")
    return cleaned


def _eleclerc_observation(
    name: str,
    *,
    price: Decimal,
    regular_price: Decimal | None,
    price_per_unit: Decimal | None,
    base_quantity: Decimal | None,
    base_unit: str | None,
    pack_count: int,
    category_code: str,
    flyer_url: str,
) -> ProductObservation:
    return ProductObservation(
        sku=f"eleclerc-{_slug(name)}",
        name=name,
        packaging=None,
        url=flyer_url,
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=price_per_unit,
        image_url=None,
        regular_price=regular_price,
        is_temporary=False,
        valid_from=None,
        valid_until=None,
    )


def _slug(text: str) -> str:
    """Deterministic ascii slug of a Spanish product name (accents folded, dashes joined)."""
    normalized = unicodedata.normalize("NFD", text.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "item"


def _decimal(value: object, step: Decimal) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation, ValueError:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number.quantize(step, rounding=ROUND_HALF_UP)
