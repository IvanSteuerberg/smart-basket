"""The decision rules: the section and the name choose a leaf or the review queue."""

from smart_basket.matching import Hit, NameMatch, Section, decide

LEAF_KEYS = frozenset(
    {
        "platano",
        "manzana",
        "uva",
        "leche",
        "leche_condensada",
        "carne",
        "pollo",
        "pavo",
        "yogur",
        "fresa",
    }
)

#: A chain section that maps to the group "fruta", and one that maps to the leaf "platano".
FRUTA = Section("fruta", False, frozenset({"frescos"}), frozenset({"platano", "manzana", "uva"}))
PLATANO = Section(
    "platano", True, frozenset({"fruta", "frescos"}), frozenset({"platano", "manzana", "uva"})
)
#: Sections that only allow their own leaf, even when the name names a nearby one.
YOGUR_SECTION = Section("yogur", True, frozenset({"lacteos", "frescos"}), frozenset({"yogur"}))
POLLO_SECTION = Section("pollo", True, frozenset({"carnes", "frescos"}), frozenset({"pollo"}))


def test_a_leaf_named_inside_the_section_is_assigned():
    decision = decide(NameMatch((Hit("platano", 1),), ()), FRUTA, LEAF_KEYS)
    assert not decision.in_review
    assert decision.category_key == "platano"
    assert decision.confidence == 0.9


def test_the_longest_form_wins():
    match = NameMatch((Hit("leche", 1), Hit("leche_condensada", 2)), ())
    lacteos = Section(
        "lacteos", False, frozenset({"frescos"}), frozenset({"leche", "leche_condensada"})
    )
    assert decide(match, lacteos, LEAF_KEYS).category_key == "leche_condensada"


def test_two_equally_specific_leaves_go_to_review():
    decision = decide(NameMatch((Hit("platano", 1), Hit("manzana", 1)), ()), FRUTA, LEAF_KEYS)
    assert decision.in_review
    assert {candidate.category_key for candidate in decision.candidates} == {"platano", "manzana"}


def test_a_leaf_outside_the_section_goes_to_review():
    decision = decide(NameMatch((Hit("leche", 1),), ()), FRUTA, LEAF_KEYS)
    assert decision.in_review
    assert decision.candidates[0].category_key == "leche"


def test_a_leaf_inside_the_section_wins_over_an_outside_one():
    match = NameMatch((Hit("yogur", 1), Hit("fresa", 1)), ("sabor:fresa",))
    decision = decide(match, YOGUR_SECTION, LEAF_KEYS)
    assert not decision.in_review
    assert decision.category_key == "yogur"
    assert decision.confidence == 0.9


def test_an_outside_leaf_does_not_tie_with_an_inside_one():
    match = NameMatch((Hit("pollo", 1), Hit("pavo", 1)), ())
    assert decide(match, POLLO_SECTION, LEAF_KEYS).category_key == "pollo"


def test_a_leaf_outside_the_section_without_an_inside_one_still_goes_to_review():
    decision = decide(NameMatch((Hit("pavo", 1),), ()), POLLO_SECTION, LEAF_KEYS)
    assert decision.in_review
    assert decision.candidates[0].category_key == "pavo"


def test_a_section_leaf_fills_a_name_without_a_leaf():
    decision = decide(NameMatch((), ()), PLATANO, LEAF_KEYS)
    assert not decision.in_review
    assert decision.category_key == "platano"
    assert decision.confidence == 0.8


def test_a_group_that_contains_the_section_leaf_is_no_conflict():
    decision = decide(NameMatch((Hit("fruta", 1),), ()), PLATANO, LEAF_KEYS)
    assert decision.category_key == "platano"


def test_a_group_outside_the_section_leaf_goes_to_review():
    decision = decide(NameMatch((Hit("carne", 1),), ()), PLATANO, LEAF_KEYS)
    assert decision.in_review
    assert decision.candidates[0].category_key == "carne"


def test_a_group_section_without_a_named_leaf_lists_its_leaves():
    decision = decide(NameMatch((), ()), FRUTA, LEAF_KEYS)
    assert decision.in_review
    assert {candidate.category_key for candidate in decision.candidates} == {
        "platano",
        "manzana",
        "uva",
    }


def test_a_product_without_a_section_goes_to_review():
    nowhere = Section(None, False, frozenset(), frozenset())
    decision = decide(NameMatch((Hit("platano", 1),), ()), nowhere, LEAF_KEYS)
    assert decision.in_review
    assert decision.candidates[0].category_key == "platano"
