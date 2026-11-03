"""Effective price of a line in a store (decision 0007, point 6; data model "Effective price").

`effective_price` takes a product with its observed price on the shopping date, the store's
promotions, the number of packs and the buyer's context, and returns the line cost with the
best single mechanic (no stacking). Pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from smart_basket.optimizer.models import Product, Promotion, PromotionKind, Store, TargetKind

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def round_money(value: Decimal) -> Decimal:
    """Round to cents, half up, as tills do per line."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class PricingContext:
    shopping_date: date
    loyalty_chain_ids: frozenset[int] = frozenset()
    coupon_codes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PricedLine:
    cost: Decimal
    promotion: Promotion | None


def matches_target(promotion: Promotion, product: Product) -> bool:
    for target in promotion.targets:
        if target.kind is TargetKind.PRODUCT and target.id == product.product_id:
            return True
        if target.kind is TargetKind.CANONICAL and target.id == product.canonical_id:
            return True
        if target.kind is TargetKind.CATEGORY and target.id in product.category_ids:
            return True
        if target.kind is TargetKind.BRAND and target.id == product.brand_id:
            return True
    return False


def candidate_promotions(store: Store, product: Product, ctx: PricingContext) -> list[Promotion]:
    """Promotions that can apply to `product` in `store` on the shopping date, best first.

    Excluded: promotions already included in the observed price, out of validity, for other
    zones, needing a loyalty card the buyer lacks, or a coupon the buyer does not use.
    Order: higher `priority` first, then lower id (the stable tie-break).
    """
    found = []
    for promo in store.promotions:
        if promo.applied_in_price or not promo.is_valid_on(ctx.shopping_date):
            continue
        if promo.zone_ids and store.zone_id not in promo.zone_ids:
            continue
        if promo.requires_loyalty and store.chain_id not in ctx.loyalty_chain_ids:
            continue
        if promo.kind is PromotionKind.COUPON and promo.coupon_code not in ctx.coupon_codes:
            continue
        if matches_target(promo, product):
            found.append(promo)
    found.sort(key=lambda p: (-p.priority, p.promotion_id))
    return found


def mechanic_cost(promo: Promotion, price: Decimal, units: int) -> Decimal | None:
    """Cost of `units` packs at base `price` under one mechanic, or None if it does not apply."""
    if units <= 0:
        return Decimal(0)
    match promo.kind:
        case PromotionKind.PROMO_PRICE | PromotionKind.LOYALTY_PRICE:
            assert promo.promo_price is not None
            return round_money(promo.promo_price * units)
        case PromotionKind.PERCENT_OFF:
            assert promo.percent is not None
            return round_money(price * units * (HUNDRED - promo.percent) / HUNDRED)
        case PromotionKind.NXM:
            assert promo.buy_n is not None
            assert promo.pay_m is not None
            free = (units // promo.buy_n) * (promo.buy_n - promo.pay_m)
            if free == 0:
                return None
            return round_money(price * (units - free))
        case PromotionKind.SECOND_UNIT:
            assert promo.percent is not None
            pairs, single = divmod(units, 2)
            if pairs == 0:
                return None
            pair_price = price * (2 - promo.percent / HUNDRED)
            return round_money(pair_price * pairs + price * single)
        case PromotionKind.VOLUME_TIER:
            reached = [t for t in promo.tiers if t.min_units <= units]
            if not reached:
                return None
            tier = max(reached, key=lambda t: t.min_units)
            if tier.unit_price is not None:
                return round_money(tier.unit_price * units)
            assert tier.percent is not None
            return round_money(price * units * (HUNDRED - tier.percent) / HUNDRED)
        case PromotionKind.COUPON:
            line = price * units
            if promo.amount is not None:
                return round_money(max(Decimal(0), line - promo.amount))
            assert promo.percent is not None
            return round_money(line * (HUNDRED - promo.percent) / HUNDRED)
    raise AssertionError(promo.kind)  # pragma: no cover


def best_price(product: Product, units: int, promotions: list[Promotion]) -> PricedLine:
    """Lowest line cost among no promotion and each candidate (already in tie-break order).

    A promotion must be strictly cheaper to win, so ties keep the plain price (simpler to
    explain) or the earlier promotion in priority order.
    """
    best = PricedLine(round_money(product.price * units), None)
    for promo in promotions:
        cost = mechanic_cost(promo, product.price, units)
        if cost is not None and cost < best.cost:
            best = PricedLine(cost, promo)
    return best


def effective_price(store: Store, product: Product, units: int, ctx: PricingContext) -> PricedLine:
    """Line cost of `units` packs of `product` in `store` for the buyer in `ctx`."""
    return best_price(product, units, candidate_promotions(store, product, ctx))
