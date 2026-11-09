"""Mercadona adapter: the site's public JSON catalog API, no login needed (decision 0006).

The catalog is a category tree (level 1 and level 2 in one response) whose level 2 pages hold
the level 3 sections with the products. Prices are strings and sizes may come in g, ml or cl,
so both are normalized here.
"""

from collections.abc import Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

from smart_basket.ingestion.base import (
    BaseUnit,
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)
from smart_basket.ingestion.http import Fetcher, FetchError

API_URL = "https://tienda.mercadona.es/api"
QUANTITY_STEP = Decimal("0.0001")
PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

# Divisor to reach the base unit of each size format. Unknown formats stay unnormalized.
SIZE_FACTORS: dict[str, tuple[Decimal, BaseUnit]] = {
    "g": (Decimal(1000), "kg"),
    "kg": (Decimal(1), "kg"),
    "ml": (Decimal(1000), "l"),
    "cl": (Decimal(100), "l"),
    "l": (Decimal(1), "l"),
    "ud": (Decimal(1), "ud"),
}


def normalize_size(size: object, size_format: str | None) -> tuple[Decimal | None, BaseUnit | None]:
    """Convert `unit_size` and `size_format` to (`base_quantity`, `base_unit`)."""
    quantity = _decimal(size, QUANTITY_STEP)
    if quantity is None or quantity == 0 or size_format is None:
        return (None, None)
    factor = SIZE_FACTORS.get(size_format.strip().lower())
    if factor is None:
        return (None, None)
    divisor, unit = factor
    return ((quantity / divisor).quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP), unit)


def parse_product(raw: Mapping[str, Any], category_code: str) -> ProductObservation | None:
    """Turn one API product into an observation, or None when it is unpublished or unusable."""
    return parse_product_or_reason(raw, category_code)[0]


def parse_product_or_reason(
    raw: Mapping[str, Any], category_code: str
) -> tuple[ProductObservation | None, str | None]:
    """Parse one product and, when it is skipped, say why.

    An unpublished product is skipped without a reason: it is not an error. A product missing
    its id, its name or a valid price is a parser error the crawl has to report.
    """
    if raw.get("published") is False:
        return (None, None)
    sku = raw.get("id")
    name = raw.get("display_name") or raw.get("name")
    instructions = raw.get("price_instructions") or {}
    price = _decimal(instructions.get("unit_price"), PRICE_STEP)
    if sku is None:
        return (None, "missing id")
    if not name:
        return (None, "missing name")
    if price is None:
        return (None, "missing or invalid price")
    base_quantity, base_unit = normalize_size(
        instructions.get("unit_size"), instructions.get("size_format")
    )
    observation = ProductObservation(
        sku=str(sku),
        name=str(name),
        packaging=raw.get("packaging"),
        url=raw.get("share_url"),
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=_pack_count(instructions),
        price=price,
        price_per_unit=_decimal(instructions.get("bulk_price"), PER_UNIT_STEP),
    )
    return (observation, None)


def parse_tree(payload: Mapping[str, Any]) -> Iterator[CategoryObservation]:
    """Yield level 1 and level 2 categories from the tree response."""
    for top in payload.get("results") or []:
        top_code = top.get("id")
        if top_code is None or not top.get("name"):
            continue
        top_code = str(top_code)
        yield CategoryObservation(code=top_code, name=str(top["name"]), parent_code=None)
        for child in top.get("categories") or []:
            code = child.get("id")
            if code is None or not child.get("name"):
                continue
            yield CategoryObservation(code=str(code), name=str(child["name"]), parent_code=top_code)


def parse_section(
    payload: Mapping[str, Any], parent_code: str, *, page_url: str | None = None
) -> Iterator[CategoryObservation | ProductObservation | CrawlError]:
    """Yield the level 3 sections of a level 2 page and their products.

    With `page_url`, products the parser has to drop are reported as `CrawlError` so the run is
    not complete; unpublished products are skipped silently.
    """
    for section in payload.get("categories") or []:
        code = section.get("id")
        if code is None or not section.get("name"):
            continue
        code = str(code)
        yield CategoryObservation(code=code, name=str(section["name"]), parent_code=parent_code)
        for raw in section.get("products") or []:
            product, reason = parse_product_or_reason(raw, code)
            if product is not None:
                yield product
            elif reason is not None and page_url is not None:
                sku = raw.get("id") if isinstance(raw, Mapping) else None
                yield CrawlError(
                    url=page_url,
                    error=f"product {sku if sku is not None else '?'} skipped: {reason}",
                )


class MercadonaAdapter:
    """Crawls the Mercadona catalog for one warehouse (zone) at a time."""

    chain_code = "mercadona"

    def __init__(self, *, delay: float = 1.5, fetcher: Fetcher | None = None) -> None:
        self._fetcher = fetcher or Fetcher(delay=delay)
        self._owns_fetcher = fetcher is None

    def close(self) -> None:
        if self._owns_fetcher:
            self._fetcher.close()

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        tree_url = _url("/categories/", zone_code)
        response = self._fetcher.get(tree_url)
        yield RawResponse(tree_url, response.status_code, response.content)

        level_two: list[CategoryObservation] = []
        for category in parse_tree(_json(response, tree_url)):
            yield category
            if category.parent_code is not None:
                level_two.append(category)
        if max_categories is not None:
            level_two = level_two[:max_categories]

        for category in level_two:
            url = _url(f"/categories/{category.code}/", zone_code)
            try:
                response = self._fetcher.get(url)
            except FetchError as exc:
                yield CrawlError(url=url, error=exc.error)
                continue
            yield RawResponse(url, response.status_code, response.content)
            try:
                payload = _json(response, url)
                yield from parse_section(payload, parent_code=category.code, page_url=url)
            except FetchError as exc:
                yield CrawlError(url=url, error=exc.error)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                yield CrawlError(url=url, error=f"malformed category: {exc}")


def _url(path: str, warehouse: str) -> str:
    return f"{API_URL}{path}?lang=es&wh={warehouse}"


def _json(response: httpx.Response, url: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FetchError(url, f"invalid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise FetchError(url, "expected a JSON object")
    return payload


def _decimal(value: object, step: Decimal) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation, ValueError:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number.quantize(step, rounding=ROUND_HALF_UP)


def _pack_count(instructions: Mapping[str, Any]) -> int:
    if not instructions.get("is_pack"):
        return 1
    try:
        total = int(instructions.get("total_units"))
    except TypeError, ValueError:
        return 1
    return max(total, 1)
