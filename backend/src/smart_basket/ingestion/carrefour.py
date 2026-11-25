"""Carrefour adapter: public server-rendered catalog via RadarSuper (decision 0006, NFR-07).

Direct automated requests to `carrefour.es/supermercado` hit a Cloudflare 403 block with no
solvable interactive challenge (verified in T1 on 2026-11-21). RadarSuper (`radarsuper.com`)
publishes Carrefour Spain's daily-updated online catalog across 152 leaf categories as plain
server-rendered HTML (`/carrefour/c/<slug>` and `/pagina/<n>`), explicitly allowed by its
`robots.txt` (`Allow: /`; `/api/`, `/cuenta/`, `/buscar?` and `/alternativas/` are disallowed
and never touched by this adapter).

All prices and quantities stay `Decimal` (decision 0016).
"""

from __future__ import annotations

import contextlib
import json
import re
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

BASE_URL = "https://radarsuper.com"
INDEX_URL = f"{BASE_URL}/carrefour"
USER_AGENT = "SmartBasket-Academic-Research/1.0"

PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

#: Category IDs 1..26 on RadarSuper are level-1 parents; IDs >= 27 are the 152 leaf categories.
MIN_LEAF_CATEGORY_ID = 27
MAX_PAGES_PER_CATEGORY = 60

_RSC_ITEM_RE = re.compile(r'\\?"item\\?":(\{[^\}]+?\})')
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_radarsuper_category_links(html: str, chain_slug: str) -> list[tuple[str, str]]:
    """Extract unique leaf category `(slug_with_id, path)` pairs from `/<chain_slug>` HTML."""
    pattern = re.compile(rf'href="(/{re.escape(chain_slug)}/c/([^"?#]+)-(\d+))"')
    found: dict[int, tuple[str, str]] = {}
    for path, slug, id_str in pattern.findall(html):
        cat_id = int(id_str)
        if cat_id < MIN_LEAF_CATEGORY_ID:
            continue
        found.setdefault(cat_id, (f"{slug}-{cat_id}", path))
    return [found[cid] for cid in sorted(found)]


def parse_carrefour_category_links(html: str) -> list[tuple[str, str]]:
    """Extract unique leaf category `(slug_with_id, path)` pairs from `/carrefour` HTML."""
    return parse_radarsuper_category_links(html, "carrefour")


def _humanize_slug(slug_with_id: str) -> str:
    base = re.sub(r"-\d+$", "", slug_with_id).replace("-", " ").strip()
    return (base[0].upper() + base[1:]) if base else slug_with_id


def parse_category_title(html: str, fallback_slug: str) -> str:
    """Read the page `<h1>` title when present, falling back to the humanized slug."""
    match = _H1_RE.search(html)
    if match:
        title = " ".join(_TAG_RE.sub(" ", match.group(1)).split()).strip()
        title = re.sub(r"\s+en\s+(?:Carrefour|Alcampo).*$", "", title, flags=re.IGNORECASE).strip()
        if title:
            return title
    return _humanize_slug(fallback_slug)


def parse_radarsuper_rsc_items(html: str, chain_slug: str) -> list[dict[str, Any]]:
    """Extract structured product dicts from Next.js RSC `\"item\":{...}` payloads."""
    prefix = f"/{chain_slug}/p/"
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_obj in _RSC_ITEM_RE.findall(html):
        unescaped = raw_obj.replace('\\"', '"')
        try:
            obj = json.loads(unescaped)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        key = str(obj.get("key") or obj.get("url") or "").strip()
        if not key or prefix not in key or key in seen_keys:
            continue
        seen_keys.add(key)
        items.append(obj)
    return items


def parse_carrefour_rsc_items(html: str) -> list[dict[str, Any]]:
    """Extract Carrefour product dicts from Next.js RSC `\"item\":{...}` payloads."""
    return parse_radarsuper_rsc_items(html, "carrefour")


def has_next_page(html: str, category_path: str, current_page: int) -> bool:
    """Whether the HTML contains a pagination link to `current_page + 1`."""
    target = f"{category_path}/pagina/{current_page + 1}"
    return target in html


def _normalize_size(
    raw_size: Any, raw_unit: Any, name: str
) -> tuple[str | None, Decimal | None, int]:
    """Return `(base_unit, per-unit size, pack count)` for one RadarSuper item.

    A multipack expression in the name (`"12 x 100 g"`) wins for the per-unit size and the pack
    count, because the raw `size` of a multipack may already be the total; a name that declares
    only the count (`"Actimel pack 6"`) keeps the raw per-unit size and the parsed pack.
    """
    name_qty, name_unit, name_pack = parse_dia_size(name)
    unit_text = str(raw_unit or "").strip().lower()
    size_dec: Decimal | None = None
    if raw_size is not None and str(raw_size).strip():
        with contextlib.suppress(InvalidOperation):
            val = Decimal(str(raw_size).replace(",", "."))
            if val > 0:
                size_dec = val
    if size_dec is not None and unit_text:
        if unit_text in ("kg", "kilo", "kilos", "kilogramo", "kilogramos"):
            unit, qty = "kg", size_dec.quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)
        elif unit_text in ("g", "gr", "gramo", "gramos"):
            kg_qty = (size_dec / Decimal("1000")).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)
            unit, qty = "kg", kg_qty
        elif unit_text in ("l", "lt", "litro", "litros"):
            unit, qty = "l", size_dec.quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)
        elif unit_text == "cl":
            unit, qty = (
                "l",
                (size_dec / Decimal("100")).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP),
            )
        elif unit_text == "ml":
            unit, qty = (
                "l",
                (size_dec / Decimal("1000")).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP),
            )
        elif unit_text in ("ud", "uds", "u", "unidad", "unidades", "lavado", "lavados"):
            unit, qty = "ud", size_dec.quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)
        else:
            unit, qty = name_unit, name_qty
        if name_pack > 1 and name_qty is not None and name_unit in ("kg", "l"):
            return name_unit, name_qty, name_pack
        return unit, qty, max(name_pack, 1)
    return name_unit, name_qty, max(name_pack, 1)


def parse_radarsuper_product(
    raw: Mapping[str, Any], *, category_code: str, chain_slug: str
) -> ProductObservation | None:
    """Parse one RadarSuper product item into a `ProductObservation`."""
    key = str(raw.get("key") or raw.get("url") or "").strip()
    name = " ".join(str(raw.get("name") or "").split()).strip()
    if not key or not name:
        return None
    sku = key.removeprefix(f"/{chain_slug}/p/").strip("/")
    if not sku:
        return None
    raw_price = raw.get("price")
    if raw_price is None:
        return None
    try:
        price = Decimal(str(raw_price).replace(",", ".")).quantize(
            PRICE_STEP, rounding=ROUND_HALF_UP
        )
    except InvalidOperation:
        return None
    if price <= 0:
        return None

    base_unit, unit_qty, pack_count = _normalize_size(raw.get("size"), raw.get("unit"), name)
    unit_price: Decimal | None = None
    if unit_qty is not None and unit_qty * pack_count > 0:
        unit_price = (price / (unit_qty * pack_count)).quantize(
            PER_UNIT_STEP, rounding=ROUND_HALF_UP
        )

    img = str(raw.get("image") or "").strip()
    image_url = f"{BASE_URL}{img}" if img.startswith("/") else (img or None)
    url_val = str(raw.get("url") or key).strip()
    source_url = f"{BASE_URL}{url_val}" if url_val.startswith("/") else url_val

    return ProductObservation(
        sku=sku[:200],
        name=name,
        packaging=None,
        url=source_url,
        category_code=category_code,
        base_quantity=unit_qty,
        base_unit=base_unit if unit_qty is not None else None,
        pack_count=pack_count,
        price=price,
        price_per_unit=unit_price,
        image_url=image_url,
    )


def parse_carrefour_product(
    raw: Mapping[str, Any], *, category_code: str
) -> ProductObservation | None:
    """Parse one RadarSuper Carrefour product item into a `ProductObservation`."""
    return parse_radarsuper_product(raw, category_code=category_code, chain_slug="carrefour")


class RadarSuperAdapter:
    """Plain-HTTP adapter for a Spanish chain mirrored daily on RadarSuper."""

    chain_code = "carrefour"
    chain_slug = "carrefour"
    zone_kind = "salepoint"
    default_zone = "0000GV"

    def __init__(
        self,
        *,
        delay: float = 0.5,
        max_categories: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._delay_seconds = delay
        self._max_categories = max_categories
        self._external_client = client

    def close(self) -> None:
        """Close owned resources (none held between crawls)."""

    def crawl(
        self, zone: str | None = None, *, max_categories: int | None = None
    ) -> Iterator[Observation]:
        del zone  # National online Spain catalog mirrored daily by RadarSuper.
        limit = max_categories if max_categories is not None else self._max_categories
        if self._external_client is not None:
            yield from self._crawl_with_client(self._external_client, max_categories=limit)
            return
        with httpx.Client(
            timeout=25.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            yield from self._crawl_with_client(client, max_categories=limit)

    def _get(self, client: httpx.Client, url: str) -> tuple[int, str] | CrawlError:
        try:
            resp = client.get(url)
            return resp.status_code, resp.text
        except httpx.HTTPError as exc:
            return CrawlError(url=url, error=str(exc))

    def _crawl_with_client(
        self, client: httpx.Client, *, max_categories: int | None = None
    ) -> Iterator[Observation]:
        index_url = f"{BASE_URL}/{self.chain_slug}"
        idx_res = self._get(client, index_url)
        if isinstance(idx_res, CrawlError):
            yield idx_res
            return
        status, index_html = idx_res
        if status != 200:
            yield CrawlError(url=index_url, error=f"HTTP {status}")
            return
        yield RawResponse(url=index_url, status_code=status, body=index_html.encode("utf-8"))

        categories = parse_radarsuper_category_links(index_html, self.chain_slug)
        if max_categories is not None:
            categories = categories[:max_categories]

        seen_skus: set[str] = set()
        for cat_idx, (cat_code, cat_path) in enumerate(categories):
            if cat_idx > 0 and self._delay_seconds > 0:
                time.sleep(self._delay_seconds)
            cat_emitted = False
            for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
                url = (
                    f"{BASE_URL}{cat_path}" if page == 1 else f"{BASE_URL}{cat_path}/pagina/{page}"
                )
                if page > 1 and self._delay_seconds > 0:
                    time.sleep(self._delay_seconds)
                res = self._get(client, url)
                if isinstance(res, CrawlError):
                    yield res
                    break
                p_status, html = res
                if p_status == 404 and page > 1:
                    break
                if p_status != 200:
                    yield CrawlError(url=url, error=f"HTTP {p_status}")
                    break
                if page == 1:
                    yield RawResponse(url=url, status_code=p_status, body=html.encode("utf-8"))
                if not cat_emitted:
                    cat_name = parse_category_title(html, cat_code)
                    yield CategoryObservation(code=cat_code, name=cat_name, parent_code=None)
                    cat_emitted = True
                raw_items = parse_radarsuper_rsc_items(html, self.chain_slug)
                if not raw_items:
                    break
                for raw_item in raw_items:
                    obs = parse_radarsuper_product(
                        raw_item, category_code=cat_code, chain_slug=self.chain_slug
                    )
                    if obs is None or obs.sku in seen_skus:
                        continue
                    seen_skus.add(obs.sku)
                    yield obs
                if not has_next_page(html, cat_path, page):
                    break


class CarrefourAdapter(RadarSuperAdapter):
    """Plain-HTTP adapter for Carrefour Spain via RadarSuper's public category pages."""

    chain_code = "carrefour"
    chain_slug = "carrefour"
    zone_kind = "salepoint"
    default_zone = "0000GV"
