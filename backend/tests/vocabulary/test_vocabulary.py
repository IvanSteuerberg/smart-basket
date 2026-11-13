"""The preprocessor lexicon built from the real packaged seed (decision 0014)."""

import importlib.util
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from smart_basket.preprocessor import InMemoryLexicon, Preprocessor
from smart_basket.seed import DEFAULT_DATA_DIR
from smart_basket.seed.loader import load_seed
from smart_basket.vocabulary import build_lexicon, export_lexicon

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

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


def test_one_generic_term_per_category_with_forms(session, lexicon):
    expected = session.execute(
        text("select count(*) from category where cardinality(forms) > 0")
    ).scalar_one()
    terms = lexicon.generic_terms()
    assert len(terms) == expected
    assert len({term.key for term in terms}) == len(terms)
    assert all(term.forms for term in terms)
    assert all(term.canonical_id is None for term in terms)

    by_key = {term.key: term for term in terms}
    pan = by_key["pan_molde"]
    assert pan.name == "Pan de molde"
    assert "pan de molde" in pan.forms
    assert pan.base_unit == "kg"
    assert pan.default_quantity == Decimal("0.45")
    assert pan.category == "panaderia"
    assert pan.vague is False

    leche = by_key["leche"]
    assert leche.base_unit == "l"
    assert leche.default_quantity == Decimal("1")
    assert leche.category == "lacteos_huevos"
    assert "leche semidesnatada" in leche.forms

    fruta = by_key["fruta"]
    assert fruta.vague is True
    assert fruta.category == "fruta_verdura"


def test_brands_and_variants_come_from_their_sources(session, lexicon):
    expected_brands = session.execute(text("select count(*) from brand")).scalar_one()
    variants = json.loads((DEFAULT_DATA_DIR / "variants_es.json").read_text(encoding="utf-8"))
    assert len(lexicon.brands()) == expected_brands
    assert len(lexicon.variants()) == len(variants["variants"])
    assert {v.key for v in lexicon.variants()} == {v["key"] for v in variants["variants"]}


def test_seed_brand_aliases_and_implies_reach_the_lexicon(session, lexicon):
    brands = {brand.name: brand for brand in lexicon.brands()}
    cocacola = brands["Coca-Cola"]
    assert cocacola.aliases == ("coca cola", "cocacola", "coca-cola", "coke")
    assert cocacola.implies == "refresco_cola"
    assert cocacola.is_private_label is False

    hacendado = brands["Hacendado"]
    assert hacendado.is_private_label is True
    assert hacendado.implies is None


def test_a_category_removed_from_the_file_leaves_the_lexicon(session, tmp_path):
    data_dir = tmp_path / "seed"
    shutil.copytree(DEFAULT_DATA_DIR, data_dir)

    def without_platano(nodes: list[dict]) -> list[dict]:
        kept = []
        for node in nodes:
            if node["key"] == "platano":
                continue
            node["children"] = without_platano(node.get("children", []))
            kept.append(node)
        return kept

    path = data_dir / "taxonomy_es.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["categories"] = without_platano(data["categories"])
    path.write_text(json.dumps(data), encoding="utf-8")
    report = load_seed(session, data_dir)
    session.commit()

    assert "platano" in report.stale_categories
    forms = session.execute(text("select forms from category where key = 'platano'")).scalar_one()
    assert forms == []
    assert "platano" not in {term.key for term in build_lexicon(session).generic_terms()}


def test_export_round_trips(lexicon, tmp_path):
    path = tmp_path / "lexicon.json"
    export_lexicon(lexicon, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"generic", "brands", "variants"}

    loaded = InMemoryLexicon.from_json(path)
    assert loaded.generic_terms() == lexicon.generic_terms()
    assert loaded.brands() == lexicon.brands()
    assert loaded.variants() == lexicon.variants()
    assert loaded.units() == lexicon.units()


def test_preprocessor_resolves_seed_brands(pp: Preprocessor):
    for phrase in ("Cocacola", "coca cola zero"):
        item = pp.preprocess(phrase).items[0]
        assert item.brand == "Coca-Cola", phrase
        assert item.generic_key == "refresco_cola", phrase
        assert item.resolved is True, phrase

    colacao = pp.preprocess("colacao").items[0]
    assert colacao.brand == "Cola Cao"
    assert colacao.generic_key == "cacao_soluble"
    assert colacao.resolved is True


def test_preprocessor_resolves_seed_terms(pp: Preprocessor):
    pan = pp.preprocess("pan de molde").items[0]
    assert pan.generic_key == "pan_molde"
    assert pan.resolved is True

    leche = pp.preprocess("2 l de leche semidesnatada").items[0]
    assert leche.generic_key == "leche"
    assert leche.quantity == Decimal(2)
    assert leche.unit == "l"
    assert leche.resolved is True

    fruta = pp.preprocess("fruta").items[0]
    assert fruta.generic_key == "fruta"
    assert fruta.resolved is False
    assert fruta.ambiguous is True
    assert "vague_item" in fruta.reasons


def test_rules_only_on_the_benchmark_lists(pp, bench, lists):
    assert len(lists) == 8
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
