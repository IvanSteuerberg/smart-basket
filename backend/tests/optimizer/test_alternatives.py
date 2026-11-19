"""Top-k alternative plans (ADR 0022): defaults, validation, near ties, JSON and oracle."""

import json
import random
from decimal import Decimal as D
from fractions import Fraction

import pytest

from smart_basket.optimizer import BasketRequest, Line, MissingReason, Store, Unit, optimize
from tests.optimizer import bruteforce
from tests.optimizer.helpers import DAY, grid_matrix, product, random_instance

MILK = [Line("milk", 1, D(1), Unit.L)]


def request(lines, stores, points, **kw):
    return BasketRequest(
        tuple(lines), tuple(stores), grid_matrix((0, 0), points), shopping_date=DAY, **kw
    )


def milk_store(store_id, price, x):
    return Store(store_id, store_id, (product(10 * store_id + 1, 1, price, "1", unit="l"),))


def two_store_case():
    """Milk at 1.00 two minutes away and at 1.10 four minutes away: a clear near tie."""
    stores = [milk_store(1, "1.00", 1), milk_store(2, "1.10", 2)]
    return request(MILK, stores, {1: (1, 0), 2: (2, 0)})


def test_default_and_zero_return_no_alternatives():
    req = two_store_case()
    assert optimize(req).alternatives == ()
    assert optimize(req, max_alternatives=0) == optimize(req)


def test_negative_max_alternatives_is_rejected():
    with pytest.raises(ValueError, match="max_alternatives"):
        optimize(two_store_case(), max_alternatives=-1)


def test_alternative_is_the_other_store_with_its_exact_delta():
    req = two_store_case()
    base = optimize(req)
    res = optimize(req, max_alternatives=1)
    # The winning plan is untouched: only the alternatives list is filled.
    assert res.to_dict() | {"alternatives": []} == base.to_dict()
    assert res.visiting_order == (1,)
    [alt] = res.alternatives
    assert alt.plan.visiting_order == (2,)
    assert alt.plan.alternatives == ()
    assert alt.plan.objective == D("1.70")
    assert alt.objective_delta == D("0.40")
    assert alt.objective_delta >= 0


def test_alternatives_are_ranked_and_capped_at_k():
    stores = [milk_store(sid, "1.00", sid) for sid in (1, 2, 3, 4)]
    req = request(MILK, stores, {sid: (sid, 0) for sid in (1, 2, 3, 4)})
    res = optimize(req, max_alternatives=2)
    assert res.visiting_order == (1,)
    assert [a.plan.visiting_order for a in res.alternatives] == [(2,), (3,)]
    deltas = [a.objective_delta for a in res.alternatives]
    assert deltas == [D("0.30"), D("0.60")]
    assert deltas == sorted(deltas)
    # k larger than the number of other valid subsets returns all of them.
    everything = optimize(req, max_alternatives=10)
    assert [a.plan.visiting_order for a in everything.alternatives] == [(2,), (3,), (4,)]


def test_a_single_store_has_no_alternative():
    req = request(MILK, [milk_store(1, "1.00", 1)], {1: (1, 0)})
    assert optimize(req, max_alternatives=3).alternatives == ()


def test_no_valid_subset_has_no_alternative():
    res = optimize(request([Line("x", 1, D(1), Unit.UD)], [], {}), max_alternatives=2)
    assert res.stores == ()
    assert res.alternatives == ()


def test_json_serializes_alternatives_with_decimal_strings():
    req = two_store_case()
    res = optimize(req, max_alternatives=1)
    data = json.loads(res.to_json())
    [alt] = data["alternatives"]
    assert alt["objective_delta"] == "0.4000"
    assert alt["plan"]["alternatives"] == []
    assert alt["plan"]["stores"][0]["store_id"] == 2
    # Round trip: the winner serializes exactly as before, only the alternatives list changes.
    assert data | {"alternatives": []} == json.loads(optimize(req).to_json())


@pytest.mark.parametrize("seed", range(300))
def test_matches_independent_brute_force_top_k(seed):
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
    base = optimize(req)
    res = optimize(req, max_alternatives=3)
    # The winning plan is the one selected without alternatives.
    assert base.alternatives == ()
    assert res.to_dict() | {"alternatives": []} == base.to_dict()

    oracle = bruteforce.solve_top_k_subsets(req, 3)
    assert len(res.alternatives) == max(0, len(oracle) - 1)
    uncovered = MissingReason.NOT_AVAILABLE
    if oracle:
        assert tuple(sorted(res.visiting_order)) == oracle[0][0]
        assert len(res.stores) == oracle[0][3]
        assert Fraction(res.minutes) == oracle[0][4]
        assert sum(m.reason is not uncovered for m in res.missing) == oracle[0][2]
    else:
        assert res.stores == ()
    for rank, alt in enumerate(res.alternatives, start=1):
        entry = oracle[rank]
        # Same subset, same route length, same lines left out, same rank in the same order.
        assert tuple(sorted(alt.plan.visiting_order)) == entry[0]
        assert alt.plan.alternatives == ()
        assert len(alt.plan.stores) == entry[3]
        assert Fraction(alt.plan.minutes) == entry[4]
        assert sum(m.reason is not uncovered for m in alt.plan.missing) == entry[2]
        assert Fraction(alt.objective_delta) == entry[1] - oracle[0][1]
        assert alt.objective_delta >= 0
    deltas = [Fraction(a.objective_delta) for a in res.alternatives]
    assert deltas == sorted(deltas)
