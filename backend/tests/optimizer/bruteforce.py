"""Independent brute-force reference solver for the optimizer tests.

Written separately from the optimizer: promotions are evaluated unit by unit, pack mixes by
enumerating every count vector with `itertools.product`, and baskets by enumerating every
assignment of lines to stores, with routes over every permutation. Only the rules (decisions
0010 and 0013) are shared, not the code. Exact arithmetic with `Fraction`.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction

from smart_basket.optimizer import (
    BaseUnit,
    BasketRequest,
    Line,
    Product,
    Promotion,
    PromotionKind,
    Store,
    TargetKind,
    Unit,
)

TO_BASE = {
    Unit.UD: (BaseUnit.UD, Fraction(1)),
    Unit.KG: (BaseUnit.KG, Fraction(1)),
    Unit.G: (BaseUnit.KG, Fraction(1, 1000)),
    Unit.L: (BaseUnit.L, Fraction(1)),
    Unit.ML: (BaseUnit.L, Fraction(1, 1000)),
}


def cents(x: Fraction) -> int:
    """Round half up to an integer number of cents (x in euros, non-negative)."""
    return math.floor(x * 100 + Fraction(1, 2))


def promo_applies(p: Promotion, store: Store, prod: Product, req: BasketRequest) -> bool:
    if p.applied_in_price:
        return False
    day = req.shopping_date
    if day < p.valid_from or (p.valid_to is not None and day >= p.valid_to):
        return False
    if p.zone_ids and store.zone_id not in p.zone_ids:
        return False
    if p.requires_loyalty and store.chain_id not in req.loyalty_chain_ids:
        return False
    if p.kind is PromotionKind.COUPON and p.coupon_code not in req.coupon_codes:
        return False
    hits = {
        TargetKind.PRODUCT: prod.product_id,
        TargetKind.CANONICAL: prod.canonical_id,
        TargetKind.BRAND: prod.brand_id,
    }
    return any(
        (t.id in prod.category_ids) if t.kind is TargetKind.CATEGORY else hits[t.kind] == t.id
        for t in p.targets
    )


def unit_by_unit(p: Promotion, price: Fraction, n: int) -> int | None:
    """Cost in cents of n packs under p, simulated unit by unit; None if it does not apply."""
    k = p.kind
    if k in (PromotionKind.PROMO_PRICE, PromotionKind.LOYALTY_PRICE):
        return cents(Fraction(p.promo_price) * n)
    if k is PromotionKind.PERCENT_OFF:
        return cents(price * n * (1 - Fraction(p.percent) / 100))
    if k is PromotionKind.NXM:
        paid, free = Fraction(0), 0
        for i in range(n):
            group_end = (i // p.buy_n + 1) * p.buy_n
            if group_end <= n and i % p.buy_n >= p.pay_m:
                free += 1
            else:
                paid += price
        return cents(paid) if free else None
    if k is PromotionKind.SECOND_UNIT:
        if n < 2:
            return None
        total = sum(
            (price * (1 - Fraction(p.percent) / 100) if i % 2 == 1 else price for i in range(n)),
            Fraction(0),
        )
        return cents(total)
    if k is PromotionKind.VOLUME_TIER:
        tiers = [t for t in p.tiers if t.min_units <= n]
        if not tiers:
            return None
        t = max(tiers, key=lambda t: t.min_units)
        unit = (
            Fraction(t.unit_price)
            if t.unit_price is not None
            else price * (1 - Fraction(t.percent) / 100)
        )
        return cents(unit * n)
    if k is PromotionKind.COUPON:
        line = price * n
        if p.amount is not None:
            return cents(max(Fraction(0), line - Fraction(p.amount)))
        return cents(line * (1 - Fraction(p.percent) / 100))
    raise AssertionError(k)


def line_cents(store: Store, prod: Product, n: int, req: BasketRequest) -> int:
    price = Fraction(prod.price)
    best_cost, best_key = cents(price * n), (0, 0, 0)
    for p in store.promotions:
        if not promo_applies(p, store, prod, req):
            continue
        c = unit_by_unit(p, price, n)
        if c is None:
            continue
        key = (1, -p.priority, p.promotion_id)
        if (c, key) < (best_cost, best_key):
            best_cost, best_key = c, key
    return best_cost


def eligible(line: Line, store: Store) -> tuple[BaseUnit | None, list[Product]]:
    pr = line.preferences
    cands = [
        p
        for p in store.products
        if p.canonical_id == line.canonical_id
        and (pr.brand_id is None or p.brand_id == pr.brand_id)
        and (pr.private_label_ok or not p.is_private_label)
        and (pr.pack_quantity is None or p.net_quantity == pr.pack_quantity)
    ]
    if not cands:
        return None, []
    lb = TO_BASE[line.unit][0]
    present = {p.base_unit for p in cands}
    if lb in present:
        base = lb
    elif line.unit is Unit.UD:
        base = sorted(present, key=lambda u: u.value)[0]
    else:
        return None, []
    return base, [p for p in cands if p.base_unit is base]


def line_option(line: Line, store: Store, req: BasketRequest) -> Fraction | None:
    """Comparable cost (euros, rounded to 0.0001) of the line in the store, or None."""
    base, prods = eligible(line, store)
    if base is None:
        return None
    lb, factor = TO_BASE[line.unit]
    if lb is base:
        q = Fraction(line.quantity) * factor
    elif line.default_quantity is not None:
        q = Fraction(line.quantity) * Fraction(line.default_quantity)
    else:
        n = math.ceil(Fraction(line.quantity))
        return Fraction(min(line_cents(store, p, n, req) for p in prods), 100)
    sizes = [Fraction(p.net_quantity) for p in prods]

    def singles() -> Fraction:
        best = None
        for p, s in zip(prods, sizes, strict=True):
            n = max(1, math.ceil(q / s))
            c = line_cents(store, p, n, req)
            key = (c, n * s - q, p.product_id)
            best = key if best is None or key < best else best
        return Fraction(best[0], 100)

    if line.preferences.exact:
        return singles()

    cfg = req.config
    lo, hi = Fraction(cfg.band_min) * q, Fraction(cfg.band_max) * q
    ranges = [range(math.floor(hi / s) + 1) for s in sizes]
    cands = []
    for counts in itertools.product(*ranges):
        used = [i for i, c in enumerate(counts) if c]
        if not used or len(used) > cfg.max_distinct_products:
            continue
        total = sum((c * s for c, s in zip(counts, sizes, strict=True)), Fraction(0))
        # Same thousandth-of-unit grid as the optimizer's integer band limits.
        if not (math.ceil(lo * 1000) <= total * 1000 <= math.floor(hi * 1000)):
            continue
        cost = sum(line_cents(store, prods[i], counts[i], req) for i in used)
        key = tuple((prods[i].product_id, counts[i]) for i in used)
        cands.append((Fraction(cost, 100) / total, total, cost, key))
    if not cands:
        return singles()
    best_up = min(c[0] for c in cands)
    near = [c for c in cands if c[0] <= best_up * (1 + Fraction(cfg.near_tie))]
    reach = [c for c in near if c[1] >= q]
    if reach:
        chosen = min(reach, key=lambda c: (c[1] - q, c[2], c[3]))
    else:
        chosen = min(near, key=lambda c: (q - c[1], c[2], c[3]))
    comparable = chosen[0] * q
    return Fraction(math.floor(comparable * 10000 + Fraction(1, 2)), 10000)


def route_minutes(req: BasketRequest, used: tuple[int, ...]) -> Fraction | None:
    idx = {sid: i + 1 for i, sid in enumerate(req.travel_times.store_ids)}
    best = None
    for perm in itertools.permutations(used):
        path = [0, *(idx[s] for s in perm)] + ([0] if req.return_to_origin else [])
        legs = [req.travel_times.minutes[a][b] for a, b in itertools.pairwise(path)]
        if any(leg is None for leg in legs):
            continue
        t = sum((Fraction(leg) for leg in legs), Fraction(0))
        best = t if best is None or t < best else best
    return best


def option_table(req: BasketRequest) -> dict[str, dict[int, Fraction]]:
    """Comparable cost of every line in every store that sells it."""
    table = {
        line.line_id: {s.store_id: line_option(line, s, req) for s in req.stores}
        for line in req.lines
    }
    return {lid: {s: c for s, c in row.items() if c is not None} for lid, row in table.items()}


def solve(req: BasketRequest) -> tuple[int, Fraction]:
    """(uncovered lines, objective) of the best basket over every line-to-store
    assignment, ranked by objective + (cheapest comparable cost anywhere + margin) per line left
    out (decision 0013, point 11). A line is left out only if no visited store sells it."""
    lam = Fraction(req.effective_lambda)
    margin = Fraction(req.coverage_margin)
    table = option_table(req)
    coverable = [lid for lid, row in table.items() if row]
    choices = [[*sorted(table[lid]), None] for lid in coverable]
    best = None
    for assignment in itertools.product(*choices):
        used = tuple(sorted({s for s in assignment if s is not None}))
        if not used or len(used) > req.max_stores:
            continue
        if any(
            s is None and any(u in table[lid] for u in used)
            for lid, s in zip(coverable, assignment, strict=True)
        ):
            continue
        minutes = route_minutes(req, used)
        if minutes is None:
            continue
        cost = penalty = Fraction(0)
        for lid, s in zip(coverable, assignment, strict=True):
            if s is None:
                penalty += min(table[lid].values()) + margin
            else:
                cost += table[lid][s]
        uncovered = sum(1 for s in assignment if s is None)
        objective = cost + lam * minutes
        key = (objective + penalty, uncovered, objective)
        best = key if best is None or key < best else best
    return best[1:] if best is not None else (0, Fraction(0))


def separate_stop(
    req: BasketRequest, used: tuple[int, ...], line_id: str
) -> tuple[int, Fraction, Fraction] | None:
    """(store, extra minutes, comparable cost + lambda x extra minutes) of the cheapest store to
    add to the route of `used` for a line left out, ties to the lowest store id."""
    lam = Fraction(req.effective_lambda)
    base = route_minutes(req, used) if used else Fraction(0)
    best = None
    for store_id, cost in sorted(option_table(req)[line_id].items()):
        minutes = route_minutes(req, (*used, store_id))
        if minutes is None:
            continue
        extra = cost + lam * (minutes - base)
        if best is None or (extra, store_id) < (best[2], best[0]):
            best = (store_id, minutes - base, extra)
    return best
