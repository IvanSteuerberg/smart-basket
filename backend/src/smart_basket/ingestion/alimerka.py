"""Alimerka adapter: Salesforce Commerce Cloud HTML grid over plain HTTP (ADR 0006).

Alimerka binds a Spanish postal code via `Stores-FindByZipcode?consent=true&zipcode=<cp>`,
publishes its 3-digit (L1) and 5-digit (L2) category tree on the homepage, and serves paginated
product grids via `Search-UpdateGrid?cgid=<l2>&start=<offset>&sz=100`. No browser needed.
All prices and quantities stay `Decimal` (decision 0016).
"""

from __future__ import annotations

import contextlib
import html as hmod
import re
import time
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx

from smart_basket.ingestion.base import (
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)
from smart_basket.ingestion.dia import parse_dia_size

BASE_URL = "https://www.alimerkaonline.es"
DW_BASE = f"{BASE_URL}/on/demandware.store/Sites-Alimerka-Site/default"
ZIP_URL = f"{DW_BASE}/Stores-FindByZipcode"
GRID_URL = f"{DW_BASE}/Search-UpdateGrid"

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")
PAGE_SIZE = 100

_CAT_LINK_RE = re.compile(
    r'href="https://www\.alimerkaonline\.es/(\d{3,5})"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_TILE_SPLIT_RE = re.compile(r'data-pid="([^"]+)"')
_PDP_LINK_RE = re.compile(
    r'<div class="pdp-link">\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_BRAND_RE = re.compile(
    r'<div class="card__body-title">\s*<a[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_IMG_RE = re.compile(
    r'<img[^>]*class="tile-image"[^>]*src="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
_PRICE_RE = re.compile(
    r'<span class="value"[^>]*content="(\d+(?:[.,]\d+)?)"',
    re.IGNORECASE,
)
_UNIT_PRICE_RE = re.compile(
    r'class="unit-price-per-unit"[^>]*>\s*\(\s*(\d+(?:[.,]\d+)?)\s*(?:€|&euro;|&#8364;)\s*/\s*([a-zA-Z]+)\s*\)',
    re.IGNORECASE | re.DOTALL,
)


def parse_alimerka_categories(homepage_html: str) -> list[CategoryObservation]:
    """Extract L1 (3-digit) and L2 (5-digit) categories from Alimerka's homepage menu."""
    l1: dict[str, str] = {}
    l2: dict[str, str] = {}
    for code, raw_label in _CAT_LINK_RE.findall(homepage_html):
        label = _clean_text(raw_label)
        if not label:
            continue
        if len(code) == 3 and code not in l1:
            l1[code] = label
        elif len(code) == 5 and code not in l2:
            l2[code] = label

    out: list[CategoryObservation] = [
        CategoryObservation(code=code, name=name, parent_code=None) for code, name in l1.items()
    ]
    for code, name in l2.items():
        parent = code[:3]
        if parent in l1:
            out.append(CategoryObservation(code=code, name=name, parent_code=parent))
    return out


def parse_alimerka_grid(grid_html: str, *, category_code: str) -> list[ProductObservation]:
    """Parse one `Search-UpdateGrid` HTML fragment into `ProductObservation` entries."""
    parts = _TILE_SPLIT_RE.split(grid_html)
    if len(parts) < 3:
        return []
    products: list[ProductObservation] = []
    seen_in_page: set[str] = set()
    for index in range(1, len(parts), 2):
        sku = parts[index].strip()
        chunk = parts[index + 1] if index + 1 < len(parts) else ""
        if not sku or sku in seen_in_page:
            continue
        # Only parse the outer tile container that holds `.pdp-link` and `.price`.
        pdp = _PDP_LINK_RE.search(chunk)
        price_match = _PRICE_RE.search(chunk)
        if pdp is None or price_match is None:
            continue
        url = pdp.group(1).strip()
        raw_name = _clean_text(pdp.group(2))
        price = _decimal(price_match.group(1), PRICE_STEP)
        if not raw_name or price is None:
            continue
        seen_in_page.add(sku)

        brand_match = _BRAND_RE.search(chunk)
        brand = _clean_text(brand_match.group(1)) if brand_match else ""
        # Include brand in name if it's not already mentioned (helps canonical matching).
        name = _format_name(raw_name, brand)
        base_quantity, base_unit, pack_count = parse_dia_size(name)

        ppu: Decimal | None = None
        up_match = _UNIT_PRICE_RE.search(chunk)
        if up_match is not None:
            ppu = _decimal(up_match.group(1), PER_UNIT_STEP)
            unit_raw = up_match.group(2).strip().lower()
            if base_quantity is None and ppu is not None and ppu > 0:
                inferred_unit = None
                if unit_raw in ("kg", "kilo", "kilos"):
                    inferred_unit = "kg"
                elif unit_raw in ("l", "lt", "litro", "litros"):
                    inferred_unit = "l"
                elif unit_raw in ("ud", "uds", "unidad", "unidades"):
                    inferred_unit = "ud"
                if inferred_unit is not None:
                    inferred_qty = (price / ppu).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    if inferred_qty > 0:
                        base_quantity, base_unit = inferred_qty, inferred_unit
        if base_quantity is None or base_unit is None:
            base_quantity, base_unit = None, None
        if ppu is None and base_quantity is not None and base_unit is not None:
            total = base_quantity * pack_count
            if total > 0:
                ppu = (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)

        img_match = _IMG_RE.search(chunk)
        image_url = img_match.group(1).strip() if img_match else None
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


class AlimerkaAdapter:
    """Crawls the Alimerka online catalog for one Spanish postal code over plain HTTP."""

    chain_code = "alimerka"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        delay: float = 0.4,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        self._delay = delay
        self._page_size = page_size
        self._requests = 0

    def close(self) -> None:
        if self._owns_client:
            with contextlib.suppress(Exception):
                self._client.close()

    def _pause(self) -> None:
        if self._requests and self._delay:
            time.sleep(self._delay)
        self._requests += 1

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        zip_url = f"{ZIP_URL}?consent=true&zipcode={zone_code}"
        self._pause()
        try:
            z_resp = self._client.get(zip_url)
        except httpx.HTTPError as exc:
            yield CrawlError(url=zip_url, error=str(exc))
            return
        yield RawResponse(zip_url, z_resp.status_code, z_resp.content)
        if z_resp.status_code != 200:
            yield CrawlError(url=zip_url, error=f"HTTP {z_resp.status_code}")
            return

        home_url = f"{BASE_URL}/"
        self._pause()
        try:
            h_resp = self._client.get(home_url)
        except httpx.HTTPError as exc:
            yield CrawlError(url=home_url, error=str(exc))
            return
        yield RawResponse(home_url, h_resp.status_code, h_resp.content)
        if h_resp.status_code != 200:
            yield CrawlError(url=home_url, error=f"HTTP {h_resp.status_code}")
            return

        categories = parse_alimerka_categories(h_resp.text)
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
        start = 0
        while True:
            url = f"{GRID_URL}?cgid={category.code}&start={start}&sz={self._page_size}"
            self._pause()
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:
                yield CrawlError(url=url, error=str(exc))
                return
            yield RawResponse(url, resp.status_code, resp.content)
            if resp.status_code != 200:
                yield CrawlError(url=url, error=f"HTTP {resp.status_code}")
                return
            products = parse_alimerka_grid(resp.text, category_code=category.code)
            fresh = [p for p in products if p.sku not in seen_skus]
            if not fresh:
                return
            for product in fresh:
                seen_skus.add(product.sku)
                yield product
            if len(products) < self._page_size:
                return
            start += self._page_size


def _clean_text(value: str) -> str:
    return " ".join(hmod.unescape(value).split())


def _format_name(raw_name: str, brand: str) -> str:
    # Alimerka titles are ALL CAPS ("LECHE SEMIDESNATADA ASTURIANA 1 L."); normalize gently.
    text = raw_name.strip().rstrip(".")
    if text.isupper():
        text = text.capitalize()
    if brand and brand.lower() not in text.lower():
        b_clean = brand.title() if brand.isupper() else brand
        text = f"{text} {b_clean}"
    return text


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
