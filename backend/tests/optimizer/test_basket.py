"""Basket optimizer: brute force, determinism, lambda sweep, missing lines, routes, timing."""

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
    )
    result = optimize(req)
    uncovered, objective = bruteforce.solve(req)
    assert sum(m.reason is MissingReason.STORE_LIMIT for m in result.missing) == uncovered
    assert Fraction(result.objective) == objective
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
        ("tofu", MissingReason.STORE_LIMIT),
    }
    both = optimize(request(lines, [a, b], {1: (1, 0), 2: (0, 9)}, max_stores=2))
    assert [m.line_id for m in both.missing] == ["saffron"]


def test_coverage_comes_before_cost_and_time():
    lines = [Line("x", 1, D(1), Unit.UD), Line("y", 2, D(1), Unit.UD)]
    near = Store(1, 1, (product(11, 1, "1.00", "1", unit="ud"),))
    far = Store(
        2, 2, (product(21, 1, "9.00", "1", unit="ud"), product(22, 2, "9.00", "1", unit="ud"))
    )
    res = optimize(
        request(lines, [near, far], {1: (1, 0), 2: (50, 0)}, max_stores=1, lambda_per_minute=D(10))
    )
    assert res.visiting_order == (2,)
    assert res.missing == ()


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
