"""Recommendation pipeline: candidates, catalog, optimizer, route and persistence.

The requested leaf category acts as the provisional canonical product until real matching
arrives (iteration 12); every price, quantity and total is a `Decimal` outside the response.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.config import Settings
from smart_basket.optimizer import (
    ENGINE_VERSION,
    LAMBDA_PRESETS,
    BasketRequest,
    BasketResult,
    LinePurchase,
    MissingLine,
    MissingReason,
    PriorityMode,
    Product,
    Store,
    StorePurchase,
    TravelTimes,
    optimize,
)
from smart_basket.recommender.candidates import CandidateStore, candidate_stores
from smart_basket.recommender.catalog import (
    CatalogEntry,
    CategoryInfo,
    Item,
    build_catalog,
    load_categories,
)
from smart_basket.recommender.explanation import cents, decimal_text, explain
from smart_basket.routing.base import (
    GeoPoint,
    RoutingEngine,
    StoreLocation,
    TravelMode,
)

#: Side of the anonymity cell the origin is rounded to, in degrees (about 500 m).
ORIGIN_CELL = Decimal("0.005")
CENT = Decimal("0.01")


class NoCandidateStores(Exception):
    """No store with current prices is close enough to the origin."""


class BasketCalculationError(Exception):
    """The optimizer rejected the basket built for this list."""


class InconsistentResult(RuntimeError):
    """The optimizer returned a store that is not among the candidates: an internal error."""


class VagueLine(Exception):
    """A generic line names a vague category and needs the shopper's choice first."""

    def __init__(self, line_id: int, category_key: str, name: str) -> None:
        self.line_id = line_id
        self.category_key = category_key
        self.message = f"Elige qué {name.lower()} quieres antes de calcular la cesta."
        super().__init__(self.message)


class LineResponse(BaseModel):
    line_id: int
    text: str
    product_id: int
    canonical_id: int | None
    brand: str | None
    image_url: str | None
    product_name: str
    packs: int
    quantity_bought: str
    cost: str


class StoreResponse(BaseModel):
    store_id: int
    name: str
    chain: str
    address: str | None
    lat: float
    lon: float
    position: int
    lines: list[LineResponse]
    subtotal: str


class StopResponse(BaseModel):
    store_id: int
    name: str
    cost: str
    extra_minutes: str
    exceeds_max_stores: bool


class MissingResponse(BaseModel):
    line_id: int
    text: str
    reason: Literal["not_available", "separate_stop", "unreachable"]
    stop: StopResponse | None = None


class LineSaving(BaseModel):
    line_id: int
    savings: str


class FlexSavings(BaseModel):
    total: str
    lines: list[LineSaving]


class RecommendationResponse(BaseModel):
    id: str
    data_as_of: str | None
    engine_version: str
    stores: list[StoreResponse]
    total_cost: str
    minutes: str
    missing: list[MissingResponse]
    flex_savings: FlexSavings | None = None
    route: list[list[float]]
    explanation: str
    degraded: bool


@dataclass(frozen=True, slots=True)
class RecommendationQuery:
    """A recommendation request, independent of the HTTP models."""

    items: tuple[Item, ...]
    origin: GeoPoint
    mode: TravelMode
    max_stores: int
    priority_mode: PriorityMode
    return_to_origin: bool
    degraded: bool
    #: Original request body, stored anonymously with the recommendation.
    payload: dict[str, Any]
    #: Chain codes to consider; empty means every chain.
    chains: tuple[str, ...] = ()


def recommend(
    session: Session,
    query: RecommendationQuery,
    routing: RoutingEngine,
    today: date,
    settings: Settings,
) -> RecommendationResponse:
    """Run the pipeline and store the recommendation; returns the response body."""
    categories = load_categories(
        session, {item.category_key for item in query.items if item.category_key is not None}
    )
    _reject_vague_lines(query, categories)
    candidates = candidate_stores(
        session, query.origin, query.mode, settings, frozenset(query.chains)
    )
    if not candidates:
        raise NoCandidateStores
    entries = build_catalog(session, query.items, categories, {c.zone_id for c in candidates})
    lines = tuple(entry.line for entry in entries if entry.line is not None)

    travel = None
    if lines:
        # The session stays open during the Valhalla calls (a second connection would be
        # needed otherwise); acceptable for the MVP, where a recommendation is short.
        travel = routing.travel_times(
            query.origin,
            [StoreLocation(c.store_id, _point(c)) for c in candidates],
            query.mode,
        )
        basket = _optimize(query, entries, candidates, travel, today)
    else:
        basket = _nothing_to_buy(query)
    flex_savings = (
        _flex_savings(session, query, entries, categories, candidates, travel, today, basket)
        if travel is not None
        else None
    )
    route = _route(routing, query, candidates, basket)
    stores_by_id = {c.store_id: c for c in candidates}
    names = {pid: name for entry in entries for pid, name in entry.product_names.items()}
    canonicals = {
        pid: canonical for entry in entries for pid, canonical in entry.product_canonicals.items()
    }
    brands = {pid: brand for entry in entries for pid, brand in entry.product_brands.items()}
    images = {pid: image for entry in entries for pid, image in entry.product_images.items()}
    texts = {str(entry.item_index): entry.text for entry in entries}
    names_by_id = {c.store_id: c.name for c in candidates}
    addresses_by_id = {c.store_id: c.address for c in candidates}
    data_as_of = _data_as_of(session, candidates, basket)
    extra = tuple(
        MissingLine(str(entry.item_index), MissingReason.NOT_AVAILABLE)
        for entry in entries
        if entry.line is None
    )
    missing = tuple(sorted((*basket.missing, *extra), key=lambda line: int(line.line_id)))

    recommendation_id = session.execute(text("select uuidv7()")).scalar_one()
    response = RecommendationResponse(
        id=str(recommendation_id),
        data_as_of=_iso(data_as_of) if basket.stores else None,
        engine_version=basket.engine_version,
        stores=[
            _store(sp, stores_by_id, names, texts, canonicals, brands, images)
            for sp in basket.stores
        ],
        total_cost=_money(basket.total_cost) if basket.stores else "0",
        minutes=_quantity(basket.minutes) if basket.stores else "0",
        missing=[_missing_line(line, stores_by_id, texts) for line in missing],
        flex_savings=flex_savings,
        route=[[lat, lon] for lat, lon in route],
        explanation=explain(basket, names_by_id, texts, extra, addresses_by_id),
        degraded=query.degraded,
    )
    _persist(session, recommendation_id, query, basket, data_as_of, response)
    return response


def _reject_vague_lines(query: RecommendationQuery, categories: Mapping[str, CategoryInfo]) -> None:
    """A vague category must be narrowed by the shopper before any basket is calculated."""
    for index, item in enumerate(query.items):
        if item.category_key is None:
            continue
        category = categories.get(item.category_key)
        if category is not None and category.is_vague:
            raise VagueLine(index, item.category_key, category.name)


def _flex_savings(
    session: Session,
    query: RecommendationQuery,
    entries: tuple[CatalogEntry, ...],
    categories: Mapping[str, CategoryInfo],
    candidates: list[CandidateStore],
    travel: TravelTimes,
    today: date,
    basket: BasketResult,
) -> FlexSavings | None:
    """What the exact lines would save if their equivalent products were accepted."""
    exact = {entry.item_index for entry in entries if entry.exact}
    if not exact:
        return None
    flexible_items = tuple(
        replace(item, accept="equivalent") if entry.exact else item
        for item, entry in zip(query.items, entries, strict=True)
    )
    flexible_entries = build_catalog(
        session, flexible_items, categories, {c.zone_id for c in candidates}
    )
    flexible = _optimize(query, flexible_entries, candidates, travel, today)
    total = basket.total_cost - flexible.total_cost
    if total <= 0:
        return None
    current_costs = _line_costs(basket)
    flexible_costs = _line_costs(flexible)
    lines = [
        LineSaving(
            line_id=index,
            savings=_money(
                current_costs.get(index, Decimal(0)) - flexible_costs.get(index, Decimal(0))
            ),
        )
        for index in sorted(exact)
        if current_costs.get(index, Decimal(0)) > flexible_costs.get(index, Decimal(0))
    ]
    return FlexSavings(total=_money(total), lines=lines)


def _line_costs(basket: BasketResult) -> dict[int, Decimal]:
    """Cost of each bought line, summed over the stores of the basket."""
    costs: dict[int, Decimal] = {}
    for purchase in basket.stores:
        for line in purchase.lines:
            index = int(line.line_id)
            costs[index] = costs.get(index, Decimal(0)) + line.cost
    return costs


def _optimize(
    query: RecommendationQuery,
    entries: tuple[CatalogEntry, ...],
    candidates: list[CandidateStore],
    travel: TravelTimes,
    today: date,
) -> BasketResult:
    """Build the optimizer input and run it; a rejected input is a client-side error."""
    try:
        request = BasketRequest(
            lines=tuple(entry.line for entry in entries if entry.line is not None),
            stores=_stores(candidates, entries),
            travel_times=travel,
            shopping_date=today,
            max_stores=query.max_stores,
            priority_mode=query.priority_mode,
            return_to_origin=query.return_to_origin,
        )
        return optimize(request)
    except ValueError as exc:
        raise BasketCalculationError(str(exc)) from exc


def _nothing_to_buy(query: RecommendationQuery) -> BasketResult:
    """An empty result when no item resolved to a line: the optimizer is not called."""
    return BasketResult(
        engine_version=ENGINE_VERSION,
        stores=(),
        total_cost=Decimal(0),
        comparable_cost=Decimal(0),
        minutes=Decimal(0),
        lambda_per_minute=LAMBDA_PRESETS[query.priority_mode],
        coverage_margin=Decimal("3.00"),
        objective=Decimal(0),
        priority_mode=query.priority_mode,
        max_stores=query.max_stores,
        return_to_origin=query.return_to_origin,
        missing=(),
    )


def _point(store: CandidateStore) -> GeoPoint:
    return GeoPoint(store.latitude, store.longitude)


def _stores(
    candidates: list[CandidateStore], entries: tuple[CatalogEntry, ...]
) -> tuple[Store, ...]:
    """One optimizer store per candidate, with the products its zone sells for every line."""
    by_zone: dict[int, dict[tuple[int, int], Product]] = {}
    for entry in entries:
        for zone_id, products in entry.products_by_zone.items():
            bucket = by_zone.setdefault(zone_id, {})
            for product in products:
                bucket.setdefault((product.product_id, product.canonical_id), product)
    return tuple(
        Store(
            store_id=c.store_id,
            chain_id=c.chain_id,
            zone_id=c.zone_id,
            products=tuple(by_zone.get(c.zone_id, {}).values()),
        )
        for c in candidates
    )


def _route(
    routing: RoutingEngine,
    query: RecommendationQuery,
    candidates: list[CandidateStore],
    basket: BasketResult,
) -> list[tuple[float, float]]:
    """Geometry from the origin through the chosen stores, back home when asked."""
    if not basket.stores:
        return []
    points = {c.store_id: _point(c) for c in candidates}
    nodes = [query.origin, *(points[s.store_id] for s in basket.stores)]
    if query.return_to_origin:
        nodes.append(query.origin)
    return routing.route_shape(nodes, query.mode)


def _store(
    purchase: StorePurchase,
    stores: Mapping[int, CandidateStore],
    names: dict[int, str],
    texts: dict[str, str],
    canonicals: dict[int, int | None],
    brands: dict[int, str | None],
    images: dict[int, str | None],
) -> StoreResponse:
    store = stores.get(purchase.store_id)
    if store is None:
        raise InconsistentResult(f"store {purchase.store_id} is not among the candidates")
    return StoreResponse(
        store_id=store.store_id,
        name=store.name,
        chain=store.chain,
        address=store.address,
        lat=store.latitude,
        lon=store.longitude,
        position=purchase.position,
        lines=[_line(line, names, texts, canonicals, brands, images) for line in purchase.lines],
        subtotal=_money(purchase.subtotal),
    )


def _line(
    purchase: LinePurchase,
    names: dict[int, str],
    texts: dict[str, str],
    canonicals: dict[int, int | None],
    brands: dict[int, str | None],
    images: dict[int, str | None],
) -> LineResponse:
    product_names = list(
        dict.fromkeys(names[pack.product_id] for pack in purchase.packs if pack.product_id in names)
    )
    if not purchase.packs:
        raise InconsistentResult(f"line {purchase.line_id} was bought without a product")
    product_id = purchase.packs[0].product_id
    return LineResponse(
        line_id=int(purchase.line_id),
        text=texts[purchase.line_id],
        product_id=product_id,
        canonical_id=canonicals.get(product_id),
        brand=brands.get(product_id),
        image_url=images.get(product_id),
        product_name=" + ".join(product_names),
        packs=sum(pack.packs for pack in purchase.packs),
        quantity_bought=_quantity(purchase.quantity_bought),
        cost=_money(purchase.cost),
    )


def _missing_line(
    line: MissingLine, stores: Mapping[int, CandidateStore], texts: dict[str, str]
) -> MissingResponse:
    stop = None
    if line.reason is MissingReason.SEPARATE_STOP and line.stop is not None:
        separate = line.stop
        store = stores.get(separate.store_id)
        if store is None:
            raise InconsistentResult(f"store {separate.store_id} is not among the candidates")
        stop = StopResponse(
            store_id=separate.store_id,
            name=store.name,
            cost=_money(separate.purchase.cost),
            extra_minutes=_quantity(separate.extra_minutes),
            exceeds_max_stores=separate.exceeds_max_stores,
        )
    return MissingResponse(
        line_id=int(line.line_id), text=texts[line.line_id], reason=line.reason.value, stop=stop
    )


def _data_as_of(
    session: Session, candidates: list[CandidateStore], basket: BasketResult
) -> datetime:
    """Oldest price sighting among the zones of the stores used (or all candidates)."""
    by_id = {c.store_id: c for c in candidates}
    zones = {by_id[s.store_id].zone_id for s in basket.stores} or {c.zone_id for c in candidates}
    seen = session.execute(
        text("select min(last_seen_at) from price_current where zone_id in :zones").bindparams(
            bindparam("zones", expanding=True)
        ),
        {"zones": sorted(zones)},
    ).scalar_one()
    return seen or datetime.now(UTC)


def _persist(
    session: Session,
    recommendation_id: Any,
    query: RecommendationQuery,
    basket: BasketResult,
    data_as_of: datetime,
    response: RecommendationResponse,
) -> None:
    """Store the recommendation and its items anonymously (rounded origin, NFR-06)."""
    # The exact origin is never stored: the request keeps the rounded cell and the result
    # drops the route, which starts and ends at the origin.
    request_body = dict(query.payload)
    request_body["origin"] = _origin_cell(query.origin)
    result_body = response.model_dump()
    result_body.pop("route", None)
    canonicals = {
        line.product_id: line.canonical_id for store in response.stores for line in store.lines
    }
    session.execute(
        text(
            "insert into recommendation (id, data_as_of, engine_version, origin_cell, "
            "travel_mode, priority_mode, max_stores, lambda, request, result, total_cost, "
            "minutes) values (:id, :data_as_of, :engine, :cell, :mode, :priority, :max_stores, "
            ":lambda, cast(:request as jsonb), cast(:result as jsonb), :total, :minutes)"
        ),
        {
            "id": recommendation_id,
            "data_as_of": data_as_of,
            "engine": basket.engine_version,
            "cell": _origin_cell(query.origin),
            "mode": query.mode.value,
            "priority": query.priority_mode.value,
            "max_stores": query.max_stores,
            "lambda": basket.lambda_per_minute,
            "request": json.dumps(request_body, ensure_ascii=False),
            "result": json.dumps(result_body, ensure_ascii=False),
            "total": basket.total_cost,
            "minutes": basket.minutes,
        },
    )
    for purchase in basket.stores:
        for line in purchase.lines:
            for part, pack in enumerate(line.packs, start=1):
                session.execute(
                    text(
                        "insert into recommendation_item (recommendation_id, line, part, "
                        "canonical_id, chain_product_id, store_id, quantity, unit_price, "
                        "line_total, promotion_id) values (:id, :line, :part, :canonical, "
                        ":product, :store, :quantity, :unit_price, :line_total, :promotion)"
                    ),
                    {
                        "id": recommendation_id,
                        "line": int(line.line_id),
                        "part": part,
                        "canonical": canonicals.get(pack.product_id),
                        "product": pack.product_id,
                        "store": purchase.store_id,
                        "quantity": pack.quantity,
                        "unit_price": (pack.cost / pack.packs).quantize(
                            CENT, rounding=ROUND_HALF_UP
                        ),
                        "line_total": pack.cost,
                        "promotion": pack.promotion_id,
                    },
                )


def _origin_cell(origin: GeoPoint) -> str:
    """Cell of about 500 m the origin is rounded to, never the exact point."""
    lat = (Decimal(str(origin.latitude)) / ORIGIN_CELL).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    lon = (Decimal(str(origin.longitude)) / ORIGIN_CELL).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return f"{lat * ORIGIN_CELL:.3f},{lon * ORIGIN_CELL:.3f}"


def _money(value: Decimal) -> str:
    """Two decimals with a dot, as the API contract shows money."""
    return f"{cents(value):.2f}"


def _quantity(value: Decimal) -> str:
    """Decimal without trailing zeros as a string ("2.0000" -> "2")."""
    return decimal_text(value)


def _iso(value: datetime) -> str:
    """UTC timestamp with `Z`, as the API contract shows it."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
