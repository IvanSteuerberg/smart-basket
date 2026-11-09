"""One group of tests per normalization rule of the preprocessor (decision 0014)."""

from decimal import Decimal as D

import pytest

from smart_basket.preprocessor import GenericTerm, InMemoryLexicon, Preprocessor
from smart_basket.preprocessor.text import fold, same_word, tokenize

# Text basics ------------------------------------------------------------------


def test_fold_lowercases_and_strips_accents():
    assert fold("Plátanos") == "platanos"
    assert fold("PIÑA") == "pina"
    assert fold("Champú") == "champu"


def test_tokens_split_numbers_from_units():
    assert [t.key for t in tokenize("1kg 6x1,5l x8 coca-cola")] == [
        "1",
        "kg",
        "6",
        "x",
        "1,5",
        "l",
        "x",
        "8",
        "coca-cola",
    ]


def test_plural_insensitive_words():
    assert same_word("tomate", "tomates")
    assert same_word("limones", "limon")
    assert not same_word("pan", "pana")


# Case and accents ---------------------------------------------------------------


def test_case_and_missing_accents(one):
    item = one("PLATANOS")
    assert item.resolved
    assert item.item == "plátanos"  # accents restored from the lexicon
    assert one("Cafe Molido").item == "café molido"


# Abbreviations ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("leche semi", "leche semidesnatada"),
        ("leche desn", "leche desnatada"),
        ("pan d molde", "pan de molde"),
        ("yogures s/lactosa", "yogures sin lactosa"),
        ("aove", "aceite de oliva virgen extra"),
        ("pan de molde integ", "pan de molde integral"),
    ],
)
def test_abbreviations(one, text, expected):
    item = one(text)
    assert item.item == expected
    assert item.resolved


def test_abbreviated_units_and_containers(one):
    assert (one("galletas 2 paqs").quantity, one("galletas 2 paqs").unit) == (D(2), "ud")
    assert (one("500 grs de queso").quantity, one("500 grs de queso").unit) == (D(500), "g")
    assert (one("2 lts leche").quantity, one("2 lts leche").unit) == (D(2), "l")


# Joined words -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pandemolde", "pan de molde"),
        ("lechesemi", "leche semidesnatada"),
        ("aceitedeoliva", "aceite de oliva"),
    ],
)
def test_joined_words_are_segmented_against_the_lexicon(one, text, expected):
    item = one(text)
    assert item.item == expected
    assert item.resolved
    assert any(text in c for c in item.corrections)


def test_unknown_long_words_are_not_split(one):
    item = one("salmorejo")
    assert item.item == "salmorejo"
    assert not item.resolved


# Typos --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cafe molio", "café molido"),
        ("lech", "leche"),
        ("lehce entera", "leche entera"),
        ("macarones", "macarrones"),
        ("mantequila", "mantequilla"),
        ("champu", "champú"),
    ],
)
def test_typos_are_corrected_by_fuzzy_matching(one, text, expected):
    item = one(text)
    assert item.item == expected
    assert item.resolved


def test_short_words_and_far_words_are_not_corrected(one):
    assert not one("pam").resolved  # three letters: too short to correct
    assert not one("tofu").resolved  # nothing close enough in the lexicon


# Synonyms -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "generic"),
    [
        ("jugo de naranja", "zumo"),
        ("papel wc", "papel_higienico"),
        ("yogurt natural", "yogur"),
        ("spaghetti", "espaguetis"),
    ],
)
def test_general_synonyms(one, text, generic):
    assert one(text).generic_key == generic


# Quantities and units -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "qty", "unit"),
    [
        ("2 l de leche", "2", "l"),
        ("2l leche", "2", "l"),
        ("leche 2 litros", "2", "l"),
        ("1kg de arroz", "1", "kg"),
        ("arroz 1 kilo", "1", "kg"),
        ("500 g de queso", "500", "g"),
        ("750 ml de vino", "750", "ml"),
        ("33 cl de cerveza", "330", "ml"),
        ("medio kilo de carne picada", "0.5", "kg"),
        ("un cuarto de kilo de queso", "0.25", "kg"),
        ("tres cuartos de kilo de queso", "0.75", "kg"),
        ("kilo y medio de patatas", "1.5", "kg"),
        ("1,5 kg de naranjas", "1.5", "kg"),
        ("1.5 kg de naranjas", "1.5", "kg"),
        ("1/2 kg de tomates", "0.5", "kg"),
        ("una docena de huevos", "12", "ud"),
        ("media docena de huevos", "6", "ud"),
        ("dos docenas de huevos", "24", "ud"),
        ("12 huevos", "12", "ud"),
        ("huevos 12", "12", "ud"),
        ("tres tomates", "3", "ud"),
        ("una lechuga", "1", "ud"),
        ("yogures x8", "8", "ud"),
        ("x3 yogures", "3", "ud"),
        ("2 paquetes de galletas", "2", "ud"),
        ("leche entera 6 bricks", "6", "ud"),
        ("atún en aceite pack de 3", "3", "ud"),
        ("agua mineral 6x1,5 l", "9", "l"),
        ("agua mineral 6 x 1,5 l", "9", "l"),
        ("cerveza 6 x 33 cl", "1980", "ml"),
        ("pan", "1", "ud"),
    ],
)
def test_quantity_forms(one, text, qty, unit):
    item = one(text)
    assert (item.quantity, item.unit) == (D(qty), unit), item
    assert item.resolved


def test_container_word_that_is_part_of_the_product(one):
    item = one("2 bolsas de basura")
    assert (item.item, item.quantity, item.unit) == ("bolsas de basura", D(2), "ud")
    assert item.resolved


def test_number_words_inside_a_phrase_are_not_quantities(one):
    item = one("algo para una cena")
    assert item.quantity == D(1)
    assert item.item == "algo para una cena"


# Numbers in product names -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "qty", "unit"),
    [
        ("pastillas omega 3", "pastillas omega 3", "1", "ud"),
        ("omega 3 x2", "omega 3", "2", "ud"),
        ("carpetas A3", "carpetas a3", "1", "ud"),
        ("leche 0%", "leche 0%", "1", "ud"),
        ("leche 0 %", "leche 0%", "1", "ud"),
        ("pan 7 cereales", "pan 7 cereales", "1", "ud"),
        ("pan 7 cereales 2 paquetes", "pan 7 cereales", "2", "ud"),
        ("yogur 0% materia grasa", "yogur 0%", "1", "ud"),
        ("3 yogures", "yogures", "3", "ud"),
        ("3x yogures", "yogures", "3", "ud"),
        ("yogur x4", "yogur", "4", "ud"),
        ("2 l de leche", "leche", "2", "l"),
        ("huevos 12", "huevos", "12", "ud"),
    ],
)
def test_numbers_that_belong_to_the_name_are_not_quantities(one, text, expected, qty, unit):
    item = one(text)
    assert (item.item, item.quantity, item.unit) == (expected, D(qty), unit), item


def test_product_names_with_numbers_resolve(one):
    assert one("pastillas omega 3").generic_key == "omega_3"
    assert one("omega 3 x2").resolved
    item = one("pan 7 cereales")
    assert (item.generic_key, item.attributes) == ("pan", ("7 cereales",))
    assert item.resolved
    item = one("leche 0%")
    assert item.generic_key == "leche"
    assert item.resolved


# Brands --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Coca-Cola zero 2 l", "coca cola zero 2l", "cocacola zero 2 l"])
def test_brand_spellings(one, text):
    item = one(text)
    assert item.brand == "Coca-Cola"
    assert item.generic_key == "refresco_cola"  # implied by the brand
    assert item.attributes == ("zero",)
    assert (item.quantity, item.unit) == (D(2), "l")
    assert item.resolved


def test_brand_with_a_generic_product(one):
    item = one("leche pascual desnatada 6 bricks")
    assert (item.brand, item.item, item.quantity) == ("Pascual", "leche desnatada", D(6))


def test_eponymous_brands(one):
    assert one("colacao").generic_key == "cacao_soluble"
    assert one("nocilla").generic_key == "crema_cacao"


def test_private_label_brand(one):
    item = one("leche hacendado")
    assert item.brand == "Hacendado"
    assert item.generic_key == "leche"


# Variants ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "attributes"),
    [
        ("pan de molde integral sin gluten", ("sin gluten", "integral")),
        ("leche sin lactosa", ("sin lactosa",)),
        ("leche semidesnatada", ("semidesnatada",)),
        ("yogur desnatado", ("desnatada",)),
        ("refresco de cola zero", ("zero",)),
        ("café descafeinado", ("descafeinado",)),
        ("helado de chocolate", ("chocolate",)),
    ],
)
def test_variants(one, text, attributes):
    item = one(text)
    assert set(item.attributes) == set(attributes)
    assert item.resolved


def test_longest_product_wins_over_product_plus_variant(one):
    assert one("tomate frito").generic_key == "tomate_frito"
    assert one("aceite de oliva virgen extra").generic_key == "aceite_oliva_ve"
    assert one("leche de avena").generic_key == "bebida_avena"
    assert one("patatas fritas").generic_key == "patatas_fritas"


# Splitting -----------------------------------------------------------------------


def test_lines_split_on_commas_newlines_and_semicolons_but_not_decimals(pp):
    items = pp.preprocess("1,5 kg de naranjas, pan\nleche; huevos\n- café molido").items
    assert [i.generic_key for i in items] == ["naranja", "pan", "leche", "huevo", "cafe_molido"]
    assert items[0].quantity == D("1.5")


def test_and_splits_only_when_both_halves_resolve(pp):
    assert [i.item for i in pp.preprocess("pan y leche").items] == ["pan", "leche"]
    assert len(pp.preprocess("kilo y medio de patatas").items) == 1
    assert [i.item for i in pp.preprocess("fruta, y algo para picar").items] == [
        "fruta",
        "algo para picar",
    ]


# Alternatives ---------------------------------------------------------------------


@pytest.mark.parametrize("text", ["pasta/espaguetis", "Pasta / espaguetis", "pasta o espaguetis"])
def test_alternatives_are_one_item(one, text):
    item = one(text)
    assert item.item == "pasta o espaguetis"
    assert item.generic_key == "pasta"  # both are specific: the first one
    assert item.alternatives == ("espaguetis",)
    assert item.resolved


def test_alternatives_prefer_a_specific_product(one):
    item = one("leche/bebida de avena")
    assert (item.item, item.generic_key) == ("leche o bebida de avena", "leche")
    assert item.alternatives == ("bebida de avena",)
    item = one("fruta/plátanos")  # "fruta" is vague
    assert (item.generic_key, item.alternatives) == ("platano", ("fruta",))
    assert item.resolved
    assert not item.ambiguous


def test_alternatives_keep_quantity_and_context(one):
    item = one("2 l de leche/bebida de avena")
    assert (item.item, item.quantity, item.unit) == ("leche o bebida de avena", D(2), "l")
    item = one("pan/tostadas para el desayuno")
    assert (item.generic_key, item.context) == ("pan", "para el desayuno")


def test_unknown_alternative_does_not_block(one):
    item = one("pasta/tallarines")
    assert (item.generic_key, item.alternatives) == ("pasta", ("tallarines",))
    assert item.resolved


def test_slash_between_digits_is_still_a_fraction(one):
    item = one("1/2 kg de queso")
    assert (item.item, item.quantity, item.unit, item.alternatives) == (
        "queso",
        D("0.5"),
        "kg",
        (),
    )


def test_alternatives_stay_out_of_the_item_schema(pp):
    schema = pp.preprocess("pasta/espaguetis").to_schema()
    assert set(schema["items"][0]) == {
        "item",
        "quantity",
        "unit",
        "brand",
        "attributes",
        "ambiguous",
    }


def test_or_and_and_together(pp):
    assert [i.item for i in pp.preprocess("pan y leche o zumo").items] == [
        "pan",
        "leche o zumo",
    ]
    assert [i.item for i in pp.preprocess("leche/zumo y huevos").items] == [
        "leche o zumo",
        "huevos",
    ]


# Ambiguity and context ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "algo para la cena",
        "lo de siempre para el desayuno",
        "algo rico para una cena con amigos el sábado",
        "cosas para el finde",
    ],
)
def test_ambiguous_lines_go_to_the_llm(one, text):
    item = one(text)
    assert item.ambiguous
    assert item.needs_llm


def test_vague_categories_are_ambiguous(one):
    item = one("algo de fruta para la semana")
    assert item.item == "fruta"
    assert item.ambiguous
    assert not item.resolved


def test_purpose_phrase_is_context_not_a_product(one):
    item = one("galletas para el desayuno")
    assert item.resolved
    assert item.item == "galletas"
    assert item.context == "para el desayuno"


def test_unknown_words_send_the_line_to_the_llm(one):
    item = one("leche de chufa")
    assert item.generic_key == "leche"
    assert not item.resolved
    assert any(r.startswith("unknown_words") for r in item.reasons)


# Output -----------------------------------------------------------------------------


def test_output_follows_the_item_schema(pp):
    result = pp.preprocess("2 litros de leche sin lactosa\nalgo para la cena\nCoca-Cola 2 l")
    schema = result.to_schema()
    assert schema["items"][0] == {
        "item": "leche sin lactosa",
        "quantity": 2,
        "unit": "l",
        "brand": None,
        "attributes": ["sin lactosa"],
        "ambiguous": False,
    }
    assert schema["items"][1]["ambiguous"] is True
    assert result.llm_lines == (1,)
    assert result.llm_input() == "algo para la cena"
    assert result.resolved_share == pytest.approx(2 / 3)


def test_deterministic(pp):
    text = "lech semi, pandemolde, 2 paqs d galletas, cafe molio, algo para picar"
    assert pp.preprocess(text) == pp.preprocess(text)


def test_works_with_any_lexicon():
    lexicon = InMemoryLexicon([GenericTerm("tofu", "tofu", ("tofu",), "kg", D("0.25"))])
    item = Preprocessor(lexicon).preprocess("2 bloques de tofu").items[0]
    assert item.generic_key == "tofu"
    assert item.quantity == D(2)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("limones", "limones"),
        ("calabacines", "calabacines"),
        ("platanos", "plátanos"),
        ("cafe", "café"),
    ],
)
def test_accents_on_plurals(one, text, shown):
    assert one(text).item == shown
