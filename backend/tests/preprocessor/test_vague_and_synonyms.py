"""Vague "leche" and "detergente", and the chicken fillet synonyms, on the packaged taxonomy.

The lexicon is built from `taxonomy_es.json` and `variants_es.json` as the vocabulary builder
does, without a database.
"""

import json

import pytest

from smart_basket.preprocessor import GenericTerm, InMemoryLexicon, Preprocessor
from smart_basket.seed import DEFAULT_DATA_DIR
from smart_basket.seed.models import TaxonomyFile
from smart_basket.vocabulary.build import _load_variants


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyFile:
    raw = json.loads((DEFAULT_DATA_DIR / "taxonomy_es.json").read_text(encoding="utf-8"))
    return TaxonomyFile.model_validate(raw)


@pytest.fixture(scope="module")
def seed_pp(taxonomy) -> Preprocessor:
    generic = [
        GenericTerm(
            key=row.key,
            name=row.name,
            forms=tuple(row.forms),
            base_unit=row.base_unit,
            default_quantity=row.default_quantity,
            vague=row.is_vague,
        )
        for row in taxonomy.rows()
        if row.forms
    ]
    return Preprocessor(InMemoryLexicon(generic, (), _load_variants()))


def _one(pp: Preprocessor, text: str):
    items = pp.preprocess(text).items
    assert len(items) == 1
    return items[0]


@pytest.mark.parametrize(
    ("text", "key"),
    [("leche", "leche_sin_especificar"), ("detergente", "detergente_sin_especificar")],
)
def test_a_bare_term_is_vague(seed_pp, text, key):
    item = _one(seed_pp, text)

    assert item.generic_key == key
    assert not item.resolved
    assert "vague_item" in item.reasons


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("leche entera", "leche"),
        ("leche semidesnatada", "leche"),
        ("leche desnatada", "leche"),
        ("detergente lavadora", "detergente_liquido"),
        ("detergente líquido", "detergente_liquido"),
        ("detergente en cápsulas", "capsulas_detergente_ropa"),
    ],
)
def test_a_specific_term_resolves_without_asking(seed_pp, text, key):
    item = _one(seed_pp, text)

    assert item.generic_key == key
    assert "vague_item" not in item.reasons


@pytest.mark.parametrize(
    "text",
    [
        "filete de pollo",
        "filetes de pollo",
        "filetes de pechuga de pollo",
        "filete de pechuga de pollo",
        "pechuga de pollo",
    ],
)
def test_chicken_fillets_are_chicken_breast(seed_pp, text):
    assert _one(seed_pp, text).generic_key == "pollo_pechuga"


@pytest.mark.parametrize("key", ["leche_sin_especificar", "detergente_sin_especificar"])
def test_the_vague_terms_offer_real_leaf_options(taxonomy, key):
    rows = {row.key: row for row in taxonomy.rows()}

    assert len(rows[key].options) >= 3
    assert all(rows[option].forms and not rows[option].is_vague for option in rows[key].options)
