"""Basket optimizer: brute force, determinism, lambda sweep, coverage margin and separate stops,
missing lines, routes, timing."""

import itertools
import random
import time
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction

import pytest

from smart_basket.optimizer import (
    ENGINE_VERSION,
    BasketRequest,
    Line,
    MissingReason,
    PriorityMode,
    Store,
    TravelTimes,
    Unit,
    best_route,
    optimize,
)
from tests.optimizer import bruteforce
from tests.optimizer.helpers import DAY, grid_matrix, product, random_instance


def request(lines, stores, points, **kw):
    return BasketRequest(
        tuple(lines), tuple(stores), grid_matrix((0, 0), points), shopping_date=DAY, **kw
    )


# Brute force ---------------------------------------------------------------


@pytest.mark.parametrize("seed", range(300))
def test_matches_independent_brute_force(seed):
    rng = random.Random(seed)
    req = random_instance(
        rng,
        n_lines=rng.randint(1, 5),
        n_stores=rng.randint(1, 5),
        max_products=rng.choice([1, 2, 3]),
        max_stores=rng.randint(1, 3),
        lambda_per_minute=D(rng.choice(["0", "0.05", "0.15", "0.40", "2"])),
        return_to_origin=rng.random() < 0.8,
        coverage_margin=D(rng.choice(["0", "0.50", "3.00", "1000000"])),
    )
    result = optimize(req)
    uncovered, objective = bruteforce.solve(req)
    assert sum(m.reason is MissingReason.SEPARATE_STOP for m in result.missing) == uncovered
    assert Fraction(result.objective) == objective
    # Each separate stop is the cheapest store to add to the chosen route.
    for m in result.missing:
        if m.reason is MissingReason.SEPARATE_STOP:
            store_id, extra_minutes, extra = bruteforce.separate_stop(
                req, result.visiting_order, m.line_id
            )
            assert m.stop.store_id == store_id
            assert Fraction(m.stop.extra_minutes) == extra_minutes
            assert Fraction(m.stop.extra_objective) == extra
            assert m.stop.exceeds_max_stores == (len(result.stores) == req.max_stores)
        else:
            assert m.reason is MissingReason.NOT_AVAILABLE
            assert m.stop is None
    # Internal consistency of the result.
    assert result.total_cost == sum(s.subtotal for s in result.stores)
    assert len(result.stores) <= req.max_stores
    assert all(s.lines for s in result.stores)
    assert result.engine_version == ENGINE_VERSION


# Determinism ---------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_same_input_gives_byte_identical_output(seed):
    req = random_instance(random.Random(seed), n_lines=8, n_stores=6, max_products=3)
    first = optimize(req).to_json()
    again = optimize(req).to_json()
    rebuilt = optimize(
        random_instance(random.Random(seed), n_lines=8, n_stores=6, max_products=3)
    ).to_json()
    assert first == again == rebuilt


@pytest.mark.parametrize("seed", range(10))
def test_separate_stops_are_deterministic(seed):
    req = random_instance(
        random.Random(seed), n_lines=8, n_stores=6, max_products=3, availability=0.4, max_stores=1
    )
    first = optimize(req)
    assert any(m.reason is MissingReason.SEPARATE_STOP for m in first.missing)
    rng = random.Random(seed + 2000)
    stores = []
    for s in req.stores:
        products, promos = list(s.products), list(s.promotions)
        rng.shuffle(products)
        rng.shuffle(promos)
        stores.append(replace(s, products=tuple(products), promotions=tuple(promos)))
    rng.shuffle(stores)
    # The same matrix with its stores in another order.
    tt = req.travel_times
    perm = list(range(len(tt.store_ids)))
    rng.shuffle(perm)
    nodes = [0, *(i + 1 for i in perm)]
    matrix = TravelTimes(
        tuple(tt.store_ids[i] for i in perm),
        tuple(tuple(tt.minutes[a][b] for b in nodes) for a in nodes),
    )
    shuffled = replace(req, stores=tuple(stores), travel_times=matrix)
    assert first.to_json() == optimize(req).to_json() == optimize(shuffled).to_json()


@pytest.mark.parametrize("seed", range(10))
def test_store_and_product_order_does_not_matter(seed):
    req = random_instance(random.Random(seed), n_lines=6, n_stores=5, max_products=3)
    rng = random.Random(seed + 1000)
    stores = []
    for s in req.stores:
        products, promos = list(s.products), list(s.promotions)
        rng.shuffle(products)
        rng.shuffle(promos)
        stores.append(replace(s, products=tuple(products), promotions=tuple(promos)))
    rng.shuffle(stores)
    assert optimize(req).to_json() == optimize(replace(req, stores=tuple(stores))).to_json()


# Lambda sweep --------------------------------------------------------------

LAMBDAS = [
    D(x)
    for x in ["0", "0.01", "0.05", "0.1", "0.15", "0.25", "0.4", "0.75", "1.5", "3", "10", "1000"]
]


@pytest.mark.parametrize("seed", range(40))
def test_lambda_sweep_minutes_never_increase_and_cost_never_decreases(seed):
    base = random_instance(
        random.Random(seed), n_lines=6, n_stores=6, max_products=2, availability=1.0
    )
    results = [optimize(replace(base, lambda_per_minute=lam)) for lam in LAMBDAS]
    for a, b in itertools.pairwise(results):
        assert b.minutes <= a.minutes
        assert b.comparable_cost >= a.comparable_cost


@pytest.mark.parametrize("seed", range(40))
def test_lambda_sweep_with_lines_left_out(seed):
    """With lines left out the exchange argument still holds for the ranked value: minutes never
    increase and comparable cost + price of the lines left out never decreases. Comparable cost
    alone never decreases between two lambdas that leave out the same lines."""
    base = random_instance(
        random.Random(seed), n_lines=6, n_stores=6, max_products=2, availability=0.5
    )
    table = bruteforce.option_table(base)
    margin = Fraction(base.coverage_margin)

    def ranked_cost(res):
        return Fraction(res.comparable_cost) + sum(
            (
                min(table[m.line_id].values()) + margin
                for m in res.missing
                if m.reason is MissingReason.SEPARATE_STOP
            ),
            Fraction(0),
        )

    results = [optimize(replace(base, lambda_per_minute=lam)) for lam in LAMBDAS]
    for a, b in itertools.pairwise(results):
        assert b.minutes <= a.minutes
        assert ranked_cost(b) >= ranked_cost(a)
        if [m.line_id for m in a.missing] == [m.line_id for m in b.missing]:
            assert b.comparable_cost >= a.comparable_cost


@pytest.mark.parametrize("seed", range(40))
def test_lambda_sweep_extremes(seed):
    base = random_instance(
        random.Random(seed), n_lines=5, n_stores=6, max_products=2, availability=1.0
    )
    cheapest = optimize(replace(base, lambda_per_minute=D(0)))
    # lambda = 0: the cheapest basket within max stores (brute force over cost only).
    assert (
        Fraction(cheapest.comparable_cost)
        == bruteforce.solve(replace(base, lambda_per_minute=D(0)))[1]
    )
    # Very high lambda: the nearest single store (every store sells every line here).
    nearest = optimize(replace(base, lambda_per_minute=D(1000)))
    single_trips = {
        s.store_id: best_route((s.store_id,), base.travel_times, True).minutes for s in base.stores
    }
    assert len(nearest.stores) == 1
    assert nearest.minutes == min(single_trips.values())


def test_store_count_follows_lambda_on_a_typical_case():
    # Each of A, B and C is cheap for one line; N, next to the origin, is dear for all.
    lines = [Line(f"L{i}", i, D(1), Unit.UD) for i in range(3)]
    special = [
        Store(
            sid,
            sid,
            tuple(
                product(10 * sid + i, i, "1.00" if i == sid - 1 else "3.00", "1", unit="ud")
                for i in range(3)
            ),
        )
        for sid in (1, 2, 3)
    ]
    near = Store(4, 4, tuple(product(40 + i, i, "2.50", "1", unit="ud") for i in range(3)))
    points = {1: (10, 0), 2: (0, 10), 3: (-10, 0), 4: (1, 0)}
    counts = []
    for lam in sorted([*LAMBDAS, D("0.075")]):
        res = optimize(request(lines, [*special, near], points, lambda_per_minute=lam))
        counts.append(len(res.stores))
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 3
    assert 2 in counts
    assert counts[-1] == 1


def test_store_count_can_rise_with_lambda():
    """Documented counter-example (decision 0013): far cheap store -> two near ones -> one."""
    lines = [Line("a", 1, D(1), Unit.UD), Line("b", 2, D(1), Unit.UD)]
    far = Store(
        1, 1, (product(11, 1, "5.00", "1", unit="ud"), product(12, 2, "5.00", "1", unit="ud"))
    )
    b = Store(
        2, 2, (product(21, 1, "5.00", "1", unit="ud"), product(22, 2, "15.00", "1", unit="ud"))
    )
    c = Store(
        3, 3, (product(31, 1, "15.00", "1", unit="ud"), product(32, 2, "5.00", "1", unit="ud"))
    )
    matrix = TravelTimes(
        (1, 2, 3),
        (
            (D(0), D(30), D(5), D(5)),
            (D(30), D(0), D(30), D(30)),
            (D(5), D(30), D(0), D(1)),
            (D(5), D(30), D(1), D(0)),
        ),
    )
    stores = []
    for lam in [D(0), D("0.5"), D(100)]:
        req = BasketRequest(tuple(lines), (far, b, c), matrix, DAY, lambda_per_minute=lam)
        stores.append(optimize(req).visiting_order)
    assert [len(s) for s in stores] == [1, 2, 1]


def test_presets_of_fr09():
    req = random_instance(random.Random(1), n_lines=3, n_stores=3)
    assert replace(req, priority_mode=PriorityMode.SAVINGS).effective_lambda == D("0.05")
    assert replace(req, priority_mode=PriorityMode.BALANCED).effective_lambda == D("0.15")
    assert replace(req, priority_mode=PriorityMode.TIME).effective_lambda == D("0.40")
    assert replace(req, lambda_per_minute=D("0.3")).effective_lambda == D("0.3")


# Missing lines, routes, edge cases ------------------------------------------


def test_missing_lines_are_reported_with_their_reason():
    lines = [
        Line("milk", 1, D(1), Unit.L),
        Line("saffron", 2, D(1), Unit.UD),
        Line("tofu", 3, D(1), Unit.UD),
    ]
    a = Store(1, 1, (product(11, 1, "0.90", "1", unit="l"),))
    b = Store(2, 2, (product(21, 3, "2.00", "1", unit="ud"),))
    res = optimize(request(lines, [a, b], {1: (1, 0), 2: (0, 9)}, max_stores=1))
    assert res.visiting_order == (1,)
    assert {(m.line_id, m.reason) for m in res.missing} == {
        ("saffron", MissingReason.NOT_AVAILABLE),
        ("tofu", MissingReason.SEPARATE_STOP),
    }
    tofu = next(m.stop for m in res.missing if m.line_id == "tofu")
    # 0->1->2->0 = 1+10+9 = 20 instead of 0->1->0 = 2.
    assert (tofu.store_id, tofu.extra_minutes, tofu.exceeds_max_stores) == (2, D(18), True)
    both = optimize(request(lines, [a, b], {1: (1, 0), 2: (0, 9)}, max_stores=2))
    assert [m.line_id for m in both.missing] == ["saffron"]


# Coverage margin and separate stops (decision 0013, point 11) ----------------

MILK_AT_A = Store(1, 1, (product(11, 1, "1.00", "1", unit="l"),))
MILK_AND_OIL = [Line("milk", 1, D(1), Unit.L), Line("oil", 2, D(1), Unit.UD)]


def oil_store(store_id, price):
    return Store(store_id, store_id, (product(10 * store_id + 2, 2, price, "1", unit="ud"),))


def detour(points, *extra_stores, **kw):
    """Milk at store 1 next to the origin; oil only at store 3 (4.00) and `extra_stores`."""
    kw.setdefault("lambda_per_minute", D("0.15"))
    stores = [MILK_AT_A, oil_store(3, "4.00"), *extra_stores]
    return optimize(request(MILK_AND_OIL, stores, points, **kw))


def test_store_nearly_on_the_way_is_added():
    # 2 extra minutes x 0.15 = 0.30 < 3.00: the full plan wins.
    res = detour({1: (1, 0), 3: (2, 0)})
    assert res.visiting_order == (1, 3)
    assert res.missing == ()
    assert (res.minutes, res.objective) == (D(4), D("5.60"))


def test_far_store_becomes_a_separate_stop():
    # 40 extra minutes x 0.15 = 6.00 > 3.00: the shorter plan wins.
    res = detour({1: (1, 0), 3: (0, 20)})
    assert res.visiting_order == (1,)
    assert (res.minutes, res.total_cost) == (D(2), D("1.00"))
    [oil] = res.missing
    assert (oil.line_id, oil.reason) == ("oil", MissingReason.SEPARATE_STOP)
    stop = oil.stop
    # 0->1->3->0 = 1+21+20 = 42 instead of 2.
    assert (stop.store_id, stop.chain_id, stop.extra_minutes) == (3, 3, D(40))
    assert stop.extra_objective == D("10.00")
    assert (stop.purchase.cost, stop.purchase.comparable_cost) == (D("4.00"), D("4.00"))
    assert stop.purchase.quantity_bought == D(1)
    assert stop.exceeds_max_stores is False


def test_separate_stop_goes_to_the_cheapest_store_to_add():
    points = {1: (1, 0), 3: (0, 20), 4: (0, -21)}
    # Store 4: 3.50 + 0.15 x 42 = 9.80 beats store 3: 4.00 + 0.15 x 40 = 10.00.
    res = detour(points, oil_store(4, "3.50"))
    assert res.visiting_order == (1,)
    assert (res.missing[0].stop.store_id, res.missing[0].stop.extra_minutes) == (4, D(42))
    # 3.70 + 6.30 = 10.00: a tie, to the lowest store id.
    tie = detour(points, oil_store(4, "3.70"))
    assert tie.missing[0].stop.store_id == 3


def test_a_tie_at_the_margin_goes_to_the_plan_covering_more_lines():
    # Margin 6.00 = 0.15 x 40 extra minutes: equal ranked value, fewer lines left out wins.
    res = detour({1: (1, 0), 3: (0, 20)}, coverage_margin=D("6.00"))
    assert res.visiting_order == (1, 3)
    assert res.missing == ()


def test_zero_margin_ranks_on_the_objective_alone():
    # Without a margin even 0.30 of detour is too much: the line is left for another day.
    res = detour({1: (1, 0), 3: (2, 0)}, coverage_margin=D(0))
    assert res.visiting_order == (1,)
    assert res.missing[0].stop.extra_minutes == D(2)
    assert res.missing[0].stop.extra_objective == D("4.30")


def test_large_margin_puts_coverage_first():
    lines = [Line("x", 1, D(1), Unit.UD), Line("y", 2, D(1), Unit.UD)]
    near = Store(1, 1, (product(11, 1, "1.00", "1", unit="ud"),))
    far = Store(
        2, 2, (product(21, 1, "9.00", "1", unit="ud"), product(22, 2, "9.00", "1", unit="ud"))
    )
    points = {1: (1, 0), 2: (50, 0)}
    kw = {"max_stores": 1, "lambda_per_minute": D(10)}
    res = optimize(request(lines, [near, far], points, coverage_margin=D(1000000), **kw))
    assert res.visiting_order == (2,)
    assert res.missing == ()
    # With the default margin the near store wins and y is a stop beyond max stores.
    default = optimize(request(lines, [near, far], points, **kw))
    assert default.visiting_order == (1,)
    [y] = default.missing
    assert (y.reason, y.stop.store_id, y.stop.exceeds_max_stores) == (
        MissingReason.SEPARATE_STOP,
        2,
        True,
    )


@pytest.mark.parametrize("seed", range(30))
def test_large_margin_leaves_out_the_fewest_lines(seed):
    rng = random.Random(seed)
    req = random_instance(
        rng,
        n_lines=6,
        n_stores=5,
        availability=0.4,
        max_stores=rng.randint(1, 3),
        coverage_margin=D(1000000),
    )
    table = bruteforce.option_table(req)
    coverable = [lid for lid, row in table.items() if row]
    fewest = min(
        sum(1 for lid in coverable if not set(table[lid]) & set(subset))
        for size in range(1, req.max_stores + 1)
        for subset in itertools.combinations([s.store_id for s in req.stores], size)
    )
    res = optimize(req)
    assert sum(m.reason is MissingReason.SEPARATE_STOP for m in res.missing) == fewest


def test_lines_nobody_sells_do_not_change_the_plan():
    saffron = Line("saffron", 9, D(1), Unit.UD)
    stores = [MILK_AT_A, oil_store(3, "4.00")]
    for points in ({1: (1, 0), 3: (2, 0)}, {1: (1, 0), 3: (0, 20)}):
        for margin in (D(0), D(3), D(1000000)):
            kw = {"lambda_per_minute": D("0.15"), "coverage_margin": margin}
            without = optimize(request(MILK_AND_OIL, stores, points, **kw)).to_dict()
            with_it = optimize(request([*MILK_AND_OIL, saffron], stores, points, **kw)).to_dict()
            extra = with_it["missing"].pop()
            assert extra == {"line_id": "saffron", "reason": "not_available", "stop": None}
            assert with_it == without


def test_line_only_in_an_unreachable_store():
    lines = [Line("a", 1, D(1), Unit.UD), Line("b", 2, D(1), Unit.UD)]
    s1 = Store(1, 1, (product(11, 1, "1.00", "1", unit="ud"),))
    s2 = Store(2, 2, (product(22, 2, "1.00", "1", unit="ud"),))
    matrix = TravelTimes(
        (1, 2),
        (
            (D(0), D(1), None),
            (D(1), D(0), None),
            (None, None, D(0)),
        ),
    )
    res = optimize(BasketRequest(tuple(lines), (s1, s2), matrix, DAY))
    assert res.visiting_order == (1,)
    assert [(m.line_id, m.reason, m.stop) for m in res.missing] == [
        ("b", MissingReason.UNREACHABLE, None)
    ]


def test_negative_margin_is_rejected():
    with pytest.raises(ValueError, match="coverage_margin"):
        request([], [], {}, coverage_margin=D("-1"))


def test_nothing_available():
    res = optimize(request([Line("x", 1, D(1), Unit.UD)], [], {}))
    assert res.stores == ()
    assert res.total_cost == D("0.00")
    assert [m.reason for m in res.missing] == [MissingReason.NOT_AVAILABLE]


def test_route_returns_to_origin_by_default_and_order_is_the_fastest():
    lines = [Line("a", 1, D(1), Unit.UD), Line("b", 2, D(1), Unit.UD)]
    s1 = Store(1, 1, (product(11, 1, "1.00", "1", unit="ud"),))
    s2 = Store(2, 2, (product(22, 2, "1.00", "1", unit="ud"),))
    matrix = TravelTimes(
        (1, 2),
        (
            (D(0), D(10), D(2)),
            (D(3), D(0), D(4)),
            (D(9), D(4), D(0)),
        ),
    )
    req = BasketRequest(tuple(lines), (s1, s2), matrix, DAY, lambda_per_minute=D(0))
    res = optimize(req)
    # 0->1->2->0 = 10+4+9 = 23 ; 0->2->1->0 = 2+4+3 = 9.
    assert res.visiting_order == (2, 1)
    assert res.minutes == D(9)
    one_way = optimize(replace(req, return_to_origin=False))
    # 0->1->2 = 14 ; 0->2->1 = 6.
    assert one_way.visiting_order == (2, 1)
    assert one_way.minutes == D(6)
    assert [s.position for s in res.stores] == [1, 2]


def test_unreachable_store_is_skipped():
    lines = [Line("a", 1, D(1), Unit.UD)]
    s1 = Store(1, 1, (product(11, 1, "1.00", "1", unit="ud"),))
    s2 = Store(2, 2, (product(21, 1, "5.00", "1", unit="ud"),))
    matrix = TravelTimes(
        (1, 2),
        (
            (D(0), None, D(5)),
            (None, D(0), D(1)),
            (D(5), D(1), D(0)),
        ),
    )
    res = optimize(BasketRequest(tuple(lines), (s1, s2), matrix, DAY))
    assert res.visiting_order == (2,)


def test_store_missing_from_the_matrix_is_an_error():
    s1 = Store(1, 1, ())
    with pytest.raises(ValueError, match="without travel times"):
        optimize(BasketRequest((), (s1,), TravelTimes((), ((D(0),),)), DAY))


def test_invalid_requests():
    with pytest.raises(ValueError, match="max_stores"):
        request([], [], {}, max_stores=4)
    with pytest.raises(ValueError, match="duplicate line"):
        request([Line("a", 1, D(1)), Line("a", 2, D(1))], [], {})
    with pytest.raises(ValueError, match="positive"):
        Line("a", 1, D(0))


# Performance (NFR-01: the optimizer alone takes under 1 s) -------------------


def test_thirty_lines_ten_stores_under_one_second():
    rng = random.Random(2026)
    req = random_instance(
        rng, n_lines=30, n_stores=10, max_products=5, promo_rate=0.5, availability=0.9, max_stores=3
    )
    optimize(req)  # warm-up (imports, caches of the interpreter)
    times = []
    for _ in range(3):
        start = time.perf_counter()
        result = optimize(req)
        times.append(time.perf_counter() - start)
    print(
        f"\n30 lines x 10 stores x up to 5 products: best {min(times):.3f} s, "
        f"worst {max(times):.3f} s, {len(result.stores)} stores"
    )
    assert max(times) < 1.0


def test_dense_catalog_under_one_second():
    """Harder than a real list: 8 formats per line and store, a promotion on every product,
    2 kg requested in packs from 100 g (up to 30 packs per product)."""
    from smart_basket.optimizer import BaseUnit, Product, PromotionKind
    from tests.optimizer.helpers import _random_promo

    rng = random.Random(7)
    lines = tuple(Line(f"L{i}", i, D(2), Unit.KG) for i in range(30))
    stores, pid = [], 0
    for s in range(10):
        products, promos = [], []
        for i in range(30):
            for size in ["0.1", "0.125", "0.2", "0.25", "0.4", "0.5", "1", "2"]:
                pid += 1
                price = D(rng.randint(50, 600)) / 100
                products.append(Product(pid, i, price, D(size), BaseUnit.KG))
                promos.append(_random_promo(rng, pid, pid, rng.choice(list(PromotionKind)), price))
        stores.append(Store(s + 1, 1 + s % 3, tuple(products), tuple(promos)))
    points = {s + 1: (rng.randint(-10, 10), rng.randint(-10, 10)) for s in range(10)}
    req = BasketRequest(
        lines,
        tuple(stores),
        grid_matrix((0, 0), points),
        DAY,
        loyalty_chain_ids=frozenset({1}),
        coupon_codes=frozenset({"CUPON"}),
    )
    start = time.perf_counter()
    optimize(req)
    elapsed = time.perf_counter() - start
    print(f"\ndense catalog, 30 lines x 10 stores x 8 formats: {elapsed:.3f} s")
    assert elapsed < 1.0
