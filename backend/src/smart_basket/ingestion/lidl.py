"""Lidl adapter: the weekly `lidl.es` flyer JSON, plain HTTP, no browser needed (ADR 0006).

Lidl publishes its weekly folletos under `https://www.lidl.es/l/folletos/<slug>`; the folletos
index page links them and each one is served as one JSON document from the leaflets endpoint.
The flyer payload mixes structured products with per-page `keyWords` OCR lines, where prices
appear in cents (`348 259` = regular `3.48 €`, offer `2.59 €`). Only private-label staples
keep the controlled-staples retention (Option B): everything else is a live-sync flyer item.
Prices and quantities stay `Decimal` (decision 0016).
"""

from __future__ import annotations

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

FOLLETOS_INDEX_URL = (
    "https://www.lidl.es/c/descubre-nuevas-ofertas-cada-semana-folletos-lidl/s10087402"
)
FLYER_API_URL = "https://endpoints.leaflets.schwarz/v4/flyer"
BASE_WEB_URL = "https://www.lidl.es"

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

_FLYER_SLUG_RE = re.compile(r"https://www\.lidl\.es/l/folletos/([^/\"'\s?#]+)")
_FOOD_SLUG_MARKERS = ("alimentacion", "navidad", "super")
_CENTS_RE = re.compile(r"\d{3,4}")
_PERCENT_RE = re.compile(r"-\d+%")
_ORDINAL_RE = re.compile(r"\d+ª")

# Flyer boilerplate that carries no product: meeting one of these tokens discards the name
# accumulated so far, so page banners never bleed into the next item's name. `deluxe` and
# `limitado` stay out on purpose: they mark the item itself as a temporary product.
_NOISE_TOKENS = frozenset(
    {
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
        "somos",
        "súper",
        "super",
        "baja",
        "precios",
        "bajadas",
        "precio",
        "productos",
        "producto",
        "lidl",
        "plus",
        "consulta",
        "condiciones",
        "artículos",
        "limitados",
        "categoría",
        "categoria",
        "origen",
        "granel",
        "€",
        "2ª",
        "3ª",
    }
)


def parse_lidl_flyer_slugs(index_html: str) -> list[str]:
    """Extract flyer slugs from the folletos index, food flyers first, order preserved.

    Slugs with `alimentacion`, `navidad` or `super` in them carry groceries; when none
    matches (a slow week, a new slug scheme) every slug found is returned instead.
    """
    slugs: list[str] = []
    for slug in _FLYER_SLUG_RE.findall(index_html):
        if slug and slug not in slugs:
            slugs.append(slug)
    food = [
        slug for slug in slugs if any(marker in slug.casefold() for marker in _FOOD_SLUG_MARKERS)
    ]
    return food or slugs


def parse_lidl_flyer(
    payload: Mapping[str, Any], *, flyer_url: str | None = None
) -> tuple[list[CategoryObservation], list[ProductObservation]]:
    """Parse one flyer JSON document into its category pair and its products.

    The categories are the folletos root plus one L2 per flyer; the products come from the
    structured `products` mapping first and from the per-page `keyWords` OCR lines second,
    deduplicated by sku with the structured sightings winning.
    """
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        flyer = payload
    valid_from = _date_text(flyer.get("offerStartDate") or flyer.get("startDate"))
    valid_until = _date_text(flyer.get("offerEndDate") or flyer.get("endDate"))
    flyer_title = str(flyer.get("name") or flyer.get("title") or "Folleto Lidl").strip()
    if not flyer_title:
        flyer_title = "Folleto Lidl"
    category_code = f"folletos/{_slug(flyer_title)}"
    categories = [
        CategoryObservation(code="folletos", name="Folletos Lidl", parent_code=None),
        CategoryObservation(code=category_code, name=flyer_title, parent_code="folletos"),
    ]

    products: list[ProductObservation] = []
    seen_skus: set[str] = set()
    for raw in _structured_product_rows(flyer.get("products")):
        observation = _parse_lidl_structured_product(
            raw, category_code=category_code, valid_from=valid_from, valid_until=valid_until
        )
        if observation is not None and observation.sku not in seen_skus:
            seen_skus.add(observation.sku)
            products.append(observation)
    pages = flyer.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, Mapping):
                continue
            for observation in parse_lidl_page_keywords(
                page,
                category_code=category_code,
                flyer_url=flyer_url,
                valid_from=valid_from,
                valid_until=valid_until,
            ):
                if observation.sku not in seen_skus:
                    seen_skus.add(observation.sku)
                    products.append(observation)
    return categories, products


def parse_lidl_page_keywords(
    page: Mapping[str, Any],
    *,
    category_code: str,
    flyer_url: str | None,
    valid_from: str | None,
    valid_until: str | None,
) -> list[ProductObservation]:
    """Extract `(name, regular, offer)` items from one page's `keyWords` OCR line.

    Lidl Spain writes flyer prices in cents as 3-4 bare digits right after each product
    name: `Alesto Nuez Natural 1175 945` is 11.75 € down to 9.45 €, and `Hamburguesa Vacuno
    299 €` is a single 2.99 € offer. Boilerplate (day names, Lidl Plus banners, origin lists)
    breaks whatever name was accumulating, and every item on a page that mentions limited
    editions or Deluxe is flagged temporary.
    """
    keywords = str(page.get("keyWords") or "")
    if not keywords.strip():
        return []
    page_low = keywords.casefold()
    page_temporary = "limitado" in page_low or "deluxe" in page_low
    image_url = _http_image(page.get("image"))

    products: list[ProductObservation] = []
    pending: list[str] = []
    tokens = keywords.split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_noise(token):
            pending.clear()
            index += 1
            continue
        if _CENTS_RE.fullmatch(token):
            regular, offer, consumed = _read_cents_prices(tokens, index)
            index += consumed
            name = " ".join(pending)
            pending.clear()
            if name and offer is not None:
                products.append(
                    _lidl_observation(
                        name,
                        regular,
                        offer,
                        category_code=category_code,
                        flyer_url=flyer_url,
                        valid_from=valid_from,
                        valid_until=valid_until,
                        image_url=image_url,
                        page_temporary=page_temporary,
                    )
                )
            continue
        pending.append(token)
        index += 1
    return products


def _read_cents_prices(tokens: list[str], index: int) -> tuple[Decimal | None, Decimal, int]:
    """Read one price group at `index`: two amounts are (regular, offer), one is the offer."""
    if index + 1 < len(tokens) and _CENTS_RE.fullmatch(tokens[index + 1]):
        return _cents(tokens[index]), _cents(tokens[index + 1]), 2
    return None, _cents(tokens[index]), 1


class LidlAdapter:
    """Crawls the weekly Lidl Spain folletos for the chain-wide zone over plain HTTP."""

    chain_code = "lidl"
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
            response = self._fetcher.get(FOLLETOS_INDEX_URL)
        except FetchError as exc:
            yield CrawlError(url=FOLLETOS_INDEX_URL, error=exc.error)
            return
        yield RawResponse(FOLLETOS_INDEX_URL, response.status_code, response.content)
        if response.status_code != 200:
            yield CrawlError(url=FOLLETOS_INDEX_URL, error=f"HTTP {response.status_code}")
            return

        slugs = parse_lidl_flyer_slugs(response.text)
        if not slugs:
            yield CrawlError(url=FOLLETOS_INDEX_URL, error="no flyer links found")
            return
        if max_categories is not None:
            slugs = slugs[:max_categories]

        seen_skus: set[str] = set()
        for slug in slugs:
            flyer_url = f"{BASE_WEB_URL}/l/folletos/{slug}"
            api_url = f"{FLYER_API_URL}?slug={slug}"
            try:
                flyer_response = self._fetcher.get(api_url)
            except FetchError as exc:
                yield CrawlError(url=api_url, error=exc.error)
                continue
            yield RawResponse(api_url, flyer_response.status_code, flyer_response.content)
            if flyer_response.status_code != 200:
                yield CrawlError(url=api_url, error=f"HTTP {flyer_response.status_code}")
                continue
            try:
                payload = flyer_response.json()
            except ValueError:
                yield CrawlError(url=api_url, error="invalid JSON")
                continue
            if not isinstance(payload, Mapping):
                yield CrawlError(url=api_url, error="expected a JSON object")
                continue
            categories, products = parse_lidl_flyer(payload, flyer_url=flyer_url)
            yield from categories
            for product in products:
                if product.sku not in seen_skus:
                    seen_skus.add(product.sku)
                    yield product


def _structured_product_rows(value: object) -> list[Mapping[str, Any]]:
    """The flyer's `products` arrive as a mapping keyed by product id or as a list."""
    if isinstance(value, Mapping):
        return [row for row in value.values() if isinstance(row, Mapping)]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _parse_lidl_structured_product(
    raw: Mapping[str, Any],
    *,
    category_code: str,
    valid_from: str | None,
    valid_until: str | None,
) -> ProductObservation | None:
    product_id = str(raw.get("productId") or raw.get("id") or "").strip()
    name = str(raw.get("title") or "").strip()
    price = _decimal(raw.get("price"), PRICE_STEP)
    if not product_id or not name or price is None:
        return None
    regular = _decimal(raw.get("strokePrice") or raw.get("oldPrice"), PRICE_STEP)
    url_value = raw.get("url")
    url: str | None
    if isinstance(url_value, str) and url_value.startswith("http"):
        url = url_value
    elif isinstance(url_value, str) and url_value.startswith("/"):
        url = f"{BASE_WEB_URL}{url_value}"
    else:
        url = None
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    price_per_unit: Decimal | None = None
    if base_quantity is not None and base_unit is not None and base_quantity * pack_count > 0:
        price_per_unit = (price / (base_quantity * pack_count)).quantize(
            PER_UNIT_STEP, rounding=ROUND_HALF_UP
        )
    return ProductObservation(
        sku=f"lidl-{product_id}",
        name=name,
        packaging=None,
        url=url,
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=price_per_unit,
        image_url=_http_image(raw.get("image")),
        regular_price=regular,
        is_temporary=_temporary_name(name),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _lidl_observation(
    name: str,
    regular: Decimal | None,
    offer: Decimal,
    *,
    category_code: str,
    flyer_url: str | None,
    valid_from: str | None,
    valid_until: str | None,
    image_url: str | None,
    page_temporary: bool,
) -> ProductObservation:
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    price_per_unit: Decimal | None = None
    if base_quantity is not None and base_unit is not None and base_quantity * pack_count > 0:
        price_per_unit = (offer / (base_quantity * pack_count)).quantize(
            PER_UNIT_STEP, rounding=ROUND_HALF_UP
        )
    return ProductObservation(
        sku=f"lidl-{_slug(name)}",
        name=name,
        packaging=None,
        url=flyer_url,
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=offer,
        price_per_unit=price_per_unit,
        image_url=image_url,
        regular_price=regular,
        is_temporary=page_temporary or _temporary_name(name),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _is_noise(token: str) -> bool:
    low = token.casefold().strip("¡!.,:;¿?")
    if low in _NOISE_TOKENS:
        return True
    return bool(_PERCENT_RE.fullmatch(token) or _ORDINAL_RE.fullmatch(token))


def _temporary_name(name: str) -> bool:
    low = name.casefold()
    return "limitado" in low or "deluxe" in low


def _cents(token: str) -> Decimal:
    return (Decimal(token) / Decimal(100)).quantize(PRICE_STEP, rounding=ROUND_HALF_UP)


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:10] or None


def _http_image(value: object) -> str | None:
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


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
