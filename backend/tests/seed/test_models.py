"""Validation of the seed models and of the cross-file references (no database)."""

import pytest
from pydantic import ValidationError

from smart_basket.seed.models import (
    BrandsFile,
    ChainCategoriesFile,
    ChainsFile,
    TaxonomyFile,
    validate_seed,
)


def node(key: str, name: str | None = None, **fields) -> dict:
    return {"key": key, "name": name or key, **fields}


def taxonomy_file(*categories: dict) -> TaxonomyFile:
    return TaxonomyFile.model_validate({"version": 1, "categories": list(categories)})


def chains_file(*chains: dict) -> ChainsFile:
    return ChainsFile.model_validate({"version": 1, "chains": list(chains)})


def mapping_file(chain: str, *categories: dict) -> ChainCategoriesFile:
    return ChainCategoriesFile.model_validate(
        {"version": 1, "chain": chain, "categories": list(categories)}
    )


def brands_file(*brands: dict) -> BrandsFile:
    return BrandsFile.model_validate({"version": 1, "brands": list(brands)})


def chain(code: str = "mercadona", **fields) -> dict:
    return {"code": code, "name": code.title(), **fields}


def test_fixture_seed_validates(seed_dir):
    taxonomy = TaxonomyFile.model_validate_json(
        (seed_dir / "taxonomy_es.json").read_text(encoding="utf-8")
    )
    chains = ChainsFile.model_validate_json(
        (seed_dir / "chains_es.json").read_text(encoding="utf-8")
    )
    mapping = ChainCategoriesFile.model_validate_json(
        (seed_dir / "chain_categories" / "mercadona.json").read_text(encoding="utf-8")
    )
    brands = BrandsFile.model_validate_json(
        (seed_dir / "brands_es.json").read_text(encoding="utf-8")
    )
    validate_seed(taxonomy, chains, {"mercadona": mapping}, brands)
    assert [row.key for row in taxonomy.rows()] == [
        "lacteos_huevos",
        "yogures",
        "yogur_griego",
        "yogur_natural",
        "bebidas",
        "agua",
    ]


def test_forms_default_to_the_name_for_leaves_and_empty_for_inner_nodes():
    tree = taxonomy_file(
        node(
            "fruta",
            name="Fruta",
            vague=True,
            children=[node("manzana", name="Manzana", base_unit="kg")],
        )
    )
    rows = {row.key: row for row in tree.rows()}
    assert rows["fruta"].forms == []
    assert rows["fruta"].is_vague is True
    assert rows["manzana"].forms == ["manzana"]
    assert rows["manzana"].level == 2


def test_leaf_without_base_unit_is_rejected():
    with pytest.raises(ValidationError, match="leaf category 'hoja' has no base_unit"):
        taxonomy_file(node("hoja", name="Hoja"))


def test_repeated_key_is_rejected():
    with pytest.raises(ValidationError, match="duplicate category key 'repetida'"):
        taxonomy_file(
            node("repetida", name="A", base_unit="kg"),
            node("repetida", name="B", base_unit="kg"),
        )


def test_key_with_invalid_characters_is_rejected():
    with pytest.raises(ValidationError, match="Mal Clave"):
        taxonomy_file(node("Mal Clave", name="Mala"))


def test_more_than_three_levels_is_rejected():
    tree = node(
        "n1",
        children=[node("n2", children=[node("n3", children=[node("n4", base_unit="kg")])])],
    )
    with pytest.raises(ValidationError, match="category 'n4' is deeper than 3 levels"):
        taxonomy_file(tree)


def test_duplicate_sibling_name_is_rejected():
    with pytest.raises(ValidationError, match="duplicate category name"):
        taxonomy_file(
            node("a", name="Mismo", base_unit="kg"),
            node("b", name="Mismo", base_unit="kg"),
        )


def test_a_form_cannot_belong_to_two_categories():
    with pytest.raises(ValidationError, match="form 'yogur' belongs to both categories"):
        taxonomy_file(
            node("yogur_griego", name="Yogur griego", base_unit="kg", forms=[" Yogur "]),
            node("yogur_natural", name="Yogur natural", base_unit="kg", forms=["yogur"]),
        )


def test_invalid_base_unit_and_quantity_are_rejected():
    with pytest.raises(ValidationError, match="base_unit"):
        taxonomy_file(node("a", base_unit="g"))
    with pytest.raises(ValidationError, match="default_quantity"):
        taxonomy_file(node("b", base_unit="kg", default_quantity=0))


def test_duplicate_chain_code_is_rejected():
    with pytest.raises(ValidationError, match="duplicate chain code 'mercadona'"):
        chains_file(chain("mercadona"), chain("mercadona"))


def test_chain_wide_zone_must_use_code_all():
    with pytest.raises(ValidationError, match="must use code 'all'"):
        chains_file(chain(zones=[{"kind": "chain", "code": "other"}]))


def test_chain_wide_zone_with_code_all_is_accepted():
    chains = chains_file(chain(zones=[{"kind": "chain", "code": "all", "name": "Todas"}]))
    assert chains.chains[0].zones[0].code == "all"


def test_duplicate_zone_is_rejected():
    zones = [{"kind": "warehouse", "code": "1"}, {"kind": "warehouse", "code": "1"}]
    with pytest.raises(ValidationError, match="duplicate zone '1'"):
        chains_file(chain(zones=zones))


def test_unknown_parent_code_is_rejected():
    with pytest.raises(ValidationError, match="parent_code '2'"):
        mapping_file("mercadona", {"code": "1", "name": "A", "parent_code": "2"})


def test_parent_code_cycle_is_rejected():
    with pytest.raises(ValidationError, match="parent_code cycle at chain category '1'"):
        mapping_file(
            "mercadona",
            {"code": "1", "name": "A", "parent_code": "2"},
            {"code": "2", "name": "B", "parent_code": "1"},
        )


def test_repeated_chain_category_code_is_rejected():
    with pytest.raises(ValidationError, match="duplicate chain category code '1'"):
        mapping_file("mercadona", {"code": "1", "name": "A"}, {"code": "1", "name": "B"})


def test_mapping_to_unknown_taxonomy_key_is_rejected():
    taxonomy = taxonomy_file(node("fruta", base_unit="kg"))
    chains = chains_file(chain())
    mapping = mapping_file("mercadona", {"code": "1", "name": "A", "category": "no_existe"})
    with pytest.raises(ValueError, match="no_existe"):
        validate_seed(taxonomy, chains, {"mercadona": mapping}, brands_file())


def test_mapping_of_unknown_chain_is_rejected():
    taxonomy = taxonomy_file(node("fruta", base_unit="kg"))
    chains = chains_file(chain())
    mapping = mapping_file("carrefour")
    with pytest.raises(ValueError, match="chain 'carrefour'"):
        validate_seed(taxonomy, chains, {"carrefour": mapping}, brands_file())


def test_mapping_file_name_must_match_its_chain():
    taxonomy = taxonomy_file(node("fruta", base_unit="kg"))
    chains = chains_file(chain())
    with pytest.raises(ValueError, match="declares chain 'mercadona'"):
        validate_seed(taxonomy, chains, {"otra": mapping_file("mercadona")}, brands_file())


def test_aliases_are_lower_case_and_trimmed():
    brands = brands_file({"name": "Marca", "aliases": ["  Alias  "]})
    assert brands.brands[0].aliases == ["alias"]


def test_repeated_brand_name_is_rejected():
    with pytest.raises(ValidationError, match="duplicate brand name 'marca'"):
        brands_file({"name": "Marca"}, {"name": "marca"})


def test_repeated_alias_within_a_brand_is_rejected():
    with pytest.raises(ValidationError, match="duplicate alias 'alias'"):
        brands_file({"name": "Marca", "aliases": ["alias", " Alias "]})


def test_alias_shared_by_two_brands_is_rejected():
    with pytest.raises(ValidationError, match="alias 'comun' belongs to both brands"):
        brands_file({"name": "Marca", "aliases": ["comun"]}, {"name": "Otra", "aliases": ["comun"]})


def test_private_label_and_implies_must_reference_seed_files():
    taxonomy = taxonomy_file(node("agua", base_unit="l"))
    chains = chains_file(chain())
    valid = brands_file({"name": "Marca", "private_label_of": "mercadona", "implies": "agua"})
    validate_seed(taxonomy, chains, {}, valid)
    with pytest.raises(ValueError, match="unknown taxonomy category 'no_existe'"):
        validate_seed(taxonomy, chains, {}, brands_file({"name": "Marca", "implies": "no_existe"}))
    with pytest.raises(ValueError, match="unknown chain 'otra'"):
        validate_seed(
            taxonomy, chains, {}, brands_file({"name": "Marca", "private_label_of": "otra"})
        )
