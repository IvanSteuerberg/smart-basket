"""Product selection for one line against the synthetic catalog (database tests)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from smart_basket.optimizer import Unit
from smart_basket.recommender.catalog import Item, build_catalog, load_categories

pytestmark = pytest.mark.db


def entry(world, text: str, category_key: str, quantity: str = "1", unit: str = "kg"):
    with Session(bind=world.connection) as session:
        categories = load_categories(session, {category_key})
        item = Item(
            text=text,
            category_key=category_key,
            quantity=Decimal(quantity),
            unit=Unit(unit),
        )
        (catalog_entry,) = build_catalog(
            session, [item], categories, {world.ids["z1"], world.ids["z2"]}
        )
    return catalog_entry


def names(catalog_entry) -> set[str]:
    return set(catalog_entry.product_names.values())


def test_a_variant_in_the_line_keeps_the_products_that_carry_it(world):
    assert names(entry(world, "pasta integral", "pasta")) == {"Macarrón rayado integral Hacendado"}


def test_a_multiword_variant_is_recognised(world):
    assert names(entry(world, "leche sin lactosa", "leche", "1", "l")) == {
        "Leche sin lactosa Hacendado"
    }


def test_a_variant_no_product_carries_keeps_every_product(world):
    assert names(entry(world, "huevos eco", "huevos", "12", "ud")) == {"Huevos frescos Hacendado"}


def test_processed_products_are_dropped_when_plain_ones_exist(world):
    assert names(entry(world, "pechuga de pollo", "pollo")) == {"Pechugas enteras de pollo"}


def test_a_prepared_product_stays_when_every_product_is_prepared(world):
    assert names(entry(world, "carne picada", "carne")) == {
        "Preparado de carne picada cerdo",
        "Preparado de carne picada mixta",
    }


def test_a_line_asking_for_a_preparation_keeps_the_prepared_product(world):
    assert "Filetes pechuga de pollo marinadas empanadas sin gluten" in names(
        entry(world, "pollo empanado", "pollo")
    )


def test_a_counted_line_of_a_weighed_leaf_uses_the_median_pack(world):
    # Sizes on sale: 0.46, 0.60, 0.63 and 0.63 kg; the lower median of an even count is 0.60.
    catalog_entry = entry(world, "pollo", "pollo", "1", "ud")
    assert catalog_entry.line.default_quantity == Decimal("0.60")
