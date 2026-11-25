"""Dia adapter: the `plp-insight` catalog through a real browser, no login needed (decision 0006).

Dia sits behind a WAF that rejects plain HTTP clients, so the transport drives Chromium, binds
the zone's postal code and replays the same JSON requests the listing pages make. The parsers
are pure and are exercised with synthetic payloads (NFR-07); prices and quantities stay
`Decimal` all the way (decision 0016).
"""

import contextlib
import json
import os
import re
import sys
import time
from collections.abc import Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlencode

from smart_basket.ingestion.base import (
    CategoryObservation,
    CrawlError,
    Observation,
    ProductObservation,
    RawResponse,
)

BASE_URL = "https://www.dia.es"
API_ROOT = "/api/v1/plp-insight/initial_analytics"
PLP_API_ROOT = "/api/v1/plp-back/reduced"
#: Any product listing of the site carries the whole `menu_analytics` tree; `L1_todo` 404s.
BOOTSTRAP_URL = f"{API_ROOT}/quesos/curado/c/L2007?navigation=L2007&page=1"
IMAGE_URL = "https://www.dia.es/product_images/{sku}/{sku}_ISO_0_ES.jpg?imwidth=384"

SIZE_STEP = Decimal("0.0001")
PRICE_STEP = Decimal("0.01")
PER_UNIT_STEP = Decimal("0.0001")

# Divisor to reach the base unit of each Spanish size expression. Unknown units stay empty.
_UNIT_FACTORS: dict[str, tuple[Decimal, str]] = {
    "kg": (Decimal(1), "kg"),
    "kilo": (Decimal(1), "kg"),
    "kilos": (Decimal(1), "kg"),
    "g": (Decimal(1000), "kg"),
    "gr": (Decimal(1000), "kg"),
    "gramo": (Decimal(1000), "kg"),
    "gramos": (Decimal(1000), "kg"),
    "l": (Decimal(1), "l"),
    "litro": (Decimal(1), "l"),
    "litros": (Decimal(1), "l"),
    "ml": (Decimal(1000), "l"),
    "cl": (Decimal(100), "l"),
    "ud": (Decimal(1), "ud"),
    "uds": (Decimal(1), "ud"),
    "unidad": (Decimal(1), "ud"),
    "unidades": (Decimal(1), "ud"),
}
_UNIT_PATTERN = r"(?:kg|kilos?|gramos?|gr|g|litros?|l|ml|cl|unidades?|uds?|ud)"
_MULTIPACK = re.compile(
    rf"(?P<pack>\d+)\s*[x×]\s*(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>{_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_SINGLE_SIZE = re.compile(
    rf"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>{_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
# A pack declared only by its count (`"Actimel pack 6"`), with no weight or volume.
_COUNT_ONLY_PACK = re.compile(r"\bpack\s+(?:de\s+)?(?P<pack>\d+)\b", re.IGNORECASE)

_MENU_KEYS = ("menu", "categories", "items", "children", "results", "menu_items")
_CHILD_KEYS = ("children", "child_categories", "subcategories", "submenu", "categories", "items")
_CODE_KEYS = ("code", "navigation_code", "navigation_id", "id", "slug")
_NAME_KEYS = ("name", "label", "title", "display_name")
_PARENT_CODE_KEYS = ("parent_code", "parent_id")
_PARENT_NAME_KEYS = ("parent_name", "parent_label", "parent_title")
_CHILD_CODE_KEYS = ("child_code", "child_id")
_CHILD_NAME_KEYS = ("child_name", "child_label")
_SKU_KEYS = ("item_id", "object_id", "id", "sku", "product_id")
_PRODUCT_NAME_KEYS = ("item_name", "display_name", "name", "title")
_PRICE_KEYS = ("prices_price", "price", "unit_price", "price_value")
_URL_KEYS = ("url", "share_url", "link")


class _MenuEntry(NamedTuple):
    """One menu node: the navigation code and PLP path Dia pages it with, plus the category."""

    navigation: str
    path: str | None
    observation: CategoryObservation


class DiaTransportError(RuntimeError):
    """The browser session could not reach Dia or bind the postal code."""


class DiaTransport(Protocol):
    """What the adapter needs from a Dia session; tests inject a fake (decision 0016)."""

    def set_postal_code(self, postal_code: str) -> None: ...

    def fetch_json(self, path_and_query: str) -> tuple[int, bytes]: ...

    def close(self) -> None: ...


_SET_POSTAL_CODE_JS = """
async (cp) => {
  const url = '/api/v1/common-aggregator/save-shipping-address'
    + '?new_postal_code=' + encodeURIComponent(cp) + '&skip_dry_run=true';
  const r = await fetch(url, { method: 'PUT', signal: AbortSignal.timeout(30000) });
  return r.status;
}
"""

_FETCH_JSON_JS = """
async (u) => {
  const r = await fetch(u, { signal: AbortSignal.timeout(30000) });
  return [r.status, await r.text()];
}
"""


class PlaywrightDiaTransport:
    """Drives the real Dia site in Chromium and replays its JSON requests (decision 0006).

    Playwright is imported lazily so the unit-test image, which has no browser installed, can
    import this module. The browser runs headed when a `DISPLAY` exists or on Windows, where a
    WAF sees a normal desktop session, unless `headless` is passed explicitly.
    """

    def __init__(self, *, delay_seconds: float = 1.0, headless: bool | None = None) -> None:
        self._delay_seconds = delay_seconds
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._requests = 0

    def _ensure_page(self) -> Any:
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=self._headless_flag())
            context = self._browser.new_context(locale="es-ES")
            self._page = context.new_page()
            self._page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            self.close()
            raise
        return self._page

    def _headless_flag(self) -> bool:
        if self._headless is not None:
            return self._headless
        return not (os.environ.get("DISPLAY") or sys.platform == "win32")

    def _pause(self) -> None:
        if self._requests and self._delay_seconds:
            time.sleep(self._delay_seconds)
        self._requests += 1

    def set_postal_code(self, postal_code: str) -> None:
        """Bind the zone so Dia serves the assortment of that postal code."""
        page = self._ensure_page()
        self._pause()
        status = int(page.evaluate(_SET_POSTAL_CODE_JS, postal_code))
        if status >= 400:
            raise DiaTransportError(f"could not bind postal code {postal_code}: HTTP {status}")

    def fetch_json(self, path_and_query: str) -> tuple[int, bytes]:
        """Fetch one JSON endpoint inside the browser session and return its status and body."""
        page = self._ensure_page()
        self._pause()
        url = (
            path_and_query
            if path_and_query.startswith(("http://", "https://"))
            else f"{BASE_URL}{path_and_query}"
        )
        status, text = page.evaluate(_FETCH_JSON_JS, url)
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


def parse_dia_menu(payload: Mapping[str, Any]) -> list[CategoryObservation]:
    """Yield the level 1 and level 2 categories of a `plp-insight` payload.

    Dia's menu mixes both levels, repeats the level 1 node as its own child and adds a
    "todo ..." umbrella link; those self-links are dropped. In the real payload
    `menu_analytics` is keyed by level 1 code and each node carries its display name in
    `parameter` (`"L1_quesos"` -> `"quesos"`); the older nested and flat shapes are still
    accepted.
    """
    return [entry.observation for entry in _menu_entries_with_codes(payload)]


def parse_dia_size(name: str) -> tuple[Decimal | None, str | None, int]:
    """Parse a Spanish size expression into (`base_quantity`, `base_unit`, `pack_count`).

    `"6 x 33 cl"`, `"4x100g"` and `"pack 4 x 125 g"` keep the per-unit size and the pack count;
    `"1,5 l"`, `"750 ml"`, `"200 g"` and `"1 kg"` are single units. A pack declared only by its
    count (`"Actimel pack 6"`) becomes one unit per pack. Sizes are normalized to kg, l or ud; a
    name without a recognizable size leaves the quantity and the unit empty.
    """
    if not isinstance(name, str) or not name.strip():
        return (None, None, 1)
    text = name.replace("×", "x")
    match = _MULTIPACK.search(text)
    if match is not None:
        pack_count = int(match.group("pack"))
        if pack_count <= 0:
            return (None, None, 1)
        quantity, unit = _normalized_size(match.group("qty"), match.group("unit"))
        return (quantity, unit, pack_count) if quantity is not None else (None, None, 1)
    match = _SINGLE_SIZE.search(text)
    if match is not None:
        quantity, unit = _normalized_size(match.group("qty"), match.group("unit"))
        if quantity is not None:
            return (quantity, unit, 1)
    match = _COUNT_ONLY_PACK.search(text)
    if match is not None:
        pack_count = int(match.group("pack"))
        if pack_count > 1:
            return (Decimal(1), "ud", pack_count)
    return (None, None, 1)


def parse_dia_products(
    payload: Mapping[str, Any], *, category_code: str
) -> list[ProductObservation]:
    """Parse the products of one listing page, dropping out-of-stock or unusable entries."""
    products: list[ProductObservation] = []
    for raw in _product_rows(payload):
        observation = _parse_dia_product(raw, category_code)
        if observation is not None:
            products.append(observation)
    return products


class DiaAdapter:
    """Crawls the Dia catalog for one postal code (zone) at a time."""

    chain_code = "dia"
    zone_kind = "postal_code"

    def __init__(
        self,
        *,
        transport: DiaTransport | None = None,
        delay_seconds: float = 1.0,
        max_pages: int = 50,
        delay: float | None = None,
    ) -> None:
        # `delay` is the name the CLI uses for every adapter; `delay_seconds` is the Dia name.
        effective_delay = delay if delay is not None else delay_seconds
        self._transport = transport or PlaywrightDiaTransport(delay_seconds=effective_delay)
        self._max_pages = max_pages

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._transport.close()

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        self._transport.set_postal_code(zone_code)
        status, body = self._transport.fetch_json(BOOTSTRAP_URL)
        yield RawResponse(BOOTSTRAP_URL, status, body)
        if status != 200:
            yield CrawlError(url=BOOTSTRAP_URL, error=f"HTTP {status}")
            return
        payload = _payload(body)
        if payload is None:
            yield CrawlError(url=BOOTSTRAP_URL, error="invalid JSON")
            return

        entries = _menu_entries_with_codes(payload)
        sources = {
            (entry.observation.parent_code, entry.observation.code): entry for entry in entries
        }
        categories = [entry.observation for entry in entries]
        yield from categories

        level_two = [category for category in categories if category.parent_code is not None]
        if max_categories is not None:
            level_two = level_two[:max_categories]
        for category in level_two:
            entry = sources.get((category.parent_code, category.code))
            if entry is None:
                navigation, path = _navigation_code(category), None
            else:
                navigation, path = entry.navigation, entry.path
            yield from self._crawl_category(category, navigation, path)

    def _crawl_category(
        self,
        category: CategoryObservation,
        navigation: str,
        path: str | None = None,
    ) -> Iterator[Observation]:
        seen: set[str] = set()
        for page in range(1, self._max_pages + 1):
            url = _plp_url(navigation, page, path)
            status, body = self._transport.fetch_json(url)
            yield RawResponse(url, status, body)
            if status != 200:
                yield CrawlError(url=url, error=f"HTTP {status}")
                return
            payload = _payload(body)
            if payload is None:
                yield CrawlError(url=url, error="invalid JSON")
                return
            # Stop on raw rows, not parsed products: a page of out-of-stock items parses empty
            # but a later page can still carry the rest of the listing.
            raw_skus = _raw_skus(payload)
            if not raw_skus:
                return
            fresh = {sku for sku in raw_skus if sku not in seen}
            if not fresh:
                return
            seen.update(fresh)
            for product in parse_dia_products(payload, category_code=category.code):
                if product.sku in fresh:
                    yield product


def _raw_skus(payload: Mapping[str, Any]) -> list[str]:
    skus: list[str] = []
    for row in _product_rows(payload):
        sku = _first(row, _SKU_KEYS)
        if sku is not None:
            skus.append(str(sku))
    return skus


def _plp_url(navigation: str, page: int, path: str | None = None) -> str:
    query = urlencode({"navigation": navigation, "page": page})
    base = f"{PLP_API_ROOT}{path}" if path else API_ROOT
    return f"{base}?{query}"


def _navigation_code(category: CategoryObservation) -> str:
    """Rebuild the site's navigation code when the payload did not provide a raw one."""
    prefix = "L1_" if category.parent_code is None else "L2_"
    return category.code if category.code.startswith(prefix) else f"{prefix}{category.code}"


def _payload(body: bytes) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(body)
    except TypeError, ValueError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _menu_entries_with_codes(payload: Mapping[str, Any]) -> list[_MenuEntry]:
    """Return each category next to the navigation code and PLP path Dia pages it with."""
    menu = payload.get("menu_analytics")
    if _is_keyed_menu(menu):
        return _keyed_menu_entries(menu)
    rows = _menu_rows(payload)
    if any(_first(row, _CHILD_CODE_KEYS) is not None for row in rows if isinstance(row, Mapping)):
        return _flat_menu_entries(rows)
    return _nested_menu_entries(rows)


def _is_keyed_menu(menu: object) -> bool:
    """True for the real shape: `{l1_code: {parameter, path, children: {l2_code: ...}}}`."""
    if not isinstance(menu, Mapping) or not menu:
        return False
    if any(key in menu for key in _MENU_KEYS):
        return False
    return all(
        isinstance(value, Mapping)
        and any(field in value for field in ("parameter", "path", "children"))
        for value in menu.values()
    )


def _keyed_menu_entries(menu: Mapping[str, Any]) -> list[_MenuEntry]:
    """Parse the dict-keyed menu of the live `plp-insight` endpoint."""
    entries: list[_MenuEntry] = []
    for parent_raw, node in menu.items():
        if not isinstance(node, Mapping):
            continue
        parent_name = _parameter_name(node)
        if not parent_name:
            continue
        parent_code = _clean_code(parent_raw)
        entries.append(
            _MenuEntry(
                str(parent_raw),
                _menu_path(node),
                CategoryObservation(parent_code, parent_name, None),
            )
        )
        children = node.get("children")
        if not isinstance(children, Mapping):
            continue
        for child_raw, child in children.items():
            if not isinstance(child, Mapping):
                continue
            child_name = _parameter_name(child)
            if not child_name or _is_self_link(parent_raw, child_raw):
                continue
            entries.append(
                _MenuEntry(
                    str(child_raw),
                    _menu_path(child),
                    CategoryObservation(_clean_code(child_raw), child_name, parent_code),
                )
            )
    return entries


def _parameter_name(node: Mapping[str, Any]) -> str | None:
    """Display name of a keyed menu node: `parameter` without its `L1_`/`L2_` prefix."""
    parameter = _first(node, (*_NAME_KEYS, "parameter"))
    if parameter is None:
        return None
    name = _clean_code(parameter)
    return name or None


def _menu_path(node: Mapping[str, Any]) -> str | None:
    path = node.get("path")
    return path if isinstance(path, str) and path.startswith("/") else None


def _menu_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    menu = payload.get("menu_analytics")
    if isinstance(menu, list):
        return [row for row in menu if isinstance(row, Mapping)]
    if not isinstance(menu, Mapping):
        return []
    for key in _MENU_KEYS:
        value = menu.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, Mapping):
            for inner_key in _MENU_KEYS:
                nested = value.get(inner_key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, Mapping)]
    return [menu] if _first(menu, _CODE_KEYS) is not None else []


def _flat_menu_entries(rows: list[Mapping[str, Any]]) -> list[_MenuEntry]:
    """Parse the flat `parent_code`/`child_code` menu rows Dia returns for some payloads."""
    entries: list[_MenuEntry] = []
    parents: set[str] = set()
    for row in rows:
        parent_raw = _first(row, _PARENT_CODE_KEYS)
        parent_name = _first(row, _PARENT_NAME_KEYS)
        if parent_raw is None or not parent_name:
            continue
        parent_code = _clean_code(parent_raw)
        if parent_code not in parents:
            parents.add(parent_code)
            entries.append(
                _MenuEntry(
                    str(parent_raw),
                    None,
                    CategoryObservation(parent_code, str(parent_name), None),
                )
            )
        child_raw = _first(row, _CHILD_CODE_KEYS)
        child_name = _first(row, _CHILD_NAME_KEYS)
        if child_raw is None or not child_name or _is_self_link(parent_raw, child_raw):
            continue
        entries.append(
            _MenuEntry(
                str(child_raw),
                None,
                CategoryObservation(_clean_code(child_raw), str(child_name), parent_code),
            )
        )
    return entries


def _nested_menu_entries(rows: list[Mapping[str, Any]]) -> list[_MenuEntry]:
    """Parse the nested menu where each level 1 node carries its level 2 children."""
    entries: list[_MenuEntry] = []
    for node in rows:
        parent_raw = _first(node, _CODE_KEYS)
        parent_name = _first(node, _NAME_KEYS)
        if parent_raw is None or not parent_name:
            continue
        parent_code = _clean_code(parent_raw)
        entries.append(
            _MenuEntry(
                str(parent_raw),
                None,
                CategoryObservation(parent_code, str(parent_name), None),
            )
        )
        for child in _children(node):
            child_raw = _first(child, _CODE_KEYS)
            child_name = _first(child, _NAME_KEYS)
            if child_raw is None or not child_name or _is_self_link(parent_raw, child_raw):
                continue
            entries.append(
                _MenuEntry(
                    str(child_raw),
                    None,
                    CategoryObservation(_clean_code(child_raw), str(child_name), parent_code),
                )
            )
    return entries


def _children(node: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for key in _CHILD_KEYS:
        value = node.get(key)
        if isinstance(value, list):
            yield from (child for child in value if isinstance(child, Mapping))
            return


def _is_self_link(parent_raw: object, child_raw: object) -> bool:
    parent = str(parent_raw)
    child = str(child_raw)
    return child == parent or child.startswith("L2_todo") or _clean_code(child).startswith("todo")


def _clean_code(value: object) -> str:
    code = str(value).strip()
    for prefix in ("L1_", "L2_"):
        if code.startswith(prefix):
            return code[len(prefix) :]
    return code


def _first(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalized_size(raw_quantity: str, raw_unit: str) -> tuple[Decimal | None, str | None]:
    quantity = _decimal(raw_quantity, SIZE_STEP)
    factor = _UNIT_FACTORS.get(raw_unit.strip().lower())
    if quantity is None or quantity == 0 or factor is None:
        return (None, None)
    divisor, unit = factor
    normalized = (quantity / divisor).quantize(SIZE_STEP, rounding=ROUND_HALF_UP)
    return (normalized, unit) if normalized != 0 else (None, None)


def _product_rows(payload: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    plp_items = payload.get("plp_items")
    if isinstance(plp_items, list):
        yield from (row for row in plp_items if isinstance(row, Mapping))
        return
    analytics = payload.get("page_product_analytics")
    rows: object = None
    if isinstance(analytics, Mapping):
        for key in ("products", "plp_items", "items", "results"):
            if isinstance(analytics.get(key), list):
                rows = analytics[key]
                break
        else:
            # Real payload: the mapping itself is keyed by SKU.
            values = list(analytics.values())
            if values and all(isinstance(value, Mapping) for value in values):
                rows = values
    elif isinstance(analytics, list):
        rows = analytics
    if not isinstance(rows, list):
        return
    yield from (row for row in rows if isinstance(row, Mapping))


def _parse_dia_product(raw: Mapping[str, Any], category_code: str) -> ProductObservation | None:
    if raw.get("stock_availability") is False:
        return None
    sku = _first(raw, _SKU_KEYS)
    name = _first(raw, _PRODUCT_NAME_KEYS)
    price = _price(raw)
    if sku is None or not name or price is None:
        return None
    sku = str(sku)
    name = str(name)
    base_quantity, base_unit, pack_count = parse_dia_size(name)
    return ProductObservation(
        sku=sku,
        name=name,
        packaging=None,
        url=_absolute_url(_first(raw, _URL_KEYS)),
        category_code=category_code,
        base_quantity=base_quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        price=price,
        price_per_unit=_price_per_unit(price, base_quantity, base_unit, pack_count),
        image_url=IMAGE_URL.format(sku=sku),
    )


def _price(raw: Mapping[str, Any]) -> Decimal | None:
    for key in _PRICE_KEYS:
        price = _decimal(raw.get(key), PRICE_STEP)
        if price is not None:
            return price
    prices = raw.get("prices")
    if isinstance(prices, Mapping):
        for key in ("price", "unit_price", "value"):
            price = _decimal(prices.get(key), PRICE_STEP)
            if price is not None:
                return price
    return None


def _price_per_unit(
    price: Decimal,
    base_quantity: Decimal | None,
    base_unit: str | None,
    pack_count: int,
) -> Decimal | None:
    if base_quantity is None or base_unit is None:
        return None
    total = base_quantity * pack_count
    if total <= 0:
        return None
    return (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)


def _absolute_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return None


def _decimal(value: object, step: Decimal) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation, ValueError:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number.quantize(step, rounding=ROUND_HALF_UP)
