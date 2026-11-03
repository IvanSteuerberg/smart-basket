"""Builders of synthetic optimizer inputs for the tests (no real data)."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

from smart_basket.optimizer import (
    BaseUnit,
    BasketRequest,
    Line,
    Product,
    Promotion,
    PromotionKind,
    Store,
    Target,
    TargetKind,
    TravelTimes,
    Unit,
)

D = Decimal
DAY = date(2026, 11, 3)
UNITS_BY_BASE = {BaseUnit.KG: Unit.KG, BaseUnit.L: Unit.L, BaseUnit.UD: Unit.UD}


def product(
    pid: int, canonical: int, price: str, size: str, unit: BaseUnit | str = BaseUnit.KG, **kw
) -> Product:
    return Product(pid, canonical, D(price), D(size), BaseUnit(unit), **kw)


def promo(pid: int, kind: PromotionKind, target_product: int, **kw) -> Promotion:
    kw.setdefault("valid_from", date(2026, 1, 1))
    return Promotion(pid, kind, (Target(TargetKind.PRODUCT, target_product),), **kw)


def grid_matrix(origin: tuple[int, int], points: dict[int, tuple[int, int]]) -> TravelTimes:
    """Manhattan minutes on an integer grid: a metric, so the triangle inequality holds."""
    ids = tuple(sorted(points))
    nodes = [origin, *(points[i] for i in ids)]
    minutes = tuple(tuple(D(abs(a[0] - b[0]) + abs(a[1] - b[1])) for b in nodes) for a in nodes)
    return TravelTimes(ids, minutes)


def random_instance(
    rng: random.Random,
    n_lines: int,
    n_stores: int,
    max_products: int = 2,
    promo_rate: float = 0.4,
    availability: float = 0.8,
    **request_kw,
) -> BasketRequest:
    """Random small instance: products of 1-3 sizes, random promotions, grid travel times."""
    kinds = list(PromotionKind)
    lines = []
    canon_unit = {}
    for i in range(n_lines):
        base = rng.choice([BaseUnit.KG, BaseUnit.L, BaseUnit.UD])
        canon_unit[i] = base
        qty = (
            D(rng.choice(["0.5", "1", "1.5", "2", "3"]))
            if base is not BaseUnit.UD
            else D(rng.choice([1, 2, 4, 6, 12]))
        )
        lines.append(Line(f"L{i}", i, qty, UNITS_BY_BASE[base]))
    stores = []
    pid = 0
    promo_id = 0
    for s in range(n_stores):
        products, promotions = [], []
        for i in range(n_lines):
            if rng.random() > availability:
                continue
            for _ in range(rng.randint(1, max_products)):
                pid += 1
                base = canon_unit[i]
                size = (
                    rng.choice(["0.25", "0.4", "0.5", "1", "2"])
                    if base is not BaseUnit.UD
                    else str(rng.choice([1, 4, 6, 12]))
                )
                price = D(rng.randint(50, 600)) / 100
                products.append(
                    Product(pid, i, price, D(size), base, pack_count=rng.choice([1, 1, 1, 2]))
                )
                if rng.random() < promo_rate:
                    promo_id += 1
                    promotions.append(_random_promo(rng, promo_id, pid, rng.choice(kinds), price))
        stores.append(Store(100 + s, 1 + s % 3, tuple(products), tuple(promotions)))
    points = {100 + s: (rng.randint(-10, 10), rng.randint(-10, 10)) for s in range(n_stores)}
    request_kw.setdefault("shopping_date", DAY)
    request_kw.setdefault("loyalty_chain_ids", frozenset({1}))
    request_kw.setdefault("coupon_codes", frozenset({"CUPON"}))
    return BasketRequest(tuple(lines), tuple(stores), grid_matrix((0, 0), points), **request_kw)


def _random_promo(
    rng: random.Random, promo_id: int, pid: int, kind: PromotionKind, price: Decimal
) -> Promotion:
    from smart_basket.optimizer import VolumeTier

    kw: dict = {"priority": rng.randint(0, 2), "applied_in_price": rng.random() < 0.1}
    match kind:
        case PromotionKind.PROMO_PRICE:
            kw["promo_price"] = (price * D("0.8")).quantize(D("0.01"))
        case PromotionKind.LOYALTY_PRICE:
            kw["promo_price"] = (price * D("0.85")).quantize(D("0.01"))
            kw["requires_loyalty"] = True
        case PromotionKind.PERCENT_OFF:
            kw["percent"] = D(rng.choice([10, 25, 33]))
        case PromotionKind.NXM:
            n = rng.choice([2, 3, 4])
            kw["buy_n"], kw["pay_m"] = n, n - 1
        case PromotionKind.SECOND_UNIT:
            kw["percent"] = D(rng.choice([50, 70, 100]))
        case PromotionKind.VOLUME_TIER:
            kw["tiers"] = (VolumeTier(2, percent=D(10)), VolumeTier(4, percent=D(20)))
        case PromotionKind.COUPON:
            kw["coupon_code"] = "CUPON"
            kw["amount"] = D("0.50")
    return promo(promo_id, kind, pid, **kw)
