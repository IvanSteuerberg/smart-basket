"""Effective price: one test group per promotion mechanic and quantity (evaluation plan)."""

from datetime import date
from decimal import Decimal as D

import pytest

from smart_basket.optimizer import (
    PricingContext,
    Promotion,
    PromotionKind,
    Store,
    Target,
    TargetKind,
    VolumeTier,
    effective_price,
)
from tests.optimizer.helpers import DAY, product, promo

P = product(1, 10, "1.00", "1", brand_id=7, category_ids=frozenset({50, 5}))
CTX = PricingContext(DAY)


def cost(promotions, units, ctx=CTX, prod=P, zone_id=None, chain_id=1):
    store = Store(1, chain_id, (prod,), tuple(promotions), zone_id=zone_id)
    return effective_price(store, prod, units, ctx)


@pytest.mark.parametrize(
    ("units", "expected"),
    [(1, "1.00"), (2, "2.00"), (3, "2.00"), (4, "3.00"), (6, "4.00"), (7, "5.00")],
)
def test_three_for_two(units, expected):
    line = cost([promo(1, PromotionKind.NXM, 1, buy_n=3, pay_m=2)], units)
    assert line.cost == D(expected)
    assert (line.promotion is None) == (units < 3)


@pytest.mark.parametrize(
    ("units", "expected"),
    [(1, "1.00"), (2, "1.50"), (3, "2.50"), (4, "3.00"), (5, "4.00"), (7, "5.50")],
)
def test_second_unit_half_price_with_odd_quantities(units, expected):
    assert cost([promo(1, PromotionKind.SECOND_UNIT, 1, percent=D(50))], units).cost == D(expected)


def test_second_unit_free_is_two_for_one():
    assert cost([promo(1, PromotionKind.SECOND_UNIT, 1, percent=D(100))], 3).cost == D("2.00")


def test_second_unit_rounds_each_line_to_cents():
    prod = product(1, 10, "1.25", "1")
    line = cost([promo(1, PromotionKind.SECOND_UNIT, 1, percent=D(70))], 2, prod=prod)
    assert line.cost == D("1.63")  # 1.25 + 0.375 = 1.625, half up


def test_promo_price_and_percent_off():
    assert cost([promo(1, PromotionKind.PROMO_PRICE, 1, promo_price=D("0.79"))], 3).cost == D(
        "2.37"
    )
    assert cost([promo(1, PromotionKind.PERCENT_OFF, 1, percent=D(25))], 3).cost == D("2.25")


@pytest.mark.parametrize(
    ("units", "expected"), [(1, "1.00"), (2, "1.80"), (3, "2.70"), (4, "3.20"), (6, "4.80")]
)
def test_volume_tiers_use_the_highest_tier_reached(units, expected):
    tiers = (VolumeTier(2, percent=D(10)), VolumeTier(4, unit_price=D("0.80")))
    assert cost([promo(1, PromotionKind.VOLUME_TIER, 1, tiers=tiers)], units).cost == D(expected)


def test_loyalty_price_only_with_the_card():
    loyalty = promo(1, PromotionKind.LOYALTY_PRICE, 1, promo_price=D("0.70"), requires_loyalty=True)
    assert cost([loyalty], 2).cost == D("2.00")
    with_card = PricingContext(DAY, loyalty_chain_ids=frozenset({1}))
    line = cost([loyalty], 2, ctx=with_card)
    assert line.cost == D("1.40")
    assert line.promotion == loyalty
    other_chain_card = PricingContext(DAY, loyalty_chain_ids=frozenset({2}))
    assert cost([loyalty], 2, ctx=other_chain_card).cost == D("2.00")


def test_any_mechanic_can_require_the_card():
    nxm = promo(1, PromotionKind.NXM, 1, buy_n=2, pay_m=1, requires_loyalty=True)
    assert cost([nxm], 2).cost == D("2.00")
    assert cost([nxm], 2, ctx=PricingContext(DAY, frozenset({1}))).cost == D("1.00")


def test_coupon_only_when_used_and_never_below_zero():
    coupon = promo(1, PromotionKind.COUPON, 1, coupon_code="OTONO", amount=D("0.50"))
    assert cost([coupon], 2).cost == D("2.00")
    ctx = PricingContext(DAY, coupon_codes=frozenset({"OTONO"}))
    assert cost([coupon], 2, ctx=ctx).cost == D("1.50")
    big = promo(2, PromotionKind.COUPON, 1, coupon_code="OTONO", amount=D("5.00"))
    assert cost([big], 1, ctx=ctx).cost == D("0.00")
    pct = promo(3, PromotionKind.COUPON, 1, coupon_code="OTONO", percent=D(10))
    assert cost([pct], 3, ctx=ctx).cost == D("2.70")


def test_promotion_already_in_the_price_is_not_applied_again():
    included = promo(1, PromotionKind.PERCENT_OFF, 1, percent=D(30), applied_in_price=True)
    line = cost([included], 2)
    assert line.cost == D("2.00")
    assert line.promotion is None


def test_validity_is_inclusive_start_exclusive_end():
    p = promo(
        1, PromotionKind.PERCENT_OFF, 1, percent=D(50), valid_from=DAY, valid_to=date(2026, 11, 10)
    )
    assert cost([p], 1).cost == D("0.50")
    assert cost([p], 1, ctx=PricingContext(date(2026, 11, 9))).cost == D("0.50")
    assert cost([p], 1, ctx=PricingContext(date(2026, 11, 10))).cost == D("1.00")
    assert cost([p], 1, ctx=PricingContext(date(2026, 11, 2))).cost == D("1.00")


def test_zone_restriction():
    p = promo(1, PromotionKind.PERCENT_OFF, 1, percent=D(50), zone_ids=frozenset({3}))
    assert cost([p], 1, zone_id=3).cost == D("0.50")
    assert cost([p], 1, zone_id=4).cost == D("1.00")
    assert cost([p], 1, zone_id=None).cost == D("1.00")


@pytest.mark.parametrize(
    ("target", "hit"),
    [
        (Target(TargetKind.CANONICAL, 10), True),
        (Target(TargetKind.CANONICAL, 11), False),
        (Target(TargetKind.BRAND, 7), True),
        (Target(TargetKind.BRAND, 8), False),
        (Target(TargetKind.CATEGORY, 5), True),  # ancestor category
        (Target(TargetKind.CATEGORY, 6), False),
    ],
)
def test_targets(target, hit):
    p = Promotion(1, PromotionKind.PERCENT_OFF, (target,), date(2026, 1, 1), percent=D(50))
    assert (cost([p], 1).cost == D("0.50")) is hit


def test_no_stacking_best_mechanic_wins():
    three_for_two = promo(1, PromotionKind.NXM, 1, buy_n=3, pay_m=2)
    half_second = promo(2, PromotionKind.SECOND_UNIT, 1, percent=D(50))
    # 3 units: 3x2 = 2.00, second unit = 2.50 -> 3x2; 2 units: 3x2 n/a, second unit 1.50.
    assert cost([three_for_two, half_second], 3).promotion == three_for_two
    assert cost([three_for_two, half_second], 2).promotion == half_second
    assert cost([three_for_two, half_second], 3).cost == D("2.00")


def test_tie_break_by_priority_then_id():
    a = promo(5, PromotionKind.PERCENT_OFF, 1, percent=D(50))
    b = promo(3, PromotionKind.PROMO_PRICE, 1, promo_price=D("0.50"))
    c = promo(9, PromotionKind.PROMO_PRICE, 1, promo_price=D("0.50"), priority=1)
    assert cost([a, b], 1).promotion == b  # same priority: lower id
    assert cost([a, b, c], 1).promotion == c  # higher priority wins
    assert cost([c, b, a], 1).promotion == c  # input order does not matter


def test_a_promotion_that_saves_nothing_is_not_reported():
    useless = promo(1, PromotionKind.PROMO_PRICE, 1, promo_price=D("1.00"))
    assert cost([useless], 2).promotion is None


def test_invalid_promotions_are_rejected():
    with pytest.raises(ValueError, match="missing parameters"):
        promo(1, PromotionKind.NXM, 1, buy_n=2, pay_m=2)
    with pytest.raises(ValueError, match="missing parameters"):
        promo(1, PromotionKind.LOYALTY_PRICE, 1, promo_price=D(1))
    with pytest.raises(ValueError, match="percent"):
        promo(1, PromotionKind.PERCENT_OFF, 1, percent=D(120))
