"""Gadis adapter: the public `gadisline.com` v3 REST API, plain HTTP, no browser needed (ADR 0006).

Gadis resolves each Spanish postal code to a `store-id` via
`GET https://store.gadisline.com/api/v3/stores/postal-codes/delivery`, serves its full category
tree from `GET https://catalog.gadisline.com/api/v3/catalog/categories`, and returns paginated
products per category via `POST https://catalog.gadisline.com/api/v3/catalog/products/search`.
All prices and quantities stay `Decimal` (decision 0016).
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

BASE_WEB_URL = "https://www.gadisline.com"
STORE_API_URL = "https://store.gadisline.com/api/v3/stores/postal-codes/delivery"
CATEGORIES_API_URL = "https://catalog.gadisline.com/api/v3/catalog/categories"
SEARCH_API_URL = "https://catalog.gadisline.com/api/v3/catalog/products/search"
SITE_ID = "56df88f9-479f-4361-891e-e1864dba1ca3"

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")
ROWS_PER_PAGE = 100


def parse_gadis_categories(payload: Mapping[str, Any]) -> list[CategoryObservation]:
    """Flatten Gadis's nested category tree into L1 and L2 `CategoryObservation` entries."""
    out: list[CategoryObservation] = []
    roots = payload.get("categories")
    if not isinstance(roots, list):
        return out
    for root in roots:
        if not isinstance(root, Mapping):
            continue
        root_id = str(root.get("id") or "").strip()
        root_name = str(root.get("name") or "").strip()
        if not root_id or not root_name:
            continue
        out.append(CategoryObservation(code=root_id, name=root_name, parent_code=None))
        nested = root.get("nested_categories")
        children = nested.get("categories") if isinstance(nested, Mapping) else None
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, Mapping):
                continue
            child_id = str(child.get("id") or "").strip()
            child_name = str(child.get("name") or "").strip()
            if not child_id or not child_name:
                continue
            out.append(CategoryObservation(code=child_id, name=child_name, parent_code=root_id))
    return out


def parse_gadis_products(
    payload: Mapping[str, Any], *, category_code: str
) -> list[ProductObservation]:
    """Parse one `catalog/products/search` page into `ProductObservation` entries."""
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []
    products: list[ProductObservation] = []
    for raw in elements:
        if not isinstance(raw, Mapping):
            continue
        obs = _parse_gadis_product(raw, category_code)
        if obs is not None:
            products.append(obs)
    return products


class GadisAdapter:
    """Crawls the Gadisline catalog for one Spanish postal code over plain HTTP."""

    chain_code = "gadis"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        delay: float = 0.4,
        rows_per_page: int = ROWS_PER_PAGE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SmartBasket/0.1)",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "site-id": SITE_ID,
            },
        )
        self._delay = delay
        self._rows_per_page = rows_per_page
        self._requests = 0

    def close(self) -> None:
        if self._owns_client:
            with contextlib.suppress(Exception):
                self._client.close()

    def _pause(self) -> None:
        if self._requests and self._delay:
            time.sleep(self._delay)
        self._requests += 1

    def _resolve_store_id(self, postal_code: str) -> tuple[str | None, RawResponse | CrawlError]:
        self._pause()
        try:
            resp = self._client.get(STORE_API_URL)
        except httpx.HTTPError as exc:
            return None, CrawlError(url=STORE_API_URL, error=str(exc))
        raw = RawResponse(STORE_API_URL, resp.status_code, resp.content)
        if resp.status_code != 200:
            return None, raw
        payload = _json(resp.content)
        elements = payload.get("elements") if isinstance(payload, Mapping) else None
        if isinstance(elements, list):
            for entry in elements:
                if isinstance(entry, Mapping) and str(entry.get("postal_code")) == postal_code:
                    store_id = str(entry.get("store_id") or "").strip()
                    if store_id:
                        return store_id, raw
        return None, raw

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        store_id, store_obs = self._resolve_store_id(zone_code)
        yield store_obs
        if store_id is None:
            if not isinstance(store_obs, CrawlError):
                yield CrawlError(url=STORE_API_URL, error=f"postal code {zone_code} not served")
            return

        headers = {"store-id": store_id}
        self._pause()
        try:
            cat_resp = self._client.get(CATEGORIES_API_URL, headers=headers)
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

        categories = parse_gadis_categories(cat_payload)
        yield from categories
        level_two = [c for c in categories if c.parent_code is not None]
        if max_categories is not None:
            level_two = level_two[:max_categories]

        seen_skus: set[str] = set()
        for category in level_two:
            yield from self._crawl_category(category, headers, seen_skus)

    def _crawl_category(
        self,
        category: CategoryObservation,
        headers: dict[str, str],
        seen_skus: set[str],
    ) -> Iterator[Observation]:
        page_number = 0
        while True:
            url = (
                f"{SEARCH_API_URL}?page_number={page_number}"
                f"&rows_per_page={self._rows_per_page}&keep_request=false"
                "&order_field=relevance&sort_type=asc"
            )
            self._pause()
            try:
                resp = self._client.post(
                    url,
                    headers=headers,
                    json={"minimum_should_match": 1, "category_ids": [category.code]},
                )
            except httpx.HTTPError as exc:
                yield CrawlError(url=url, error=str(exc))
                return
            yield RawResponse(url, resp.status_code, resp.content)
            if resp.status_code != 200:
                yield CrawlError(url=url, error=f"HTTP {resp.status_code}")
                return
            payload = _json(resp.content)
            if payload is None:
                yield CrawlError(url=url, error="invalid JSON")
                return
            products = parse_gadis_products(payload, category_code=category.code)
            for product in products:
                if product.sku not in seen_skus:
                    seen_skus.add(product.sku)
                    yield product
            page_info = payload.get("page")
            total_pages = (
                int(page_info.get("total_pages", 1)) if isinstance(page_info, Mapping) else 1
            )
            page_number += 1
            if not products or page_number >= total_pages:
                return


def _parse_gadis_product(raw: Mapping[str, Any], category_code: str) -> ProductObservation | None:
    sku_raw = raw.get("product_code") or raw.get("id")
    name = _spanish_text(raw.get("commercial_description"))
    price = _decimal(raw.get("price"), PRICE_STEP)
    if sku_raw is None or not name or price is None:
        return None
    sku = str(sku_raw).strip()
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    ppu = _decimal(raw.get("price_kilo_litre"), PER_UNIT_STEP)
    if base_quantity is None and ppu is not None and ppu > 0:
        suffix = (_spanish_text(raw.get("price_kilo_litre_suffix")) or "").lower()
        inferred_unit = None
        if "kilo" in suffix or "kg" in suffix:
            inferred_unit = "kg"
        elif "litro" in suffix or suffix == "l":
            inferred_unit = "l"
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

    slug = raw.get("slug")
    url = f"{BASE_WEB_URL}{slug}" if isinstance(slug, str) and slug.startswith("/") else None
    image_obj = raw.get("image")
    image_url = None
    if isinstance(image_obj, Mapping):
        image_url = image_obj.get("image_thumbnails") or image_obj.get("image")
        if not isinstance(image_url, str) or not image_url.startswith("http"):
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


def _spanish_text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        fallback: str | None = None
        for entry in value:
            if not isinstance(entry, Mapping):
                continue
            text = str(entry.get("value") or "").strip()
            if not text:
                continue
            if str(entry.get("language") or "").upper() == "ES":
                return text
            if fallback is None:
                fallback = text
        return fallback
    return None


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
