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

    # Alternatives are the best subset of each *other* chain set, so the oracle is the full
    # ranking and every alternative must be one of its entries with the same figures.
    oracle = bruteforce.solve_top_k_subsets(req, 10**6)
    chain_of = {s.store_id: s.chain_id for s in req.stores}

    def chain_set(ids):
        return frozenset(chain_of[sid] for sid in ids)

    uncovered = MissingReason.NOT_AVAILABLE
    if oracle:
        assert tuple(sorted(res.visiting_order)) == oracle[0][0]
        assert len(res.stores) == oracle[0][3]
        assert Fraction(res.minutes) == oracle[0][4]
        assert sum(m.reason is not uncovered for m in res.missing) == oracle[0][2]
    else:
        assert res.stores == ()
    winner_chains = chain_set(res.visiting_order)
    by_subset = {entry[0]: entry for entry in oracle}
    seen = {winner_chains}
    for alt in res.alternatives:
        entry = by_subset[tuple(sorted(alt.plan.visiting_order))]
        assert alt.plan.alternatives == ()
        assert len(alt.plan.stores) == entry[3]
        assert Fraction(alt.plan.minutes) == entry[4]
        assert sum(m.reason is not uncovered for m in alt.plan.missing) == entry[2]
        assert Fraction(alt.objective_delta) == entry[1] - oracle[0][1]
        assert alt.objective_delta >= 0
        # Never the winner's chains, never twice the same chains.
        chains = chain_set(alt.plan.visiting_order)
        assert chains not in seen
        seen.add(chains)
    others = {chain_set(entry[0]) for entry in oracle[1:]} - {winner_chains}
    assert len(res.alternatives) == min(3, len(others))
    deltas = [Fraction(a.objective_delta) for a in res.alternatives]
    assert deltas == sorted(deltas)


def chain_store(store_id, chain_id, price, minutes_x):
    return Store(store_id, chain_id, (product(10 * store_id + 1, 1, price, "1", unit="l"),))


def test_branches_of_the_same_chain_are_never_alternatives():
    # Stores 1 and 2 belong to chain 7, store 3 to chain 8: only chain 8 is a real alternative.
    stores = [
        chain_store(1, 7, "1.00", 1),
        chain_store(2, 7, "1.01", 2),
        chain_store(3, 8, "1.05", 3),
    ]
    req = request(MILK, stores, {1: (1, 0), 2: (2, 0), 3: (3, 0)})
    res = optimize(req, max_alternatives=3)
    assert res.visiting_order == (1,)
    assert [a.plan.visiting_order for a in res.alternatives] == [(3,)]


def test_pareto_single_store_and_cheaper_plan_are_kept_within_the_quota():
    lines = [Line("milk", 1, D(1), Unit.L), Line("oil", 2, D(1), Unit.L)]

    # Chains 1+2 win: milk is cheap in 1, oil in 2, each one minute away. Chain 3 sells both
    # at a higher price (a single-store plan); chains 4 and 5 are near copies that would fill
    # the quota if the Pareto plans were not reserved a slot.
    def shop(sid, chain, milk, oil):
        items = tuple(
            product(100 * sid + i, i, price, "1", unit="l")
            for i, price in ((1, milk), (2, oil))
            if price is not None
        )
        return Store(sid, chain, items)

    stores = [
        shop(1, 1, "1.00", None),
        shop(2, 2, None, "1.00"),
        shop(3, 3, "1.40", "1.40"),
        shop(4, 4, "1.00", "1.05"),
        shop(5, 5, "1.00", "1.06"),
    ]
    points = {1: (1, 0), 2: (0, 1), 3: (1, 1), 4: (6, 0), 5: (7, 0)}
    req = BasketRequest(tuple(lines), tuple(stores), grid_matrix((0, 0), points), shopping_date=DAY)
    res = optimize(req, max_alternatives=2)
    chosen = {frozenset(s.store_id for s in a.plan.stores) for a in res.alternatives}
    assert len(res.alternatives) <= 2
    assert all(len(a.plan.stores) >= 1 for a in res.alternatives)
    assert optimize(req).visiting_order == res.visiting_order
    if len(res.stores) >= 2:
        assert any(len(ids) == 1 for ids in chosen)
