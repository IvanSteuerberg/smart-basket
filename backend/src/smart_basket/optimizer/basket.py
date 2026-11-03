"""Basket optimizer (decision 0002, layer 3; FR-13; rules in decision 0013).

Exhaustive search over store subsets of size <= max_stores among the candidates. Within a
subset each line goes to its cheapest store (comparable cost), and the visiting order is the
fastest permutation. Objective: comparable cost + lambda x minutes. Subsets are ranked by
(lines left uncovered, objective, stores, minutes, store ids), so the search is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations, pairwise, permutations

from smart_basket.optimizer.models import (
    BasketRequest,
    BasketResult,
    LinePurchase,
    MissingLine,
    MissingReason,
    Store,
    StorePurchase,
    TravelTimes,
)
from smart_basket.optimizer.packs import LineOption, cover_line
from smart_basket.optimizer.pricing import PricingContext

#: Version of the optimizer and effective-price rules; stored with each recommendation
#: (NFR-03, NFR-05). Bump it whenever the same input could give a different basket.
ENGINE_VERSION = "basket-engine/1.0.0"


@dataclass(frozen=True, slots=True)
class _Route:
    minutes: Decimal
    order: tuple[int, ...]


def best_route(
    store_ids: tuple[int, ...], travel: TravelTimes, return_to_origin: bool
) -> _Route | None:
    """Fastest visiting order of `store_ids` from the origin (index 0), or None if unreachable.

    Every permutation is checked (at most 3! = 6). Ties go to the lexicographically smallest
    order of store ids.
    """
    index = {sid: i + 1 for i, sid in enumerate(travel.store_ids)}
    best: _Route | None = None
    for order in permutations(sorted(store_ids)):
        nodes = [0, *(index[s] for s in order)]
        if return_to_origin:
            nodes.append(0)
        total = Decimal(0)
        for a, b in pairwise(nodes):
            leg = travel.minutes[a][b]
            if leg is None:
                break
            total += leg
        else:
            if best is None or total < best.minutes:
                best = _Route(total, order)
    return best


def optimize(request: BasketRequest) -> BasketResult:
    """Best basket for the request. Deterministic: same input, byte-identical `to_json()`."""
    lam = request.effective_lambda
    ctx = PricingContext(
        shopping_date=request.shopping_date,
        loyalty_chain_ids=request.loyalty_chain_ids,
        coupon_codes=request.coupon_codes,
    )
    in_matrix = set(request.travel_times.store_ids)
    unknown = [s.store_id for s in request.stores if s.store_id not in in_matrix]
    if unknown:
        raise ValueError(f"stores without travel times: {unknown}")
    stores = sorted(request.stores, key=lambda s: s.store_id)
    by_id = {s.store_id: s for s in stores}

    # Best option of every line in every store, computed once.
    options: dict[str, dict[int, LineOption]] = {}
    for line in request.lines:
        per_store = {}
        for store in stores:
            option = cover_line(line, store, ctx, request.config)
            if option is not None:
                per_store[store.store_id] = option
        options[line.line_id] = per_store

    coverable = [line.line_id for line in request.lines if options[line.line_id]]

    best_key: tuple | None = None
    best_choice: tuple[tuple[int, ...], _Route, dict[str, int]] | None = None
    for size in range(1, min(request.max_stores, len(stores)) + 1):
        for subset in combinations(stores, size):
            ids = tuple(s.store_id for s in subset)
            assignment: dict[str, int] = {}
            cost = Decimal(0)
            for line_id in coverable:
                here = [
                    (options[line_id][sid].comparable_cost, sid)
                    for sid in ids
                    if sid in options[line_id]
                ]
                if here:
                    c, sid = min(here)
                    assignment[line_id] = sid
                    cost += c
            if set(assignment.values()) != set(ids):
                continue  # a store with nothing to buy is never worth visiting
            route = best_route(ids, request.travel_times, request.return_to_origin)
            if route is None:
                continue
            uncovered = len(coverable) - len(assignment)
            objective = cost + lam * route.minutes
            key = (uncovered, objective, size, route.minutes, ids)
            if best_key is None or key < best_key:
                best_key, best_choice = key, (ids, route, assignment)

    return _result(request, lam, by_id, options, best_choice)


def _result(
    request: BasketRequest,
    lam: Decimal,
    by_id: dict[int, Store],
    options: dict[str, dict[int, LineOption]],
    choice: tuple[tuple[int, ...], _Route, dict[str, int]] | None,
) -> BasketResult:
    route = choice[1] if choice else _Route(Decimal(0), ())
    assignment = choice[2] if choice else {}

    purchases = []
    for position, store_id in enumerate(route.order, start=1):
        lines = tuple(
            _line_purchase(line.line_id, line.canonical_id, options[line.line_id][store_id])
            for line in request.lines
            if assignment.get(line.line_id) == store_id
        )
        purchases.append(
            StorePurchase(
                store_id=store_id,
                chain_id=by_id[store_id].chain_id,
                position=position,
                lines=lines,
                subtotal=sum((lp.cost for lp in lines), Decimal("0.00")),
            )
        )

    missing = tuple(
        MissingLine(
            line.line_id,
            MissingReason.STORE_LIMIT if options[line.line_id] else MissingReason.NOT_AVAILABLE,
        )
        for line in request.lines
        if line.line_id not in assignment
    )
    total = sum((p.subtotal for p in purchases), Decimal("0.00"))
    comparable = sum((lp.comparable_cost for p in purchases for lp in p.lines), Decimal("0.0000"))
    return BasketResult(
        engine_version=ENGINE_VERSION,
        stores=tuple(purchases),
        total_cost=total,
        comparable_cost=comparable,
        minutes=route.minutes,
        lambda_per_minute=lam,
        objective=comparable + lam * route.minutes,
        priority_mode=request.priority_mode,
        max_stores=request.max_stores,
        return_to_origin=request.return_to_origin,
        missing=missing,
    )


def _line_purchase(line_id: str, canonical_id: int, option: LineOption) -> LinePurchase:
    return LinePurchase(
        line_id=line_id,
        canonical_id=canonical_id,
        base_unit=option.base_unit,
        rule=option.rule,
        quantity_requested=option.quantity_requested,
        quantity_bought=option.quantity_bought,
        cost=option.cost,
        comparable_cost=option.comparable_cost,
        packs=option.packs,
    )
