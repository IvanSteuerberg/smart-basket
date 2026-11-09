"""How `collect` folds adapter observations into a final status."""

from decimal import Decimal as D

from smart_basket.ingestion.base import ProductObservation, SkippedProduct, collect


class ScriptedAdapter:
    """An adapter with a fixed script; `collect` must only care about what it yields."""

    chain_code = "mercadona"

    def __init__(self, observations: tuple) -> None:
        self.observations = observations

    def crawl(self, zone_code: str, *, max_categories: int | None = None):
        yield from self.observations


def product(index: int) -> ProductObservation:
    return ProductObservation(
        sku=str(index),
        name=f"Producto {index}",
        packaging=None,
        url=None,
        category_code="112",
        base_quantity=None,
        base_unit=None,
        pack_count=1,
        price=D("1.00"),
        price_per_unit=None,
    )


def skipped(index: int) -> SkippedProduct:
    return SkippedProduct(
        url="https://example.test/api/categories/112/",
        error=f"product {index} skipped: missing name",
    )


def products(count: int) -> list[ProductObservation]:
    return [product(index) for index in range(count)]


def skipped_products(count: int) -> list[SkippedProduct]:
    return [skipped(index) for index in range(count)]


def test_one_discarded_product_out_of_two_hundred_keeps_the_run_complete():
    observations = (*products(200), *skipped_products(1))

    result = collect(ScriptedAdapter(observations), "W1")

    assert result.status == "succeeded"
    assert result.complete is True
    assert len(result.errors) == 1


def test_three_discarded_products_out_of_two_hundred_make_the_run_partial():
    observations = (*products(200), *skipped_products(3))

    result = collect(ScriptedAdapter(observations), "W1")

    assert result.status == "partial"
    assert result.complete is False
    assert len(result.errors) == 3
