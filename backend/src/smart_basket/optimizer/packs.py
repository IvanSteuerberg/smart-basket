"""Covering a line's quantity with a store's packs (decision 0010, details in decision 0013).

Quantities are handled internally as integers in thousandths of the base unit (grams,
millilitres, thousandths of a unit) and costs as integer cents, so comparisons of price per
base unit are exact cross-multiplications.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from fractions import Fraction

from smart_basket.optimizer.models import (
    UNIT_TO_BASE,
    BaseUnit,
    CoverRule,
    Line,
    OptimizerConfig,
    PackPurchase,
    Product,
    Store,
    Unit,
)
from smart_basket.optimizer.pricing import PricedLine, PricingContext, candidate_promotions
from smart_basket.optimizer.pricing import best_price as price_with

MILLI = Decimal(1000)
COMPARABLE_STEP = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class LineOption:
    """The best way to buy one line in one store."""

    store_id: int
    rule: CoverRule
    base_unit: BaseUnit
    quantity_requested: Decimal | None
    quantity_bought: Decimal
    cost: Decimal
    comparable_cost: Decimal
    packs: tuple[PackPurchase, ...]


def _milli(q: Decimal) -> int:
    return max(1, int((q * MILLI).to_integral_value(rounding=ROUND_HALF_UP)))


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


class _Priced:
    """Lazily priced pack counts of one product in one store."""

    __slots__ = ("_cache", "_promos", "product", "size")

    def __init__(self, product: Product, store: Store, ctx: PricingContext) -> None:
        self.product = product
        self.size = _milli(product.net_quantity)
        self._promos = candidate_promotions(store, product, ctx)
        self._cache: dict[int, tuple[int, PricedLine]] = {}

    def cost(self, units: int) -> int:
        return self.priced(units)[0]

    def priced(self, units: int) -> tuple[int, PricedLine]:
        hit = self._cache.get(units)
        if hit is None:
            line = price_with(self.product, units, self._promos)
            hit = self._cache[units] = (_cents(line.cost), line)
        return hit


def eligible_products(line: Line, store: Store) -> tuple[BaseUnit | None, list[Product]]:
    """Products of the store that can satisfy the line, and the base unit they share."""
    prefs = line.preferences
    products = [
        p
        for p in store.products
        if p.canonical_id == line.canonical_id
        and (prefs.brand_id is None or p.brand_id == prefs.brand_id)
        and (prefs.private_label_ok or not p.is_private_label)
        and (prefs.pack_quantity is None or p.net_quantity == prefs.pack_quantity)
    ]
    if not products:
        return None, []
    line_base = UNIT_TO_BASE[line.unit][0]
    units_present = {p.base_unit for p in products}
    if line_base in units_present:
        base = line_base
    elif line.unit is Unit.UD:
        base = min(units_present, key=lambda u: u.value)
    else:
        return None, []
    return base, sorted((p for p in products if p.base_unit == base), key=lambda p: p.product_id)


def cover_line(
    line: Line, store: Store, ctx: PricingContext, config: OptimizerConfig
) -> LineOption | None:
    """Best purchase of `line` in `store`, or None if the store has no eligible product."""
    base, products = eligible_products(line, store)
    if base is None:
        return None
    priced = [_Priced(p, store, ctx) for p in products]
    line_base, factor = UNIT_TO_BASE[line.unit]

    if line_base is base:
        requested = line.quantity * factor
    elif line.default_quantity is not None:  # units of a product sold by weight or volume
        requested = line.quantity * line.default_quantity
    else:
        return _pack_count(line, store, base, priced)

    if line.preferences.exact:
        return _exact(store, base, requested, priced)
    return _cover(store, base, requested, priced, config) or _fallback(
        store, base, requested, priced
    )


# Rules ----------------------------------------------------------------------


def _option(
    store: Store,
    rule: CoverRule,
    base: BaseUnit,
    requested: Decimal | None,
    chosen: list[tuple[_Priced, int]],
    comparable: Decimal | None = None,
) -> LineOption:
    packs = []
    for item, units in sorted(chosen, key=lambda c: c[0].product.product_id):
        _, line = item.priced(units)
        packs.append(
            PackPurchase(
                product_id=item.product.product_id,
                packs=units,
                quantity=item.product.net_quantity * units,
                cost=line.cost,
                promotion_id=line.promotion.promotion_id if line.promotion else None,
                promotion_kind=line.promotion.kind if line.promotion else None,
            )
        )
    cost = sum((p.cost for p in packs), Decimal("0.00"))
    return LineOption(
        store_id=store.store_id,
        rule=rule,
        base_unit=base,
        quantity_requested=requested,
        quantity_bought=sum((p.quantity for p in packs), Decimal(0)),
        cost=cost,
        comparable_cost=(cost if comparable is None else comparable).quantize(COMPARABLE_STEP),
        packs=tuple(packs),
    )


def _cheapest_single(
    priced: list[_Priced], units_for: dict[int, int], target: int | None
) -> tuple[_Priced, int]:
    """Lowest cost; ties to the least excess over `target`, then the lowest product id."""

    def key(item: _Priced) -> tuple[int, int, int]:
        units = units_for[item.product.product_id]
        excess = units * item.size - target if target is not None else 0
        return (item.cost(units), excess, item.product.product_id)

    best = min(priced, key=key)
    return best, units_for[best.product.product_id]


def _pack_count(line: Line, store: Store, base: BaseUnit, priced: list[_Priced]) -> LineOption:
    units = int(line.quantity.to_integral_value(rounding=ROUND_CEILING))
    best, n = _cheapest_single(priced, {p.product.product_id: units for p in priced}, None)
    return _option(store, CoverRule.PACK_COUNT, base, None, [(best, n)])


def _exact(store: Store, base: BaseUnit, requested: Decimal, priced: list[_Priced]) -> LineOption:
    target = _milli(requested)
    units = {p.product.product_id: max(1, _ceil_div(target, p.size)) for p in priced}
    best, n = _cheapest_single(priced, units, target)
    return _option(store, CoverRule.EXACT, base, requested, [(best, n)])


def _fallback(
    store: Store, base: BaseUnit, requested: Decimal, priced: list[_Priced]
) -> LineOption:
    target = _milli(requested)
    units = {p.product.product_id: max(1, _ceil_div(target, p.size)) for p in priced}
    best, n = _cheapest_single(priced, units, target)
    return _option(store, CoverRule.FALLBACK, base, requested, [(best, n)])


def _combinations(
    priced: list[_Priced], lo: int, hi: int, max_distinct: int
) -> Iterator[tuple[int, int, tuple[tuple[int, int], ...]]]:
    """(total, cost, ((index, units), ...)) for every mix within [lo, hi]."""

    def walk(start: int, left: int, total: int, cost: int, chosen: tuple[tuple[int, int], ...]):
        for i in range(start, len(priced)):
            item = priced[i]
            for units in range(1, (hi - total) // item.size + 1):
                new_total = total + units * item.size
                new_cost = cost + item.cost(units)
                new_chosen = (*chosen, (i, units))
                if new_total >= lo:
                    yield new_total, new_cost, new_chosen
                if left > 1:
                    yield from walk(i + 1, left - 1, new_total, new_cost, new_chosen)

    yield from walk(0, max_distinct, 0, 0, ())


def _cover(
    store: Store,
    base: BaseUnit,
    requested: Decimal,
    priced: list[_Priced],
    config: OptimizerConfig,
) -> LineOption | None:
    target = _milli(requested)
    lo = int((config.band_min * target).to_integral_value(rounding=ROUND_CEILING))
    hi = int((config.band_max * target).to_integral_value(rounding=ROUND_FLOOR))
    candidates = list(_combinations(priced, lo, hi, config.max_distinct_products))
    if not candidates:
        return None

    # Lowest price per base unit: cost_a / total_a < cost_b / total_b, compared exactly.
    best_total, best_cost, _ = candidates[0]
    for total, cost, _ in candidates[1:]:
        if cost * best_total < best_cost * total:
            best_total, best_cost = total, cost

    tie = Fraction(1) + Fraction(config.near_tie)
    near = [
        c
        for c in candidates
        if c[1] * best_total * tie.denominator <= best_cost * c[0] * tie.numerator
    ]

    def product_key(c: tuple[int, int, tuple[tuple[int, int], ...]]) -> tuple[tuple[int, int], ...]:
        return tuple((priced[i].product.product_id, units) for i, units in c[2])

    reaching = [c for c in near if c[0] >= target]
    if reaching:
        total, cost, chosen = min(reaching, key=lambda c: (c[0] - target, c[1], product_key(c)))
    else:
        total, cost, chosen = min(near, key=lambda c: (target - c[0], c[1], product_key(c)))

    comparable = Decimal(cost * target) / Decimal(total) / 100
    comparable = comparable.quantize(COMPARABLE_STEP, rounding=ROUND_HALF_UP)
    return _option(
        store,
        CoverRule.COVER,
        base,
        requested,
        [(priced[i], units) for i, units in chosen],
        comparable,
    )
