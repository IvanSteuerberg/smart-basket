"""Lupa adapter: Magento 2 HTML catalog on `lupaonline.com` via browser fetch (ADR 0006).

Lupa's WAF rejects bare HTTP clients (HTTP 400), so `PlaywrightLupaTransport` opens one headed
Chromium session (`with-xvfb` in Docker) and replays same-origin `fetch()` calls for the menu
and each L2 category page (`?p=1, 2, ...`). Parsers are pure and tested on synthetic HTML
(NFR-07); prices and quantities stay `Decimal` (decision 0016).
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

BASE_URL = "https://www.lupaonline.com"
STORE_PREFIX = "/santander"
PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

_FETCH_TEXT_JS = """
async (u) => {
  const r = await fetch(u, { signal: AbortSignal.timeout(30000) });
  return [r.status, await r.text()];
}
"""

_NAV_LINK_RE = re.compile(
    r'<a[^>]*href="https://www\.lupaonline\.com/santander/([a-z0-9-]+(?:/[a-z0-9-]+)?)/?"[^>]*>\s*(?:<span[^>]*>)?([^<]+)(?:</span>)?\s*</a>',
    re.IGNORECASE,
)
_ITEM_SPLIT_RE = re.compile(r'<li[^>]*class="[^"]*product-item[^"]*"[^>]*>', re.IGNORECASE)
_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*product-item-link[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LINK_ALT_RE = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*product-item-link[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_PRICE_RE = re.compile(r'data-price-amount="(\d+(?:[.,]\d+)?)"', re.IGNORECASE)
_SKU_RE = re.compile(r'data-product-sku="([^"]+)"', re.IGNORECASE)
_ID_RE = re.compile(r'data-product-id="([^"]+)"', re.IGNORECASE)
_IMG_RE = re.compile(
    r'<img[^>]*class="[^"]*product-image-photo[^"]*"[^>]*src="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
_IMG_ALT_RE = re.compile(
    r'<img[^>]*src="([^"]+)"[^>]*class="[^"]*product-image-photo[^"]*"',
    re.IGNORECASE | re.DOTALL,
)
_SKIP_SLUGS = frozenset(
    {
        "customer",
        "checkout",
        "catalogsearch",
        "ofertas",
        "folletos",
        "novedades",
        "contacto",
        "tiendas",
    }
)


class LupaTransport(Protocol):
    """Injectable transport for Lupa; unit tests use a fake."""

    def fetch_html(self, path_and_query: str) -> tuple[int, bytes]: ...

    def close(self) -> None: ...


class PlaywrightLupaTransport:
    """Replays same-origin HTML fetches inside one headed Chromium session."""

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
                f"{BASE_URL}{STORE_PREFIX}/", wait_until="domcontentloaded", timeout=60_000
            )
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
        url = path_and_query if path_and_query.startswith("http") else f"{BASE_URL}{path_and_query}"
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


def parse_lupa_categories(homepage_html: str) -> list[CategoryObservation]:
    """Extract L1 (`alimentacion`) and L2 (`alimentacion/aceites`) categories from Lupa's nav."""
    l1: dict[str, str] = {}
    l2: dict[str, str] = {}
    for slug, raw_label in _NAV_LINK_RE.findall(homepage_html):
        label = _clean_text(raw_label)
        if not label:
            continue
        parts = slug.strip("/").split("/")
        if parts[0] in _SKIP_SLUGS:
            continue
        if len(parts) == 1 and parts[0] not in l1:
            l1[parts[0]] = label
        elif len(parts) == 2 and slug not in l2:
            l2[slug] = label

    out: list[CategoryObservation] = [
        CategoryObservation(code=code, name=name, parent_code=None) for code, name in l1.items()
    ]
    for code, name in l2.items():
        parent = code.split("/", 1)[0]
        if parent in l1:
            out.append(CategoryObservation(code=code, name=name, parent_code=parent))
    return out


def parse_lupa_products(page_html: str, *, category_code: str) -> list[ProductObservation]:
    """Parse Magento 2 `li.product-item` cards from one Lupa category page."""
    chunks = _ITEM_SPLIT_RE.split(page_html)
    if len(chunks) < 2:
        return []
    products: list[ProductObservation] = []
    seen: set[str] = set()
    for chunk in chunks[1:]:
        link = _LINK_RE.search(chunk) or _LINK_ALT_RE.search(chunk)
        price_m = _PRICE_RE.search(chunk)
        sku_m = _SKU_RE.search(chunk) or _ID_RE.search(chunk)
        if link is None or price_m is None or sku_m is None:
            continue
        sku = sku_m.group(1).strip()
        if not sku or sku in seen:
            continue
        url = link.group(1).strip()
        name = _clean_text(link.group(2))
        price = _decimal(price_m.group(1), PRICE_STEP)
        if not name or price is None:
            continue
        seen.add(sku)

        base_quantity, base_unit, pack_count = parse_dia_size(name)
        ppu: Decimal | None = None
        if base_quantity is not None and base_unit is not None:
            total = base_quantity * pack_count
            if total > 0:
                ppu = (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)

        img_m = _IMG_RE.search(chunk) or _IMG_ALT_RE.search(chunk)
        image_url = img_m.group(1).strip() if img_m else None
        if image_url and not image_url.startswith("http"):
            image_url = f"{BASE_URL}{image_url}" if image_url.startswith("/") else None

        products.append(
            ProductObservation(
                sku=sku,
                name=name,
                packaging=None,
                url=url if url.startswith("http") else f"{BASE_URL}{url}",
                category_code=category_code,
                base_quantity=base_quantity,
                base_unit=base_unit,
                pack_count=pack_count,
                price=price,
                price_per_unit=ppu,
                image_url=image_url,
            )
        )
    return products


class LupaAdapter:
    """Crawls the Lupa online catalog via `PlaywrightLupaTransport`."""

    chain_code = "lupa"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        transport: LupaTransport | None = None,
        delay: float = 0.4,
        max_pages: int = 30,
    ) -> None:
        self._transport = transport or PlaywrightLupaTransport(delay_seconds=delay)
        self._max_pages = max_pages

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._transport.close()

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        home_path = f"{STORE_PREFIX}/"
        status, body = self._transport.fetch_html(home_path)
        yield RawResponse(home_path, status, body)
        if status != 200:
            yield CrawlError(url=home_path, error=f"HTTP {status}")
            return
        categories = parse_lupa_categories(body.decode("utf-8", errors="replace"))
        yield from categories
        level_two = [c for c in categories if c.parent_code is not None]
        if max_categories is not None:
            level_two = level_two[:max_categories]

        seen_skus: set[str] = set()
        for category in level_two:
            yield from self._crawl_category(category, seen_skus)

    def _crawl_category(
        self, category: CategoryObservation, seen_skus: set[str]
    ) -> Iterator[Observation]:
        cat_seen: set[str] = set()
        for page in range(1, self._max_pages + 1):
            path = f"{STORE_PREFIX}/{category.code}?p={page}"
            status, body = self._transport.fetch_html(path)
            yield RawResponse(path, status, body)
            if status != 200:
                yield CrawlError(url=path, error=f"HTTP {status}")
                return
            products = parse_lupa_products(
                body.decode("utf-8", errors="replace"), category_code=category.code
            )
            fresh_in_cat = [p for p in products if p.sku not in cat_seen]
            if not fresh_in_cat:
                return
            for p in fresh_in_cat:
                cat_seen.add(p.sku)
                if p.sku not in seen_skus:
                    seen_skus.add(p.sku)
                    yield p


def _clean_text(value: str) -> str:
    return " ".join(hmod.unescape(value).split())


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
