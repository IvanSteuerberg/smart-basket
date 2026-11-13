"""Recommendation pipeline: candidates, catalog, optimizer, route and persistence.

The requested leaf category acts as the provisional canonical product until real matching
arrives (iteration 12); every price, quantity and total is a `Decimal` outside the response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.config import Settings
from smart_basket.optimizer import (
    BasketRequest,
    BasketResult,
    LinePurchase,
    MissingLine,
    MissingReason,
    PriorityMode,
    Product,
    Store,
    StorePurchase,
    optimize,
)
from smart_basket.recommender.candidates import CandidateStore, candidate_stores
from smart_basket.recommender.catalog import (
    CatalogEntry,
    Item,
    build_catalog,
    load_categories,
)
from smart_basket.recommender.explanation import explain
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


def recommend(
    session: Session,
    query: RecommendationQuery,
    routing: RoutingEngine,
    today: date,
    settings: Settings,
) -> dict[str, Any]:
    """Run the pipeline and store the recommendation; returns the response body."""
    candidates = candidate_stores(session, query.origin, query.mode, settings)
    if not candidates:
        raise NoCandidateStores
    categories = load_categories(session, {item.category_key for item in query.items})
    entries = build_catalog(session, query.items, categories, {c.zone_id for c in candidates})

    travel = routing.travel_times(
        query.origin,
        [StoreLocation(c.store_id, _point(c)) for c in candidates],
        query.mode,
    )
    basket = optimize(
        BasketRequest(
            lines=tuple(entry.line for entry in entries if entry.line is not None),
            stores=_stores(candidates, entries),
            travel_times=travel,
            shopping_date=today,
            max_stores=query.max_stores,
            priority_mode=query.priority_mode,
            return_to_origin=query.return_to_origin,
        )
    )
    route = _route(routing, query, candidates, basket)
    names = {pid: name for entry in entries for pid, name in entry.product_names.items()}
    texts = {str(entry.item_index): entry.text for entry in entries}
    names_by_id = {c.store_id: c.name for c in candidates}
    data_as_of = _data_as_of(session, candidates, basket)
    extra = tuple(
        MissingLine(str(entry.item_index), MissingReason.NOT_AVAILABLE)
        for entry in entries
        if entry.line is None
    )
    missing = tuple(sorted((*basket.missing, *extra), key=lambda line: int(line.line_id)))

    recommendation_id = session.execute(text("select uuidv7()")).scalar_one()
    body: dict[str, Any] = {
        "id": str(recommendation_id),
        "data_as_of": _iso(data_as_of),
        "engine_version": basket.engine_version,
        "stores": [_store(sp, candidates, names, texts) for sp in basket.stores],
        "total_cost": _money(basket.total_cost),
        "minutes": _quantity(basket.minutes),
        "missing": [_missing_line(line, candidates, texts) for line in missing],
        "route": [[lat, lon] for lat, lon in route],
        "explanation": explain(basket, names_by_id, texts, extra),
        "degraded": query.degraded,
    }
    _persist(session, recommendation_id, query, basket, data_as_of, body)
    return body


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
    candidates: list[CandidateStore],
    names: dict[int, str],
    texts: dict[str, str],
) -> dict[str, Any]:
    store = next(c for c in candidates if c.store_id == purchase.store_id)
    return {
        "store_id": store.store_id,
        "name": store.name,
        "chain": store.chain,
        "lat": store.latitude,
        "lon": store.longitude,
        "position": purchase.position,
        "lines": [_line(line, names, texts) for line in purchase.lines],
        "subtotal": _money(purchase.subtotal),
    }


def _line(purchase: LinePurchase, names: dict[int, str], texts: dict[str, str]) -> dict[str, Any]:
    product_names = list(
        dict.fromkeys(names[pack.product_id] for pack in purchase.packs if pack.product_id in names)
    )
    return {
        "text": texts[purchase.line_id],
        "product_name": " + ".join(product_names),
        "packs": sum(pack.packs for pack in purchase.packs),
        "quantity_bought": _quantity(purchase.quantity_bought),
        "cost": _money(purchase.cost),
    }


def _missing_line(
    line: MissingLine, candidates: list[CandidateStore], texts: dict[str, str]
) -> dict[str, Any]:
    stop = None
    if line.reason is MissingReason.SEPARATE_STOP and line.stop is not None:
        separate = line.stop
        store = next(c for c in candidates if c.store_id == separate.store_id)
        stop = {
            "store_id": separate.store_id,
            "name": store.name,
            "cost": _money(separate.purchase.cost),
            "extra_minutes": _quantity(separate.extra_minutes),
            "exceeds_max_stores": separate.exceeds_max_stores,
        }
    return {"text": texts[line.line_id], "reason": line.reason.value, "stop": stop}


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
    body: dict[str, Any],
) -> None:
    """Store the recommendation and its items anonymously (rounded origin, NFR-06)."""
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
            "request": json.dumps(query.payload, ensure_ascii=False),
            "result": json.dumps(body, ensure_ascii=False),
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
                        "chain_product_id, store_id, quantity, unit_price, line_total, "
                        "promotion_id) values (:id, :line, :part, :product, :store, :quantity, "
                        ":unit_price, :line_total, :promotion)"
                    ),
                    {
                        "id": recommendation_id,
                        "line": int(line.line_id),
                        "part": part,
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
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def _quantity(value: Decimal) -> str:
    """Decimal without trailing zeros as a string ("2.0000" -> "2")."""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _iso(value: datetime) -> str:
    """UTC timestamp with `Z`, as the API contract shows it."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
