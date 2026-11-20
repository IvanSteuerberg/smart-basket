"""Aldi adapter: the public Algolia peninsula index and the weekly offers (ADR 0006).

Aldi Spain exposes its whole assortment through one public Algolia index
(`an_prd_es_es_pen_products2`): the `hierarchicalCategories.lvl0`/`lvl1` facets carry the
category tree and a facet-filtered `query` returns the products of each leaf, so no browser and
no zone are needed and the chain uses one chain-wide zone. The weekly offers come from
`GET /api/offer/es/current`, whose `algoliaDataMap` holds priced products that the index does
not list yet. All prices and quantities stay `Decimal` (decision 0016); the parsers are pure and
are exercised with synthetic payloads (NFR-07).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import unicodedata
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

ALGOLIA_APP_ID = "L9KNU74IO7"
ALGOLIA_API_KEY = "83df5acd172c42ab174afa4583232b5d"
ALGOLIA_INDEX = "an_prd_es_es_pen_products2"
ALGOLIA_QUERY_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
OFFERS_CURRENT_URL = "https://www.aldi.es/api/offer/es/current"
BASE_WEB_URL = "https://www.aldi.es"
HITS_PER_PAGE = 100

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

#: Products without a category in `hierarchicalCategories.lvl1` land in a synthetic "Otros" node.
FALLBACK_L1_CODE = "lvl0:otros"
FALLBACK_L2_CODE = "lvl1:otros/general"

_PRICE_FILTER = "currentPrice.priceValue > 0"
_FACETS_QUERY: dict[str, Any] = {
    "query": "",
    "hitsPerPage": 0,
    "numericFilters": [_PRICE_FILTER],
    "facets": [
        "hierarchicalCategories.lvl0",
        "hierarchicalCategories.lvl1",
        "categoryIDs",
    ],
}
_KILO_SCALES = frozenset({"kg", "kilo", "kilogramo"})
_LITRE_SCALES = frozenset({"l", "litro"})
_UNIT_SCALES = frozenset({"ud", "unidad", "lavado"})
_HUNDRED_GRAM_SCALES = frozenset({"100 g", "100g", "100 gr"})
_HUNDRED_ML_SCALES = frozenset({"100 ml", "100ml"})
_BRAND_PREFIX = "Marcas >"

logger = logging.getLogger(__name__)


def parse_aldi_categories(payload: Mapping[str, Any]) -> list[CategoryObservation]:
    """Build the L1/L2 tree from the Algolia facet counts of one facets query.

    `hierarchicalCategories.lvl0` lists the roots and `hierarchicalCategories.lvl1` lists
    `"Parent > Child"` leaves. A synthetic `Otros`/`General` pair is always added so a product
    or weekly offer without a known category still has somewhere to go.
    """
    facets = payload.get("facets")
    facets = facets if isinstance(facets, Mapping) else {}
    level_zero = _facet_names(facets.get("hierarchicalCategories.lvl0"))
    level_one = _facet_names(facets.get("hierarchicalCategories.lvl1"))

    roots: list[str] = []
    pairs: list[tuple[str, str]] = []
    for name in level_zero:
        if name not in roots:
            roots.append(name)
    for value in level_one:
        parent, child = _split_lvl1(value)
        if parent is None:
            if value not in roots:
                roots.append(value)
            continue
        if parent not in roots:
            roots.append(parent)
        pairs.append((parent, child))

    out: list[CategoryObservation] = []
    seen: set[str] = set()

    def _add(code: str, name: str, parent_code: str | None) -> None:
        if code in seen:
            return
        seen.add(code)
        out.append(CategoryObservation(code=code, name=name, parent_code=parent_code))

    for name in roots:
        _add(f"lvl0:{_slug(name)}", name, None)
    for parent, child in pairs:
        _add(f"lvl1:{_slug(parent)}/{_slug(child)}", child, f"lvl0:{_slug(parent)}")
    _add(FALLBACK_L1_CODE, "Otros", None)
    _add(FALLBACK_L2_CODE, "General", FALLBACK_L1_CODE)
    return out


def parse_aldi_products(
    payload: Mapping[str, Any],
    *,
    default_category_code: str = FALLBACK_L2_CODE,
    valid_category_codes: set[str] | None = None,
) -> list[ProductObservation]:
    """Parse the `hits` of one Algolia page, dropping unpriced or unavailable entries."""
    hits = payload.get("hits")
    if not isinstance(hits, list):
        return []
    products: list[ProductObservation] = []
    for raw in hits:
        if not isinstance(raw, Mapping):
            continue
        observation = parse_aldi_product(
            raw,
            default_category_code=default_category_code,
            valid_category_codes=valid_category_codes,
        )
        if observation is not None:
            products.append(observation)
    return products


def parse_aldi_product(
    raw: Mapping[str, Any],
    *,
    default_category_code: str = FALLBACK_L2_CODE,
    valid_category_codes: set[str] | None = None,
) -> ProductObservation | None:
    """Turn one Algolia hit (or weekly-offer entry) into a `ProductObservation`."""
    if raw.get("isRecall") is True or raw.get("isAvailable") is False:
        return None
    sku = str(raw.get("objectID") or "").strip()
    name_raw = str(raw.get("name") or "").strip()
    current_price = raw.get("currentPrice")
    if not sku or not name_raw or not isinstance(current_price, Mapping):
        return None
    price = _decimal(current_price.get("priceValue"), PRICE_STEP)
    if price is None or price <= 0:
        return None

    brand_raw = str(raw.get("brandName") or "").replace("®", "").replace("™", "").strip()
    if brand_raw and brand_raw.casefold() not in name_raw.casefold():
        name = f"{name_raw} {brand_raw}"
    else:
        name = name_raw

    category_code = _resolve_category_code(raw, default_category_code, valid_category_codes)

    sales_unit = str(raw.get("salesUnit") or "").strip() or None
    ppu, scale_unit = _base_price(current_price.get("basePrice"))
    base_quantity, base_unit, pack_count = parse_dia_size(sales_unit or name_raw)
    if base_quantity is None and ppu is not None and ppu > 0 and scale_unit is not None:
        inferred_qty = (price / ppu).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if inferred_qty > 0:
            base_quantity, base_unit = inferred_qty, scale_unit
    if base_quantity is None or base_unit is None or base_quantity <= 0:
        base_quantity, base_unit = None, None
    if ppu is None and base_quantity is not None and base_unit is not None:
        total = base_quantity * pack_count
        if total > 0:
            ppu = (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)

    slug = str(raw.get("productSlug") or "").strip()
    return ProductObservation(
        sku=sku,
        name=name,
        packaging=None,
        url=f"{BASE_WEB_URL}/productos/{slug}.html" if slug else None,
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=ppu,
        image_url=_primary_asset(raw.get("assets")),
    )


class AldiAdapter:
    """Crawls the Aldi peninsula catalog through its public Algolia index and offers API."""

    chain_code = "aldi"
    zone_kind = "chain"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        delay: float = 0.2,
        hits_per_page: int = HITS_PER_PAGE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SmartBasket/0.1)",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-algolia-application-id": ALGOLIA_APP_ID,
                "x-algolia-api-key": ALGOLIA_API_KEY,
            },
        )
        self._delay = delay
        self._hits_per_page = hits_per_page
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
        """Yield the facets, the category tree, every leaf listing and, in full runs, the offers.

        `zone_code` is accepted for the `ChainAdapter` contract but ignored: the index is the
        peninsula catalog, so every zone sees the same assortment.
        """
        self._pause()
        try:
            facets_resp = self._client.post(ALGOLIA_QUERY_URL, json=_FACETS_QUERY)
        except httpx.HTTPError as exc:
            yield CrawlError(url=ALGOLIA_QUERY_URL, error=str(exc))
            return
        yield RawResponse(ALGOLIA_QUERY_URL, facets_resp.status_code, facets_resp.content)
        if facets_resp.status_code != 200:
            yield CrawlError(url=ALGOLIA_QUERY_URL, error=f"HTTP {facets_resp.status_code}")
            return
        facets_payload = _json(facets_resp.content)
        if facets_payload is None:
            yield CrawlError(url=ALGOLIA_QUERY_URL, error="invalid JSON")
            return

        categories = parse_aldi_categories(facets_payload)
        yield from categories
        valid_codes = {c.code for c in categories if c.parent_code is not None}

        listings = _lvl1_listings(facets_payload)
        if max_categories is not None:
            listings = listings[:max_categories]

        seen_skus: set[str] = set()
        for lvl1_value, category_code in listings:
            yield from self._crawl_listing(
                filter_value=f"hierarchicalCategories.lvl1:{lvl1_value}",
                category_label=lvl1_value,
                default_category_code=category_code,
                valid_category_codes=valid_codes,
                seen_skus=seen_skus,
            )

        if max_categories is None:
            yield from self._crawl_orphan_categories(facets_payload, valid_codes, seen_skus)
            yield from self._crawl_offers(valid_codes, seen_skus)

    def _crawl_listing(
        self,
        *,
        filter_value: str,
        category_label: str,
        default_category_code: str,
        valid_category_codes: set[str],
        seen_skus: set[str],
    ) -> Iterator[Observation]:
        page = 0
        while True:
            url = f"{ALGOLIA_QUERY_URL}?category={_slug(category_label)}&page={page}"
            self._pause()
            try:
                resp = self._client.post(
                    url,
                    json={
                        "query": "",
                        "page": page,
                        "hitsPerPage": self._hits_per_page,
                        "numericFilters": [_PRICE_FILTER],
                        "facetFilters": [[filter_value]],
                    },
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
            for product in parse_aldi_products(
                payload,
                default_category_code=default_category_code,
                valid_category_codes=valid_category_codes,
            ):
                if product.sku not in seen_skus:
                    seen_skus.add(product.sku)
                    yield product
            hits = payload.get("hits")
            page += 1
            if not isinstance(hits, list) or not hits or page >= _int(payload.get("nbPages"), 1):
                return

    def _crawl_orphan_categories(
        self,
        payload: Mapping[str, Any],
        valid_category_codes: set[str],
        seen_skus: set[str],
    ) -> Iterator[Observation]:
        """Sweep the `categoryIDs` facets for products the L1 listings do not surface."""
        facets = payload.get("facets")
        category_ids = facets.get("categoryIDs") if isinstance(facets, Mapping) else None
        if not isinstance(category_ids, Mapping):
            return
        for raw_id in category_ids:
            category_id = str(raw_id).strip()
            if not category_id:
                continue
            yield from self._crawl_listing(
                filter_value=f"categoryIDs:{category_id}",
                category_label=category_id,
                default_category_code=FALLBACK_L2_CODE,
                valid_category_codes=valid_category_codes,
                seen_skus=seen_skus,
            )

    def _crawl_offers(
        self, valid_category_codes: set[str], seen_skus: set[str]
    ) -> Iterator[Observation]:
        """Merge the weekly offers; a broken offers API never fails an otherwise good crawl."""
        self._pause()
        try:
            resp = self._client.get(OFFERS_CURRENT_URL)
        except httpx.HTTPError as exc:
            logger.warning("aldi offers API unavailable: %s", exc)
            return
        if resp.status_code != 200:
            logger.warning("aldi offers API returned HTTP %s", resp.status_code)
            return
        payload = _json(resp.content)
        if payload is None:
            logger.warning("aldi offers API returned invalid JSON")
            return
        yield RawResponse(OFFERS_CURRENT_URL, resp.status_code, resp.content)
        offers = payload.get("algoliaDataMap")
        if not isinstance(offers, Mapping):
            return
        for object_id, raw in offers.items():
            if not isinstance(raw, Mapping):
                continue
            entry = dict(raw)
            if not str(entry.get("objectID") or "").strip():
                entry["objectID"] = str(object_id)
            product = parse_aldi_product(
                entry,
                default_category_code=FALLBACK_L2_CODE,
                valid_category_codes=valid_category_codes,
            )
            if product is None or product.sku in seen_skus:
                continue
            seen_skus.add(product.sku)
            yield product


def _facet_names(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return [str(key).strip() for key in value if str(key).strip()]


def _lvl1_listings(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return each `(facet value, category code)` pair of the L2 leaves, in facet order."""
    facets = payload.get("facets")
    level_one = facets.get("hierarchicalCategories.lvl1") if isinstance(facets, Mapping) else None
    listings: list[tuple[str, str]] = []
    for value in _facet_names(level_one):
        parent, child = _split_lvl1(value)
        if parent is None:
            continue
        listings.append((value, f"lvl1:{_slug(parent)}/{_slug(child)}"))
    return listings


def _resolve_category_code(
    raw: Mapping[str, Any],
    default_category_code: str,
    valid_category_codes: set[str] | None,
) -> str:
    """Prefer the product's own L2, ignoring Aldi's synthetic `Marcas > ...` marketing branch."""
    hierarchical = raw.get("hierarchicalCategories")
    level_one = hierarchical.get("lvl1") if isinstance(hierarchical, Mapping) else None
    if not isinstance(level_one, list):
        return default_category_code
    chosen = _first_non_brand(level_one)
    if chosen is None:
        return default_category_code
    parent, child = _split_lvl1(chosen)
    if parent is None:
        return default_category_code
    code = f"lvl1:{_slug(parent)}/{_slug(child)}"
    if valid_category_codes is None or code in valid_category_codes:
        return code
    return default_category_code


def _first_non_brand(values: list[Any]) -> str | None:
    fallback: str | None = None
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text:
            continue
        if fallback is None:
            fallback = text
        if not text.startswith(_BRAND_PREFIX):
            return text
    return fallback


def _base_price(base_price: object) -> tuple[Decimal | None, str | None]:
    """Read Aldi's `basePrice` list into a per-unit price and the unit it is quoted in."""
    if not isinstance(base_price, list):
        return None, None
    for entry in base_price:
        if not isinstance(entry, Mapping):
            continue
        value = _decimal(entry.get("basePriceValue"), PER_UNIT_STEP)
        scale = str(entry.get("basePriceScale") or "").strip().lower()
        if scale in _KILO_SCALES:
            return value, "kg"
        if scale in _LITRE_SCALES:
            return value, "l"
        if scale in _UNIT_SCALES:
            return value, "ud"
        if scale in _HUNDRED_GRAM_SCALES:
            per_kilo = (value * 10).quantize(PER_UNIT_STEP) if value else None
            return per_kilo, "kg"
        if scale in _HUNDRED_ML_SCALES:
            per_litre = (value * 10).quantize(PER_UNIT_STEP) if value else None
            return per_litre, "l"
    return None, None


def _primary_asset(assets: object) -> str | None:
    if not isinstance(assets, list):
        return None
    fallback: str | None = None
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        url = asset.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        if asset.get("type") == "primary":
            return url
        if fallback is None:
            fallback = url
    return fallback


def _split_lvl1(value: str) -> tuple[str | None, str]:
    """Split `"Parent > Child"`; a facet value without a child has no parent either."""
    parent, _, child = value.partition(" > ")
    parent, child = parent.strip(), child.strip()
    if not parent or not child:
        return None, value
    return parent, child


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return text or "sin-nombre"


def _int(value: object, default: int) -> int:
    if isinstance(value, str | int | float):
        try:
            return int(value)
        except TypeError, ValueError:
            return default
    return default


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
