"""Product selection for one line through canonical products (database tests)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.optimizer import Unit
from smart_basket.recommender.catalog import (
    Item,
    UnknownProduct,
    build_catalog,
    load_categories,
)

pytestmark = pytest.mark.db


def entry(
    world,
    text: str,
    category_key: str | None = None,
    quantity: str = "1",
    unit: str = "kg",
    *,
    product: str | None = None,
    accept: str = "equivalent",
    variants: tuple[str, ...] | None = None,
):
    with Session(bind=world.connection) as session:
        categories = load_categories(session, {category_key} if category_key else set())
        item = Item(
            text=text,
            category_key=category_key,
            product_id=product_id(world, product) if product else None,
            accept=accept,
            variants=variants,
            quantity=Decimal(quantity),
            unit=Unit(unit),
        )
        (catalog_entry,) = build_catalog(
            session, [item], categories, {world.ids["z1"], world.ids["z2"]}
        )
    return catalog_entry


def product_id(world, sku: str) -> int:
    if sku.isdigit():
        return int(sku)
    return world.connection.execute(
        text("select id from chain_product where chain_sku = :sku"), {"sku": sku}
    ).scalar_one()


def names(catalog_entry) -> set[str]:
    return set(catalog_entry.product_names.values())


def test_a_generic_line_takes_the_canonicals_whose_variant_set_is_empty(world):
    # "leche" asks for no variant, so the semi-skimmed, skimmed and lactose-free canonicals
    # are not exact matches; only the plain canonical products remain.
    assert names(entry(world, "leche", "leche", "1", "l")) == {
        "Leche entera Pascual",
    }


def test_a_canonical_variant_selects_its_canonical(world):
    assert names(entry(world, "leche semidesnatada", "leche", "1", "l")) == {
        "Leche semidesnatada Hacendado"
    }


def test_the_variant_set_is_a_superset_when_no_exact_match_exists(world):
    # No canonical is exactly "sin gluten", but the wholemeal gluten-free pasta carries it.
    assert names(entry(world, "pasta sin gluten", "pasta", "0.5", "kg")) == {
        "Macarrón integral sin gluten Hacendado",
    }


def test_a_variant_no_product_carries_leaves_no_candidates(world):
    # "eco" is a canonical variant and nothing in the leaf carries it.
    assert names(entry(world, "huevos eco", "huevos", "12", "ud")) == set()


def test_non_canonical_variants_filter_products_by_name(world):
    assert names(entry(world, "yogur", "yogur", "4", "ud")) == {
        "Yogur natural Hacendado",
        "Yogur griego Hacendado",
    }
    assert names(entry(world, "yogur natural", "yogur", "4", "ud")) == {"Yogur natural Hacendado"}


def test_products_without_a_canonical_are_never_candidates(world):
    # The frying pan shares the chain category but has no canonical product.
    assert names(entry(world, "panaderia", "panaderia")) == {"Pan de pueblo"}


def test_a_concrete_exact_line_keeps_only_that_product(world):
    catalog_entry = entry(world, "leche sin lactosa", product="L4", accept="exact", unit="ud")
    assert names(catalog_entry) == {"Leche sin lactosa Hacendado"}
    assert catalog_entry.exact is True
    assert catalog_entry.line.quantity == Decimal(1)
    assert catalog_entry.line.unit is Unit.L
    assert catalog_entry.line.preferences.pack_quantity == Decimal(1)


def test_a_concrete_exact_line_buys_the_requested_number_of_packs(world):
    catalog_entry = entry(world, "leche", product="L1", accept="exact", quantity="2", unit="ud")
    assert catalog_entry.line.quantity == Decimal(2)
    assert catalog_entry.line.unit is Unit.L
    assert catalog_entry.line.preferences.pack_quantity == Decimal(1)


def test_a_concrete_equivalent_line_accepts_its_whole_canonical(world):
    catalog_entry = entry(world, "leche sin lactosa", product="L4", unit="ud")
    assert names(catalog_entry) == {"Leche sin lactosa Hacendado", "Leche sin lactosa Dia"}
    assert catalog_entry.exact is False


def test_a_concrete_product_without_a_canonical_behaves_as_exact(world):
    catalog_entry = entry(world, "sarten", product="S1", unit="ud")
    assert names(catalog_entry) == {"Sartén antiadherente"}


def test_an_unknown_product_is_reported(world):
    with pytest.raises(UnknownProduct):
        entry(world, "no existe", product="999999")


def test_a_counted_line_of_a_weighed_leaf_uses_the_median_pack(world):
    # Sizes on sale: 0.46, 0.46, 0.60, 0.63 and 0.63 kg; the lower median of an even count is 0.60.
    catalog_entry = entry(world, "pollo", "pollo", "1", "ud")
    assert catalog_entry.line.default_quantity == Decimal("0.60")
