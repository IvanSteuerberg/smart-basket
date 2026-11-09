"""Basket optimizer (decision 0002, layer 3; FR-13; rules in decision 0013).

Exhaustive search over store subsets of size <= max_stores among the candidates. Within a
subset each line goes to its cheapest store (comparable cost), and the visiting order is the
fastest permutation. Objective: comparable cost + lambda x minutes. A line that some candidate
store sells but no store of the subset does is left out at the price of its lowest comparable
cost in any store plus the coverage margin (point 11). Subsets are ranked by (objective + that
price of the lines left out, lines left out, stores, minutes, store ids), so the search is
deterministic. Each line left out is reported with the store where it is cheapest to add.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations, pairwise, permutations

from smart_basket.optimizer.models import (
    BasketRequest,
    BasketResult,
    Line,
    LinePurchase,
    MissingLine,
    MissingReason,
    SeparateStop,
    Store,
    StorePurchase,
    TravelTimes,
)
from smart_basket.optimizer.packs import LineOption, cover_line
from smart_basket.optimizer.pricing import PricingContext

#: Version of the optimizer and effective-price rules; stored with each recommendation
#: (NFR-03, NFR-05). Bump it whenever the same input could give a different basket.
ENGINE_VERSION = "basket-engine/1.1.0"


@dataclass(frozen=True, slots=True)
class _Route:
    minutes: Decimal
    order: tuple[int, ...]


def best_route(
    store_ids: tuple[int, ...], travel: TravelTimes, return_to_origin: bool
) -> _Route | None:
    """Fastest visiting order of `store_ids` from the origin (index 0), or None if unreachable.

    Every permutation is checked (at most 3! = 6 for a plan, 4! = 24 when a separate stop is
    added to it). Ties go to the lexicographically smallest order of store ids.
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
    # A line left out will be bought elsewhere: it costs its lowest comparable cost in any
    # store plus the coverage margin, so plans compare on detours, not on what is bought.
    left_out = {
        line_id: min(o.comparable_cost for o in options[line_id].values()) + request.coverage_margin
        for line_id in coverable
    }

    best_key: tuple | None = None
    best_choice: tuple[tuple[int, ...], _Route, dict[str, int]] | None = None
    for size in range(1, min(request.max_stores, len(stores)) + 1):
        for subset in combinations(stores, size):
            ids = tuple(s.store_id for s in subset)
            assignment: dict[str, int] = {}
            cost = penalty = Decimal(0)
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
                else:
                    penalty += left_out[line_id]
            if set(assignment.values()) != set(ids):
                continue  # a store with nothing to buy is never worth visiting
            route = best_route(ids, request.travel_times, request.return_to_origin)
            if route is None:
                continue
            uncovered = len(coverable) - len(assignment)
            objective = cost + lam * route.minutes
            key = (objective + penalty, uncovered, size, route.minutes, ids)
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

    missing = []
    for line in request.lines:
        if line.line_id in assignment:
            continue
        if not options[line.line_id]:
            missing.append(MissingLine(line.line_id, MissingReason.NOT_AVAILABLE))
            continue
        stop = _separate_stop(request, lam, by_id, line, options[line.line_id], route)
        reason = MissingReason.UNREACHABLE if stop is None else MissingReason.SEPARATE_STOP
        missing.append(MissingLine(line.line_id, reason, stop))
    total = sum((p.subtotal for p in purchases), Decimal("0.00"))
    comparable = sum((lp.comparable_cost for p in purchases for lp in p.lines), Decimal("0.0000"))
    return BasketResult(
        engine_version=ENGINE_VERSION,
        stores=tuple(purchases),
        total_cost=total,
        comparable_cost=comparable,
        minutes=route.minutes,
        lambda_per_minute=lam,
        coverage_margin=request.coverage_margin,
        objective=comparable + lam * route.minutes,
        priority_mode=request.priority_mode,
        max_stores=request.max_stores,
        return_to_origin=request.return_to_origin,
        missing=tuple(missing),
    )


def _separate_stop(
    request: BasketRequest,
    lam: Decimal,
    by_id: dict[int, Store],
    line: Line,
    per_store: dict[int, LineOption],
    route: _Route,
) -> SeparateStop | None:
    """Store where a line left out is cheapest to add to today's route, or None if none can be.

    Each store that sells the line is re-routed with the chosen stores; the lowest comparable
    cost + lambda x extra minutes wins, ties to the lowest store id.
    """
    best: tuple[Decimal, int, Decimal] | None = None
    for store_id in sorted(per_store):
        detour = best_route(
            (*route.order, store_id), request.travel_times, request.return_to_origin
        )
        if detour is None:
            continue
        extra_minutes = detour.minutes - route.minutes
        extra = per_store[store_id].comparable_cost + lam * extra_minutes
        if best is None or (extra, store_id) < best[:2]:
            best = (extra, store_id, extra_minutes)
    if best is None:
        return None
    extra, store_id, extra_minutes = best
    return SeparateStop(
        store_id=store_id,
        chain_id=by_id[store_id].chain_id,
        purchase=_line_purchase(line.line_id, line.canonical_id, per_store[store_id]),
        extra_minutes=extra_minutes,
        extra_objective=extra,
        exceeds_max_stores=len(route.order) + 1 > request.max_stores,
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
