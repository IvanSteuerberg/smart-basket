"""What a product name says: its taxonomy terms and its equivalence variants."""

import json

import pytest

from smart_basket.matching import Hit, canonical_name, name_match, variant_key
from smart_basket.preprocessor import (
    BrandTerm,
    GenericTerm,
    InMemoryLexicon,
    Preprocessor,
    VariantTerm,
)
from smart_basket.seed import DEFAULT_DATA_DIR


@pytest.fixture(scope="module")
def pp() -> Preprocessor:
    """A lexicon with the packaged variants and a handful of synthetic terms."""
    data = json.loads((DEFAULT_DATA_DIR / "variants_es.json").read_text(encoding="utf-8"))
    variants = [
        VariantTerm(
            key=variant["key"],
            name=variant.get("name", variant["key"]),
            forms=tuple(variant.get("forms", [variant.get("name", variant["key"])])),
            canonical=variant.get("canonical", False),
        )
        for variant in data["variants"]
    ]
    lexicon = InMemoryLexicon(
        [
            GenericTerm("leche", "Leche", ("leche", "leche sin lactosa")),
            GenericTerm("leche_condensada", "Leche condensada", ("leche condensada",)),
            GenericTerm("platano", "Plátano", ("plátano", "banana")),
            GenericTerm("fresa", "Fresa", ("fresa",)),
            GenericTerm("petit_suisse", "Petit suisse", ("petit suisse", "petit")),
            GenericTerm("yogur", "Yogur", ("yogur",)),
            GenericTerm("fruta", "Fruta", ("fruta",), vague=True),
        ],
        brands=[BrandTerm("Hacendado", ("hacendado",), is_private_label=True)],
        variants=variants,
    )
    return Preprocessor(lexicon)


def test_a_name_names_its_leaf(pp: Preprocessor):
    match = name_match(pp, "Plátano de Canarias IGP")
    assert match.hits == (Hit("platano", 1),)
    assert match.variant_keys == ()


def test_brand_words_are_removed_before_the_match(pp: Preprocessor):
    assert name_match(pp, "Hacendado").hits == ()


def test_a_name_can_name_several_leaves(pp: Preprocessor):
    match = name_match(pp, "Leche condensada Hacendado")
    assert {(hit.key, hit.length) for hit in match.hits} == {
        ("leche", 1),
        ("leche_condensada", 2),
    }


def test_sin_lactosa_changes_the_equivalence(pp: Preprocessor):
    assert name_match(pp, "Leche sin lactosa Hacendado").variant_keys == ("sin_lactosa",)


def test_marketing_variants_do_not_change_the_equivalence(pp: Preprocessor):
    assert name_match(pp, "Yogur natural").variant_keys == ()


def test_a_flavour_creates_a_variant(pp: Preprocessor):
    assert name_match(pp, "Petit sabor fresa").variant_keys == ("sabor:fresa",)


def test_an_introductory_a_or_de_is_skipped(pp: Preprocessor):
    assert name_match(pp, "Yogur sabor a fresa").variant_keys == ("sabor:fresa",)
    assert name_match(pp, "Yogur sabor de fresa").variant_keys == ("sabor:fresa",)


def test_and_and_con_join_a_two_word_flavour(pp: Preprocessor):
    assert name_match(pp, "Petit sabor fresa y plátano").variant_keys == ("sabor:fresa y platano",)
    assert name_match(pp, "Petit sabor fresa con plátano").variant_keys == (
        "sabor:fresa con platano",
    )


def test_a_flavour_word_does_not_name_its_leaf(pp: Preprocessor):
    assert name_match(pp, "Yogur sabor fresa").hits == (Hit("yogur", 1),)


def test_a_two_word_flavour_names_neither_leaf(pp: Preprocessor):
    match = name_match(pp, "Petit sabor fresa y plátano")
    assert match.hits == (Hit("petit_suisse", 1),)
    assert match.variant_keys == ("sabor:fresa y platano",)


def test_the_flavour_stops_where_an_equivalence_variant_starts(pp: Preprocessor):
    match = name_match(pp, "Yogur sabor fresa sin lactosa")
    assert match.variant_keys == ("sabor:fresa", "sin_lactosa")


def test_canonical_names_hold_the_leaf_and_the_variants():
    names = {"sin_lactosa": "sin lactosa"}
    assert canonical_name("Leche", ("sin_lactosa",), names) == "Leche — sin lactosa"
    assert canonical_name("Petit suisse", ("sabor:fresa",), names) == "Petit suisse — sabor fresa"
    assert canonical_name("Leche", (), names) == "Leche"


def test_the_variant_key_is_sorted_and_joined():
    assert variant_key(("sin_lactosa", "sabor:fresa")) == "sabor:fresa|sin_lactosa"
    assert variant_key(()) == ""
