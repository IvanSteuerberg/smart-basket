"""Parsing and size normalization of the Mercadona API shapes, with synthetic fixtures."""

from decimal import Decimal as D

import pytest

from smart_basket.ingestion.base import CategoryObservation, ProductObservation
from smart_basket.ingestion.mercadona import (
    normalize_size,
    parse_product,
    parse_section,
    parse_tree,
)


def make_product(
    *,
    sku: str = "1",
    display_name: str = "Producto",
    unit_price: str | None = "1.00",
    bulk_price: str | None = "1.00",
    unit_size: object = 1.0,
    size_format: str | None = "l",
    is_pack: bool = False,
    total_units: object = None,
    published: bool = True,
) -> dict[str, object]:
    return {
        "id": sku,
        "display_name": display_name,
        "packaging": "Botella",
        "share_url": f"https://example.test/product/{sku}",
        "published": published,
        "price_instructions": {
            "unit_price": unit_price,
            "bulk_price": bulk_price,
            "reference_format": "L",
            "unit_size": unit_size,
            "size_format": size_format,
            "is_pack": is_pack,
            "pack_size": total_units,
            "total_units": total_units,
        },
    }


@pytest.mark.parametrize(
    ("size", "size_format", "quantity", "unit"),
    [
        (1000, "g", D("1"), "kg"),
        (2.5, "kg", D("2.5"), "kg"),
        (750, "ml", D("0.75"), "l"),
        (75, "cl", D("0.75"), "l"),
        (1.5, "l", D("1.5"), "l"),
        (6, "ud", D("6"), "ud"),
        (250, "ML", D("0.25"), "l"),
    ],
)
def test_normalize_size_converts_to_base_units(size, size_format, quantity, unit):
    assert normalize_size(size, size_format) == (quantity, unit)


@pytest.mark.parametrize(
    ("size", "size_format"),
    [(12, "oz"), (None, "l"), (0, "kg"), (-1, "kg"), (1, None)],
)
def test_normalize_size_leaves_unknown_or_missing_sizes_empty(size, size_format):
    assert normalize_size(size, size_format) == (None, None)


def test_padded_price_strings_are_parsed():
    observation = parse_product(
        make_product(unit_price="       5.10 ", bulk_price=" 3.35  "), "420"
    )
    assert observation is not None
    assert observation.price == D("5.10")
    assert observation.price_per_unit == D("3.35")


def test_pack_sets_pack_count_and_per_item_size():
    observation = parse_product(
        make_product(unit_size=250, size_format="ml", is_pack=True, total_units=4), "420"
    )
    assert observation is not None
    assert observation.base_quantity == D("0.25")
    assert observation.base_unit == "l"
    assert observation.pack_count == 4


def test_product_without_pack_is_one_unit():
    observation = parse_product(make_product(), "420")
    assert observation is not None
    assert observation.pack_count == 1


def test_unknown_size_format_keeps_both_size_columns_empty():
    observation = parse_product(make_product(unit_size=12, size_format="oz"), "420")
    assert observation is not None
    assert (observation.base_quantity, observation.base_unit) == (None, None)


def test_unpublished_product_is_skipped():
    assert parse_product(make_product(published=False), "420") is None


def test_product_without_a_price_is_skipped():
    assert parse_product(make_product(unit_price=" "), "420") is None


def test_parse_tree_emits_both_levels(load_fixture):
    categories = list(parse_tree(load_fixture("tree.json")))
    assert CategoryObservation("12", "Aceite, especias y salsas", None) in categories
    assert CategoryObservation("112", "Aceite, vinagre y sal", "12") in categories
    assert CategoryObservation("130", "Agua y refrescos", "13") in categories
    parents = {category.code: category.parent_code for category in categories}
    assert parents == {
        "12": None,
        "112": "12",
        "113": "12",
        "13": None,
        "130": "13",
    }


def test_parse_section_emits_level_three_and_products(load_fixture):
    observations = list(parse_section(load_fixture("category-112.json"), "112"))
    categories = [o for o in observations if isinstance(o, CategoryObservation)]
    products = [o for o in observations if isinstance(o, ProductObservation)]
    assert categories == [
        CategoryObservation("420", "Aceite de oliva", "112"),
        CategoryObservation("421", "Vinagre", "112"),
    ]
    assert [product.sku for product in products] == ["4241", "4242", "4241", "4243"]
    assert products[0].category_code == "420"
    assert products[1].category_code == "420"
    assert products[2].category_code == "421"


def test_parse_section_reads_the_first_section_price(load_fixture):
    products = [
        o
        for o in parse_section(load_fixture("category-112.json"), "112")
        if isinstance(o, ProductObservation) and o.sku == "4241"
    ]
    assert [product.price for product in products] == [D("5.10"), D("5.50")]
