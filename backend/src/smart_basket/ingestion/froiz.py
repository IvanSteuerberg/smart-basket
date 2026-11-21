"""Froiz adapter: the `servicios.froiz.com` Hydra JSON-LD REST API, no login needed (decision 0006).

Froiz resolves each Spanish postal code through
`GET https://servicios.froiz.com/api/storescoverage/coverage/{code}`, serves its category tree
from `GET /api/categories` and paginates the whole catalog at `GET /api/products?page&size` in
the Hydra collection shape (`hydra:member` also answers flat, as `/api/products/families/{id}`
does). All prices and quantities stay `Decimal` (decision 0016).
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

from smart_basket.ingestion.base import (
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)
from smart_basket.ingestion.dia import parse_dia_size

BASE_WEB_URL = "https://supermercado.froiz.com"
IMAGE_CDN_BASE = "https://imagedelivery.net"
COVERAGE_API_URL = "https://servicios.froiz.com/api/storescoverage/coverage"
CATEGORIES_API_URL = "https://servicios.froiz.com/api/categories"
PRODUCTS_API_URL = "https://servicios.froiz.com/api/products"

PAGE_SIZE = 100
PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

#: Froiz `measurement_unit` spellings, normalized to the base units of the seed.
UNIT_NAMES: dict[str, str] = {
    "kilogramo": "kg",
    "kg": "kg",
    "litro": "l",
    "l": "l",
    "unidad": "ud",
    "ud": "ud",
}


def parse_froiz_categories(payload: Mapping[str, Any]) -> list[CategoryObservation]:
    """Flatten the Hydra category collection into `cat:` roots and their `sec:` children."""
    out: list[CategoryObservation] = []
    members = payload.get("hydra:member")
    if not isinstance(members, list):
        return out
    for category in members:
        if not isinstance(category, Mapping):
            continue
        cat_id = category.get("id")
        cat_name = str(category.get("name") or "").strip()
        if cat_id is None or not cat_name:
            continue
        cat_code = f"cat:{cat_id}"
        out.append(CategoryObservation(code=cat_code, name=cat_name, parent_code=None))
        sections = category.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            sec_id = section.get("id")
            sec_name = str(section.get("name") or "").strip()
            if sec_id is None or not sec_name:
                continue
            out.append(
                CategoryObservation(code=f"sec:{sec_id}", name=sec_name, parent_code=cat_code)
            )
    return out


def parse_froiz_product(raw: Mapping[str, Any]) -> ProductObservation | None:
    """Parse one Froiz product row, or None when it is disabled or unusable."""
    if raw.get("enabled") is False:
        return None
    sku_raw = raw.get("id")
    name_raw = str(raw.get("name") or raw.get("name_suggestion") or "").strip()
    if sku_raw is None or not name_raw:
        return None
    sku = str(sku_raw).strip()

    brand_raw = str(raw.get("brand_name") or "").strip()
    if brand_raw and brand_raw.casefold() not in name_raw.casefold():
        name = f"{name_raw} {brand_raw}"
    else:
        name = name_raw

    offer = raw.get("offer")
    offer_price = None
    if isinstance(offer, Mapping) and offer.get("quantity") in (None, 1, "1"):
        offer_price = _decimal(offer.get("price"), PRICE_STEP)
    order_price = _decimal(raw.get("order_price"), PRICE_STEP)
    base_price = _decimal(raw.get("base_price"), PRICE_STEP)
    price = (
        offer_price
        if offer_price is not None and offer_price > 0
        else order_price
        if order_price is not None and order_price > 0
        else base_price
    )
    if price is None or price <= 0:
        return None

    sec_id = raw.get("section_id")
    cat_id = raw.get("category_id")
    if sec_id is not None:
        category_code = f"sec:{sec_id}"
    elif cat_id is not None:
        category_code = f"cat:{cat_id}"
    else:
        category_code = "cat:0"

    base_quantity, base_unit, pack_count = parse_dia_size(name_raw)
    if base_quantity is None:
        mapped_unit = UNIT_NAMES.get(str(raw.get("measurement_unit") or "").strip().lower())
        per_unit_weight = _decimal(raw.get("per_unit_weight"), PER_UNIT_STEP)
        ratio = _decimal(raw.get("measurement_unit_ratio"), PER_UNIT_STEP)
        if (
            raw.get("fractional") is True
            and per_unit_weight is not None
            and per_unit_weight > 0
            and mapped_unit == "kg"
        ):
            base_quantity, base_unit, pack_count = per_unit_weight, "kg", 1
        elif mapped_unit in ("kg", "l", "ud") and ratio is not None and ratio > 0:
            base_quantity, base_unit, pack_count = ratio, mapped_unit, 1
    if base_quantity is None or base_unit is None or base_quantity <= 0:
        base_quantity, base_unit = None, None

    ppu = None
    if base_quantity is not None and base_unit is not None:
        total = base_quantity * pack_count
        if total > 0:
            ppu = (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)

    slug = str(raw.get("slug") or "").strip()
    url = f"{BASE_WEB_URL}/producto/{slug}" if slug else None
    image = str(raw.get("image") or "").strip()
    if image.startswith("http"):
        image_url: str | None = image
    elif image.startswith("/"):
        image_url = f"{IMAGE_CDN_BASE}{image}"
    else:
        image_url = None

    return ProductObservation(
        sku=sku,
        name=name,
        packaging=None,
        url=url,
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=ppu,
        image_url=image_url,
    )


class FroizAdapter:
    """Crawls the Froiz catalog for one Spanish postal code over plain HTTP."""

    chain_code = "froiz"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        delay: float = 0.25,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SmartBasket/0.1)",
                "Accept": "application/ld+json, application/json",
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
        coverage_url = f"{COVERAGE_API_URL}/{zone_code}"
        self._pause()
        try:
            resp = self._client.get(coverage_url)
        except httpx.HTTPError as exc:
            yield CrawlError(url=coverage_url, error=str(exc))
            return
        yield RawResponse(coverage_url, resp.status_code, resp.content)
        payload = _json(resp.content)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if (
            resp.status_code != 200
            or not isinstance(data, Mapping)
            or data.get("coverage") is not True
        ):
            yield CrawlError(url=coverage_url, error=f"postal code {zone_code} not covered")
            return

        self._pause()
        try:
            cat_resp = self._client.get(CATEGORIES_API_URL)
        except httpx.HTTPError as exc:
            yield CrawlError(url=CATEGORIES_API_URL, error=str(exc))
            return
        yield RawResponse(CATEGORIES_API_URL, cat_resp.status_code, cat_resp.content)
        if cat_resp.status_code != 200:
            yield CrawlError(url=CATEGORIES_API_URL, error=f"HTTP {cat_resp.status_code}")
            return
        cat_payload = _json(cat_resp.content)
        if cat_payload is None:
            yield CrawlError(url=CATEGORIES_API_URL, error="invalid JSON")
            return
        categories = parse_froiz_categories(cat_payload)
        yield from categories
        known_category_codes = {category.code for category in categories}

        seen_skus: set[str] = set()
        page = 1
        # `max_categories` limits the crawl to that many product pages, so `--max-categories 1`
        # stays a quick probe and `collect` marks the run as not complete.
        while max_categories is None or page <= max_categories:
            url = f"{PRODUCTS_API_URL}?page={page}&size={self._page_size}"
            self._pause()
            try:
                prod_resp = self._client.get(url)
            except httpx.HTTPError as exc:
                yield CrawlError(url=url, error=str(exc))
                return
            yield RawResponse(url, prod_resp.status_code, prod_resp.content)
            if prod_resp.status_code != 200:
                yield CrawlError(url=url, error=f"HTTP {prod_resp.status_code}")
                return
            prod_payload = _json(prod_resp.content)
            if prod_payload is None:
                yield CrawlError(url=url, error="invalid JSON")
                return
            rows, total_pages = _products_page(prod_payload.get("hydra:member"))
            for row in rows:
                yield from _product_categories(row, known_category_codes)
                product = parse_froiz_product(row)
                if product is not None and product.sku not in seen_skus:
                    seen_skus.add(product.sku)
                    yield product
            page += 1
            if not rows or (total_pages is not None and page > total_pages):
                return


def _products_page(members: Any) -> tuple[list[Mapping[str, Any]], int | None]:
    """The product rows of one Hydra answer, and its page count when it carries any.

    `/api/products` wraps the page in a six-element `hydra:member` whose first element is the
    product list and whose last element holds the pagination metadata; the family and section
    endpoints answer a flat product list instead.
    """
    if not isinstance(members, list):
        return [], None
    if members and isinstance(members[0], list):
        rows = [row for row in members[0] if isinstance(row, Mapping)]
        total_pages = None
        if len(members) >= 6 and isinstance(members[5], Mapping):
            total_pages = _int(members[5].get("totalPages"))
        return rows, total_pages
    return [row for row in members if isinstance(row, Mapping)], None


def _product_categories(
    raw: Mapping[str, Any], known_category_codes: set[str]
) -> Iterator[CategoryObservation]:
    """The category or section a product names but the category tree did not list."""
    cat_id = raw.get("category_id")
    cat_name = str(raw.get("category_name") or "").strip()
    if cat_id is not None and cat_name and f"cat:{cat_id}" not in known_category_codes:
        known_category_codes.add(f"cat:{cat_id}")
        yield CategoryObservation(code=f"cat:{cat_id}", name=cat_name, parent_code=None)
    sec_id = raw.get("section_id")
    sec_name = str(raw.get("section_name") or "").strip()
    if sec_id is None or not sec_name or f"sec:{sec_id}" in known_category_codes:
        return
    parent_code = f"cat:{cat_id}" if cat_id is not None else None
    known_category_codes.add(f"sec:{sec_id}")
    yield CategoryObservation(code=f"sec:{sec_id}", name=sec_name, parent_code=parent_code)


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _json(body: bytes) -> Mapping[str, Any] | None:
    try:
        data = json.loads(body)
    except TypeError, ValueError:
        return None
    return data if isinstance(data, Mapping) else None


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
