"""Evaluation over the 8 example lists of the LLM benchmark, with bench.py's own scoring.

`experiments/` is read, never modified: bench.py is loaded as a module to reuse `score` and
`valid_items` exactly. Rules only (no LLM), i.e. the degraded mode of FR-41. The fixture
lexicon was written knowing these lists, so the figures are optimistic for the rules; real
lists are needed for a fair measure (see decision 0014).
"""

import importlib.util
import json
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).parents[3] / "experiments" / "llm-benchmark"


@pytest.fixture(scope="module")
def bench():
    if not (BENCH_DIR / "bench.py").exists():
        pytest.skip("experiments/llm-benchmark not available")
    spec = importlib.util.spec_from_file_location("bench", BENCH_DIR / "bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lists():
    return json.loads((BENCH_DIR / "lists.json").read_text(encoding="utf-8"))


def test_rules_only_on_the_benchmark_lists(pp, bench, lists):
    rows, tp, pred, gold, qty_ok, resolved, lines = [], 0, 0, 0, 0, 0, 0
    for lst in lists:
        result = pp.preprocess(lst["text"])
        schema = result.to_schema()
        assert bench.valid_items(schema), lst["id"]
        s = bench.score(schema["items"], lst["gold"])
        rows.append(
            (
                lst["id"],
                s["f1"],
                s["qty_unit_ok"],
                s["gold"],
                sum(i.resolved for i in result.items),
                len(result.items),
            )
        )
        tp, pred, gold, qty_ok = (
            tp + s["tp"],
            pred + s["pred"],
            gold + s["gold"],
            qty_ok + s["qty_unit_ok"],
        )
        resolved += sum(i.resolved for i in result.items)
        lines += len(result.items)
    mean_f1 = sum(r[1] for r in rows) / len(rows)
    precision, recall = tp / pred, tp / gold
    micro_f1 = 2 * precision * recall / (precision + recall)
    print("\nlist  F1     qty+unit ok  resolved by rules")
    for list_id, f1, ok, n_gold, n_res, n_lines in rows:
        print(f"{list_id:4}  {f1:.3f}  {ok:2}/{n_gold:<2}        {n_res:2}/{n_lines}")
    print(
        f"mean F1 {mean_f1:.3f}, micro F1 {micro_f1:.3f}, quantity and unit right "
        f"{qty_ok}/{gold}, resolved without LLM {resolved}/{lines} ({resolved / lines:.0%})"
    )
    assert mean_f1 >= 0.90  # the F1 target of NFR-14, here for rules only
    assert resolved / lines >= 0.80


#: A synthetic list in the style of the real household list of the benchmark notes (not the
#: author's): abbreviations, joined words, typos, no quantities. Expected canonical keys.
MESSY = (
    "lech semi\npandemolde integ\n2 paqs d galletas\ncafe molio\n1/2 kg tomates\n"
    "yogures s/lactosa x4\npapel wc\naove 1l\nmacarones\nmantequila\ncolacao\ndetergente lavadora"
)
MESSY_KEYS = [
    "leche",
    "pan_molde",
    "galleta",
    "cafe_molido",
    "tomate",
    "yogur",
    "papel_higienico",
    "aceite_oliva_ve",
    "macarrones",
    "mantequilla",
    "cacao_soluble",
    "detergente_lavadora",
]


def test_messy_household_style_list(pp):
    result = pp.preprocess(MESSY)
    keys = [i.generic_key for i in result.items]
    hits = sum(k == e for k, e in zip(keys, MESSY_KEYS, strict=True))
    print(
        f"\nmessy list: {hits}/{len(MESSY_KEYS)} canonical keys right, "
        f"{result.resolved_share:.0%} resolved without LLM"
    )
    assert keys == MESSY_KEYS
    assert result.resolved_share == 1.0
