"""Pack-covering rule of decision 0010 and the line rules of decision 0013."""

from decimal import Decimal as D

from smart_basket.optimizer import (
    BaseUnit,
    CoverRule,
    Line,
    LinePreferences,
    OptimizerConfig,
    PricingContext,
    PromotionKind,
    Store,
    Unit,
    cover_line,
)
from tests.optimizer.helpers import DAY, product, promo

CTX = PricingContext(DAY)
CFG = OptimizerConfig()


def cover(line, products, promotions=(), config=CFG):
    return cover_line(line, Store(1, 1, tuple(products), tuple(promotions)), CTX, config)


def packs(option):
    return [(p.product_id, p.packs) for p in option.packs]


# The two examples written in decision 0010: 1 kg requested, 400 g packs at 1.00 €.


def test_0010_without_promotion_three_packs_reach_the_quantity():
    option = cover(Line("y", 10, D(1), Unit.KG), [product(1, 10, "1.00", "0.4")])
    assert packs(option) == [(1, 3)]
    assert option.quantity_bought == D("1.2")
    assert option.cost == D("3.00")
    assert option.rule is CoverRule.COVER


def test_0010_second_unit_half_price_buys_two_packs():
    option = cover(
        Line("y", 10, D(1), Unit.KG),
        [product(1, 10, "1.00", "0.4")],
        [promo(1, PromotionKind.SECOND_UNIT, 1, percent=D(50))],
    )
    assert packs(option) == [(1, 2)]
    assert option.quantity_bought == D("0.8")
    assert option.cost == D("1.50")
    assert option.comparable_cost == D("1.8750")  # 1.875 €/kg x 1 kg
    assert option.packs[0].promotion_kind is PromotionKind.SECOND_UNIT


def test_grams_are_converted_to_the_base_unit():
    option = cover(Line("y", 10, D(1000), Unit.G), [product(1, 10, "1.00", "0.4")])
    assert packs(option) == [(1, 3)]


def test_lowest_price_per_unit_wins_outside_the_near_tie():
    small = product(1, 10, "1.00", "0.5")  # 2.00 €/kg
    big = product(2, 10, "1.70", "1")  # 1.70 €/kg
    assert packs(cover(Line("y", 10, D(1), Unit.KG), [small, big])) == [(2, 1)]


def test_near_tie_goes_to_the_one_reaching_the_quantity():
    # 800 g at 1.60 (2.000 €/kg) vs 1 kg at 2.08 (2.08 €/kg): within 5 %, so 1 kg.
    a = product(1, 10, "1.60", "0.8")
    b = product(2, 10, "2.08", "1")
    option = cover(Line("y", 10, D(1), Unit.KG), [a, b])
    assert packs(option) == [(2, 1)]
    # With a 3 % threshold 800 g is clearly cheaper and wins.
    tight = OptimizerConfig(near_tie=D("0.03"))
    assert packs(cover(Line("y", 10, D(1), Unit.KG), [a, b], config=tight)) == [(1, 1)]


def test_near_tie_without_reaching_goes_to_the_closest():
    a = product(1, 10, "1.60", "0.8")
    b = product(2, 10, "1.82", "0.9")  # 2.022 €/kg, near tie, closer to 1 kg
    assert packs(cover(Line("y", 10, D(1), Unit.KG), [a, b])) == [(2, 1)]


def test_thresholds_are_configurable():
    p = product(1, 10, "1.00", "0.4")
    # Band 100-110 %: no combination of 400 g packs fits, the fallback reaches 1 kg.
    narrow = OptimizerConfig(band_min=D(1), band_max=D("1.1"))
    option = cover(Line("y", 10, D(1), Unit.KG), [p], config=narrow)
    assert option.rule is CoverRule.FALLBACK
    assert packs(option) == [(1, 3)]


def test_mixing_two_formats():
    # 1.5 l requested: a 1 l and a 0.5 l bottle beat three 0.5 l or two 1 l bottles.
    big = product(1, 10, "0.80", "1", BaseUnit.L)
    small = product(2, 10, "0.40", "0.5", BaseUnit.L)
    option = cover(Line("w", 10, D("1.5"), Unit.L), [big, small])
    assert option.quantity_bought == D("1.5")
    assert option.cost == D("1.20")
    single = OptimizerConfig(max_distinct_products=1)
    assert len(cover(Line("w", 10, D("1.5"), Unit.L), [big, small], config=single).packs) == 1


def test_pack_count_uses_the_pack_count_field():
    six = product(1, 10, "5.40", "1", BaseUnit.L, pack_count=6)
    single = product(2, 10, "0.95", "1", BaseUnit.L)
    option = cover(Line("m", 10, D(6), Unit.L), [six, single])
    assert packs(option) == [(1, 1)]
    assert option.quantity_bought == D(6)


def test_units_of_a_weighed_product_use_the_default_quantity():
    milk = product(1, 10, "0.95", "1", BaseUnit.L)
    option = cover(Line("m", 10, D(6), Unit.UD, default_quantity=D(1)), [milk])
    assert option.rule is CoverRule.COVER
    assert packs(option) == [(1, 6)]


def test_units_without_default_quantity_buy_that_many_cheapest_packs():
    small = product(1, 10, "1.10", "0.25")
    big = product(2, 10, "2.50", "1")
    option = cover(Line("c", 10, D(2), Unit.UD), [small, big])
    assert option.rule is CoverRule.PACK_COUNT
    assert packs(option) == [(1, 2)]
    assert option.quantity_requested is None


def test_exact_brand_skips_the_band_and_reaches_the_quantity():
    cola_2l = product(1, 10, "1.90", "2", BaseUnit.L, brand_id=3)
    cola_15 = product(2, 10, "1.10", "1.5", BaseUnit.L, brand_id=3)
    store_brand = product(3, 10, "0.60", "2", BaseUnit.L, brand_id=4, is_private_label=True)
    line = Line("c", 10, D(2), Unit.L, LinePreferences(brand_id=3))
    option = cover(line, [cola_2l, cola_15, store_brand])
    assert option.rule is CoverRule.EXACT
    assert packs(option) == [(1, 1)]


def test_exact_format():
    a = product(1, 10, "1.00", "0.5", BaseUnit.L)
    b = product(2, 10, "1.20", "1", BaseUnit.L)
    line = Line("c", 10, D(1), Unit.L, LinePreferences(pack_quantity=D("0.5")))
    option = cover(line, [a, b])
    assert packs(option) == [(1, 2)]
    assert option.rule is CoverRule.EXACT


def test_private_label_refused():
    pl = product(1, 10, "0.50", "1", is_private_label=True)
    brand = product(2, 10, "1.50", "1", brand_id=9)
    line = Line("c", 10, D(1), Unit.KG, LinePreferences(private_label_ok=False))
    assert packs(cover(line, [pl, brand])) == [(2, 1)]


def test_no_eligible_product():
    assert cover(Line("c", 11, D(1), Unit.KG), [product(1, 10, "1", "1")]) is None
    assert cover(Line("c", 10, D(1), Unit.L), [product(1, 10, "1", "1")]) is None
