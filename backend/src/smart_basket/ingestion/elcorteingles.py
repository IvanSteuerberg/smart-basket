"""El Corte Inglés adapter: Supermercado HTML catalog via same-origin browser fetch (decision 0006).

The supermarket sits behind Akamai bot protection, so `PlaywrightElCorteInglesTransport` opens
one Chromium session on a real listing (so the Akamai cookies initialize) and replays
same-origin `fetch()` calls for each L1 section page (`/supermercado/<l1>/`, `/2/`, ...).
Parsers are pure and tested on synthetic HTML (NFR-07); prices and quantities stay `Decimal`
(decision 0016).
"""

from __future__ import annotations

import contextlib
import html as hmod
import os
import re
import sys
import time
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from smart_basket.ingestion.base import (
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)
from smart_basket.ingestion.dia import parse_dia_size

BASE_URL = "https://www.elcorteingles.es"
STORE_PREFIX = "/supermercado"
PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

#: Level 1 supermarket sections; slugs as they appear in `/supermercado/<slug>/`.
DEFAULT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("frescos", "Frescos"),
    ("alimentacion-general", "Alimentación General"),
    ("desayunos-dulces-y-pan", "Desayunos, dulces y pan"),
    ("lacteos", "Lácteos"),
    ("congelados", "Congelados"),
    ("nutricion-y-bienestar", "Nutrición y bienestar"),
    ("bebidas", "Bebidas"),
    ("bebes", "Bebés"),
    ("cuidado-personal-y-belleza", "Cuidado personal y belleza"),
    ("drogueria-y-limpieza", "Droguería y limpieza"),
    ("mascotas", "Mascotas"),
)

_FETCH_TEXT_JS = """
async (u) => {
  const r = await fetch(u, { signal: AbortSignal.timeout(30000) });
  return [r.status, await r.text()];
}
"""

_TOTAL_PAGES_RE = re.compile(r'data-lr-plp-total-pages="(\d+)"')
_ITEM_SPLIT_RE = re.compile(
    r'<div[^>]*class="[^"]*\bartwork\s+product\b[^"]*"[^>]*>', re.IGNORECASE
)
_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*food-product-preview-responsive__description[^"]*"[^>]*'
    r'href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TO_PDP_RE = re.compile(r'data-lr-plp-to-pdp="([^"]+)"')
_URL_SKU_RE = re.compile(r"/supermercado/([A-Za-z0-9]+)-")
_BV_ID_RE = re.compile(r'data-bv-product-id="([^"_]+)')
_PRODUCT_ID_RE = re.compile(r'data-product-id="([^"]+)"')
_EURO = r"(?:€|&euro;)"
_PRICE_RE = re.compile(
    r'<div[^>]*class="[^"]*food-prices__price(?:--sale)?[^"]*"[^>]*>'
    rf"\s*([0-9]+(?:[.,][0-9]{{1,2}})?)\s*{_EURO}"
)
_PRICE_FALLBACK_RE = re.compile(
    rf'<div[^>]*class="[^"]*food-prices\b[^"]*"[^>]*>.*?([0-9]+(?:[.,][0-9]{{1,2}})?)\s*{_EURO}',
    re.IGNORECASE | re.DOTALL,
)
# The sale type wraps its separator in a nested `<span class="lighter-gray">|</span>`,
# so the capture must cross one nested span before the outer closing tag.
_SALE_TYPE_RE = re.compile(
    r'<span[^>]*class="[^"]*food-product-preview-responsive__sale_type[^"]*"[^>]*>'
    r"((?:<span[^>]*>[^<]*</span>|(?!</span>).)*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_IMG_RE = re.compile(
    r'<div[^>]*class="[^"]*food-product-preview-responsive__image[^"]*"[^>]*>\s*'
    r'<img[^>]*src="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


class ElCorteInglesTransport(Protocol):
    """Injectable transport for El Corte Inglés; unit tests use a fake."""

    def fetch_html(self, path_and_query: str) -> tuple[int, bytes]: ...

    def close(self) -> None: ...


class PlaywrightElCorteInglesTransport:
    """Replays same-origin HTML fetches inside one Chromium session."""

    def __init__(self, *, delay_seconds: float = 0.4, headless: bool | None = None) -> None:
        self._delay_seconds = delay_seconds
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._requests = 0

    def _headless_flag(self) -> bool:
        if self._headless is not None:
            return self._headless
        return not (os.environ.get("DISPLAY") or sys.platform == "win32")

    def _ensure_page(self) -> Any:
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=self._headless_flag())
            context = self._browser.new_context(locale="es-ES")
            self._page = context.new_page()
            self._page.goto(
                f"{BASE_URL}{STORE_PREFIX}/alimentacion-general/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            # Akamai initializes its session cookies on the first listing; a short wait
            # keeps the later same-origin fetches from being challenged.
            self._page.wait_for_timeout(2500)
        except Exception:
            self.close()
            raise
        return self._page

    def _pause(self) -> None:
        if self._requests and self._delay_seconds:
            time.sleep(self._delay_seconds)
        self._requests += 1

    def fetch_html(self, path_and_query: str) -> tuple[int, bytes]:
        page = self._ensure_page()
        self._pause()
        url = (
            path_and_query
            if path_and_query.startswith(("http://", "https://"))
            else f"{BASE_URL}{path_and_query}"
        )
        status, text = page.evaluate(_FETCH_TEXT_JS, url)
        return int(status), str(text).encode("utf-8")

    def close(self) -> None:
        page, browser, playwright = self._page, self._browser, self._playwright
        self._page = self._browser = self._playwright = None
        if page is not None:
            with contextlib.suppress(Exception):
                page.context.close()
        if browser is not None:
            with contextlib.suppress(Exception):
                browser.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                playwright.stop()


def parse_eci_categories(
    page_html: str, *, l1_code: str, l1_name: str
) -> list[CategoryObservation]:
    """Emit the L1 root, its linked L2 sections and a `<l1>/general` fallback.

    The fallback keeps products parsed straight from the L1 listing (no matched L2 link)
    inside a valid level-2 `category_code`. Numeric pagination links (`/<l1>/2/`) are skipped.
    """
    categories: dict[str, CategoryObservation] = {
        l1_code: CategoryObservation(code=l1_code, name=l1_name, parent_code=None)
    }
    link_re = re.compile(
        rf'<a[^>]*href="/supermercado/{re.escape(l1_code)}/([a-z0-9-]+)/?"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for sub_slug, raw_label in link_re.findall(page_html):
        if sub_slug.isdigit():
            continue
        name = _clean_text(raw_label)
        if not name:
            continue
        code = f"{l1_code}/{sub_slug}"
        categories.setdefault(code, CategoryObservation(code=code, name=name, parent_code=l1_code))
    categories.setdefault(
        f"{l1_code}/general",
        CategoryObservation(
            code=f"{l1_code}/general", name=f"{l1_name} general", parent_code=l1_code
        ),
    )
    return list(categories.values())


def parse_eci_total_pages(page_html: str) -> int:
    """Read the listing's page-count badge; a page without it counts as a single page."""
    match = _TOTAL_PAGES_RE.search(page_html)
    return int(match.group(1)) if match else 1


def parse_eci_products(page_html: str, *, category_code: str) -> list[ProductObservation]:
    """Parse `.artwork.product` cards from one listing page."""
    chunks = _ITEM_SPLIT_RE.split(page_html)
    if len(chunks) < 2:
        return []
    products: list[ProductObservation] = []
    seen: set[str] = set()
    for chunk in chunks[1:]:
        product = _parse_product_card(chunk, category_code)
        if product is None or product.sku in seen:
            continue
        seen.add(product.sku)
        products.append(product)
    return products


def _parse_product_card(chunk: str, category_code: str) -> ProductObservation | None:
    link = _LINK_RE.search(chunk)
    if link is None:
        pdp_m = _TO_PDP_RE.search(chunk)
        if pdp_m is None:
            return None
        url, raw_name = pdp_m.group(1), ""
    else:
        url, raw_name = link.group(1), link.group(2)
    sku = _extract_sku(chunk, url)
    name = _capitalize(_clean_text(raw_name))
    if not sku or not name:
        return None
    price = _card_price(chunk)
    if price is None:
        return None

    packaging = _card_packaging(chunk)
    base_quantity, base_unit, pack_count = parse_dia_size(f"{name} {packaging or ''}")
    if base_quantity is None or base_unit is None or base_quantity <= 0:
        base_quantity = base_unit = None
    ppu: Decimal | None = None
    if base_quantity is not None and base_unit is not None:
        total = base_quantity * pack_count
        if total > 0:
            ppu = (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)

    return ProductObservation(
        sku=sku,
        name=name,
        packaging=packaging,
        url=_absolute_url(url),
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=ppu,
        image_url=_card_image(chunk),
    )


def _extract_sku(chunk: str, url: str) -> str | None:
    match = _URL_SKU_RE.search(url)
    if match is None:
        match = _BV_ID_RE.search(chunk) or _PRODUCT_ID_RE.search(chunk)
    return match.group(1).strip() if match else None


def _card_price(chunk: str) -> Decimal | None:
    match = _PRICE_RE.search(chunk) or _PRICE_FALLBACK_RE.search(chunk)
    return None if match is None else _decimal(match.group(1), PRICE_STEP)


def _card_packaging(chunk: str) -> str | None:
    match = _SALE_TYPE_RE.search(chunk)
    if match is None:
        return None
    packaging = _clean_text(match.group(1))
    return packaging or None


def _card_image(chunk: str) -> str | None:
    match = _IMG_RE.search(chunk)
    if match is None:
        return None
    return _absolute_url(match.group(1).strip())


def _absolute_url(value: str) -> str | None:
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return None


class ElCorteInglesAdapter:
    """Crawls the El Corte Inglés Supermercado catalog through one browser session.

    The catalog is national, so `zone_code` (a postal code) only selects which zone the
    products are recorded against; the crawl itself is identical for every zone.
    """

    chain_code = "elcorteingles"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        transport: ElCorteInglesTransport | None = None,
        delay: float = 0.4,
        max_pages: int = 160,
        sections: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        self._transport = transport or PlaywrightElCorteInglesTransport(delay_seconds=delay)
        self._max_pages = max_pages
        self._sections = DEFAULT_SECTIONS if sections is None else sections

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._transport.close()

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        sections = list(self._sections)
        if max_categories is not None:
            sections = sections[:max_categories]
        # A bounded run stays bounded: one listing page per section, no pagination.
        max_pages = 1 if max_categories is not None else self._max_pages

        seen_skus: set[str] = set()
        for l1_slug, l1_name in sections:
            path = f"{STORE_PREFIX}/{l1_slug}/"
            status, body = self._transport.fetch_html(path)
            yield RawResponse(path, status, body)
            if status != 200:
                yield CrawlError(url=path, error=f"HTTP {status}")
                continue
            html1 = body.decode("utf-8", errors="replace")
            yield from parse_eci_categories(html1, l1_code=l1_slug, l1_name=l1_name)
            default_cat_code = f"{l1_slug}/general"
            yield from _fresh_products(html1, default_cat_code, seen_skus)
            total_pages = min(parse_eci_total_pages(html1), max_pages)
            for page_num in range(2, total_pages + 1):
                page_path = f"{STORE_PREFIX}/{l1_slug}/{page_num}/"
                status, body = self._transport.fetch_html(page_path)
                yield RawResponse(page_path, status, body)
                if status != 200:
                    yield CrawlError(url=page_path, error=f"HTTP {status}")
                    break
                page_html = body.decode("utf-8", errors="replace")
                fresh = _fresh_products(page_html, default_cat_code, seen_skus)
                yield from fresh
                if not fresh:
                    break


def _fresh_products(
    page_html: str, category_code: str, seen_skus: set[str]
) -> list[ProductObservation]:
    """Products of one page whose SKUs the crawl has not yielded yet."""
    fresh = [
        product
        for product in parse_eci_products(page_html, category_code=category_code)
        if product.sku not in seen_skus
    ]
    seen_skus.update(product.sku for product in fresh)
    return fresh


def _clean_text(value: str) -> str:
    return " ".join(hmod.unescape(_TAG_RE.sub(" ", value)).split())


def _capitalize(name: str) -> str:
    return name[:1].upper() + name[1:]


def _decimal(value: str, step: Decimal) -> Decimal | None:
    try:
        number = Decimal(value.strip().replace(",", "."))
    except InvalidOperation, ValueError:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number.quantize(step, rounding=ROUND_HALF_UP)
