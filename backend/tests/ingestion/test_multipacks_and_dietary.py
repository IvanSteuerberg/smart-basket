"""Multipack sizes, the unit-price outlier guard and FR-42 dietary tags (task I17-E1).

The pure cases cover the parsers shared by every adapter; the database cases need a disposable
PostgreSQL (`TEST_DATABASE_URL`) and run the catalog-quality backfill and the store against it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal as D
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from smart_basket.db import session_scope
from smart_basket.db.migrate import alembic_config
from smart_basket.ingestion import (
    CategoryObservation,
    ProductObservation,
    backfill_catalog_quality,
    ingest_catalog,
)
from smart_basket.ingestion.carrefour import parse_carrefour_product
from smart_basket.ingestion.dia import parse_dia_size
from smart_basket.ingestion.quality import (
    derived_price_per_unit,
    extract_dietary_tags,
    is_unit_price_outlier,
    reparse_multipack_from_name,
    sanitize_unit_pricing,
)

URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.mark.parametrize(
    ("name", "quantity", "unit", "pack"),
    [
        ("Actimel 12 x 100 g", D("0.1"), "kg", 12),
        ("Vitalinea 4x100g", D("0.1"), "kg", 4),
        ("Danone pack 4 x 125 g", D("0.125"), "kg", 4),
        ("Cerveza pack 6 x 33 cl", D("0.33"), "l", 6),
        ("Actimel pack 6", D("1"), "ud", 6),
        ("Pack de 8 botellas", D("1"), "ud", 8),
    ],
)
def test_parse_dia_size_keeps_compact_and_count_only_multipacks(name, quantity, unit, pack):
    assert parse_dia_size(name) == (quantity, unit, pack)


def test_reparse_multipack_delegates_to_the_dia_parser():
    assert reparse_multipack_from_name("Danone pack 4 x 125 g") == (D("0.125"), "kg", 4)


def _carrefour_item(name: str, price: float, **extra: object) -> dict[str, object]:
    slug = name.casefold().replace(" ", "-")
    return {
        "key": f"/carrefour/p/{slug}-carrefour",
        "name": name,
        "price": price,
        "url": f"/carrefour/p/{slug}-carrefour",
        **extra,
    }


def test_carrefour_keeps_the_pack_count_and_divides_by_the_whole_pack():
    product = parse_carrefour_product(
        _carrefour_item("Actimel 12 x 100 g", 5.99), category_code="yogures"
    )

    assert product is not None
    assert (product.base_quantity, product.base_unit) == (D("0.1"), "kg")
    assert product.pack_count == 12
    assert product.price_per_unit == D("4.9917")


def test_carrefour_prefers_the_per_unit_size_of_the_multipack_name():
    item = _carrefour_item("Actimel 12 x 100 g", 5.99, size=1200, unit="g")

    product = parse_carrefour_product(item, category_code="yogures")

    assert product is not None
    assert (product.base_quantity, product.pack_count) == (D("0.1"), 12)
    assert product.price_per_unit == D("4.9917")


def test_carrefour_count_only_pack_keeps_the_raw_per_unit_size():
    item = _carrefour_item("Actimel pack 6", 2.40, size=100, unit="g")

    product = parse_carrefour_product(item, category_code="yogures")

    assert product is not None
    assert (product.base_quantity, product.base_unit) == (D("0.1"), "kg")
    assert product.pack_count == 6
    assert product.price_per_unit == D("4.0000")


@pytest.mark.parametrize(
    ("price", "quantity", "unit", "pack", "outlier"),
    [
        ("0.65", "0.0001", "kg", 1, True),  # grams read as kilos: 6500 €/kg
        ("0.65", "0.5", "kg", 1, False),
        ("1.00", "10", "kg", 1, True),  # 0.10 €/kg is below the kg floor
        ("0.40", "10", "kg", 1, False),  # a pack under 0.50 € is exempt from the floor
        ("0.60", "10", "l", 1, True),  # 0.06 €/l is below the litre floor
        ("0.60", "5", "l", 1, False),
        ("6.00", "0.01", "kg", 1, True),  # 600 €/kg is above the ceiling
        ("5.99", "0.1", "kg", 12, False),  # the pack count divides it back to 4.99 €/kg
        ("1.00", "1", "ud", 1, False),
        ("1.00", None, None, 1, False),
    ],
)
def test_is_unit_price_outlier(price, quantity, unit, pack, outlier):
    assert (
        is_unit_price_outlier(D(price), None if quantity is None else D(quantity), unit, pack)
        is outlier
    )


def test_derived_price_per_unit_needs_a_size():
    assert derived_price_per_unit(D("1.00"), D("2"), "kg", 1) == D("0.5000")
    assert derived_price_per_unit(D("1.00"), None, None, 1) is None


def test_sanitize_reparses_a_sane_size_from_the_name():
    pricing = sanitize_unit_pricing(
        "Yogur griego natural 500 g", D("0.65"), D("0.0001"), "kg", 1, price_per_unit=D("6500")
    )

    assert pricing.repaired
    assert (pricing.base_quantity, pricing.base_unit, pricing.pack_count) == (D("0.5"), "kg", 1)
    assert pricing.price_per_unit == D("1.3000")


def test_sanitize_clears_a_size_the_name_cannot_rescue():
    pricing = sanitize_unit_pricing(
        "Producto sin tamaño", D("0.60"), D("0.0001"), "kg", 1, price_per_unit=D("6000")
    )

    assert pricing.repaired
    assert (pricing.base_quantity, pricing.base_unit, pricing.price_per_unit) == (
        None,
        None,
        None,
    )


def test_sanitize_leaves_a_sane_observation_untouched():
    pricing = sanitize_unit_pricing(
        "Aceite de oliva 1 l", D("3.00"), D("1"), "l", 1, price_per_unit=D("3.00")
    )

    assert not pricing.repaired
    assert (
        pricing.base_quantity,
        pricing.base_unit,
        pricing.pack_count,
        pricing.price_per_unit,
    ) == (D("1"), "l", 1, D("3.00"))


@pytest.mark.parametrize(
    ("text", "tags"),
    [
        ("Yogur natural sin gluten", ("sin_gluten",)),
        ("Pan gluten free", ("sin_gluten",)),
        ("Galletas 0% gluten", ("sin_gluten",)),
        ("Leche sin lactosa", ("sin_lactosa",)),
        ("Bebida lactose free", ("sin_lactosa",)),
        ("Postre 0% lactosa", ("sin_lactosa",)),
        ("Bebida de avena vegano", ("vegano",)),
        ("Hamburguesa vegana", ("vegano",)),
        ("Snack vegan", ("vegano",)),
        ("Bebida 100% vegetal", ("vegano",)),
        ("Queso vegetariano", ("vegetariano",)),
        ("Hamburguesa veggie", ("vegetariano",)),
        ("Aceite ecologico", ("ecologico",)),
        ("Harina organica", ("ecologico",)),
        ("Producto bio", ("ecologico",)),
        ("Tomate eco", ("ecologico",)),
        ("Ahorro eco en tu compra", ()),
        ("Producto economico", ()),
        ("Zumo sin azucar", ("sin_azucar",)),
        ("Galletas sin azucares anadidos", ("sin_azucar",)),
        ("Refresco zero azucar", ("sin_azucar",)),
        ("Bebida 0% azucares", ("sin_azucar",)),
        ("Galletas con gluten", ()),
        ("Harina con trazas de gluten", ()),
        ("Producto puede contener gluten", ()),
        ("Pan no sin gluten", ()),
        ("Leche con lactosa", ()),
        ("Bebida con trazas de lactosa", ()),
        ("Postre puede contener lactosa", ()),
        ("Leche no sin lactosa", ()),
    ],
)
def test_extract_dietary_tags_only_reads_explicit_declarations(text, tags):
    assert extract_dietary_tags(text) == tags


def test_dietary_tags_are_sorted_unique_and_read_the_packaging():
    assert extract_dietary_tags("Producto vegano sin gluten sin lactosa ecologico") == (
        "ecologico",
        "sin_gluten",
        "sin_lactosa",
        "vegano",
    )
    assert extract_dietary_tags("Tomate frito", "Sin gluten") == ("sin_gluten",)
    assert extract_dietary_tags("", None) == ()


def test_a_negation_vetoes_only_its_own_tag():
    assert extract_dietary_tags("Producto sin gluten sin lactosa con trazas de gluten") == (
        "sin_lactosa",
    )


# --- Database: the catalog-quality backfill and the store against PostgreSQL ---------------


@dataclass(frozen=True)
class Db:
    url: str
    engine: Engine
    chain_id: int
    zone_id: int


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    cfg = alembic_config(URL)
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Db:
    with engine.begin() as conn:
        conn.execute(text("truncate table chain restart identity cascade"))
        chain_id = conn.execute(
            text("insert into chain (code, name) values ('carrefour', 'Carrefour') returning id")
        ).scalar_one()
        zone_id = conn.execute(
            text(
                "insert into zone (chain_id, kind, code) "
                "values (:chain, 'salepoint', '0001') returning id"
            ),
            {"chain": chain_id},
        ).scalar_one()
    return Db(url=URL, engine=engine, chain_id=chain_id, zone_id=zone_id)


def rows(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def scalar(db: Db, sql: str, **params):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def add_product(
    db: Db,
    sku: str,
    name: str,
    *,
    price: str,
    price_per_unit: str,
    quantity: str | None,
    unit: str | None,
    pack_count: int = 1,
    packaging: str | None = None,
) -> int:
    with db.engine.begin() as conn:
        product_id = conn.execute(
            text(
                "insert into chain_product (chain_id, chain_sku, name, packaging, base_quantity, "
                "base_unit, pack_count) values (:chain, :sku, :name, :packaging, :quantity, "
                ":unit, :pack) returning id"
            ),
            {
                "chain": db.chain_id,
                "sku": sku,
                "name": name,
                "packaging": packaging,
                "quantity": None if quantity is None else D(quantity),
                "unit": unit,
                "pack": pack_count,
            },
        ).scalar_one()
        conn.execute(
            text(
                "insert into price_current (chain_product_id, zone_id, price, price_per_unit, "
                "valid_from) values (:product, :zone, :price, :ppu, now())"
            ),
            {
                "product": product_id,
                "zone": db.zone_id,
                "price": D(price),
                "ppu": D(price_per_unit),
            },
        )
    return product_id


def stored(db: Db, sku: str):
    return rows(
        db,
        "select p.base_quantity, p.base_unit, p.pack_count, p.dietary_tags, "
        "c.price_per_unit from chain_product p "
        "join price_current c on c.chain_product_id = p.id where p.chain_sku = :sku",
        sku=sku,
    )[0]


@pytest.mark.db
@needs_db
def test_backfill_fixes_multipacks_outliers_and_dietary_tags(db):
    add_product(
        db,
        "actimel",
        "Actimel 12 x 100 g",
        price="5.99",
        price_per_unit="59.90",
        quantity="0.1",
        unit="kg",
    )
    add_product(
        db,
        "yogur",
        "Yogur griego natural 500 g",
        price="0.65",
        price_per_unit="6500",
        quantity="0.0001",
        unit="kg",
    )
    add_product(
        db,
        "agua",
        "Agua mineral 1,5 l",
        price="0.50",
        price_per_unit="0.01",
        quantity="1.5",
        unit="l",
    )
    add_product(
        db,
        "raro",
        "Producto sin tamaño",
        price="0.60",
        price_per_unit="6000",
        quantity="0.0001",
        unit="kg",
    )
    add_product(
        db,
        "leche",
        "Leche entera sin lactosa 1 l",
        price="1.00",
        price_per_unit="1.00",
        quantity="1",
        unit="l",
    )
    add_product(
        db,
        "gluten",
        "Bebida con trazas de gluten",
        price="1.00",
        price_per_unit="1.00",
        quantity="1",
        unit="l",
    )

    summary = backfill_catalog_quality(db.url)

    assert summary.products == 6
    assert (summary.multipacks_fixed, summary.outliers_sanitized, summary.dietary_tagged) == (
        1,
        3,
        1,
    )
    actimel = stored(db, "actimel")
    assert (actimel.base_quantity, actimel.base_unit, actimel.pack_count) == (
        D("0.1"),
        "kg",
        12,
    )
    assert actimel.price_per_unit == D("4.9917")
    yogur = stored(db, "yogur")
    assert (yogur.base_quantity, yogur.base_unit) == (D("0.5"), "kg")
    assert yogur.price_per_unit == D("1.3")
    agua = stored(db, "agua")
    assert (agua.base_quantity, agua.price_per_unit) == (D("1.5"), D("0.3333"))
    raro = stored(db, "raro")
    assert (raro.base_quantity, raro.base_unit, raro.price_per_unit) == (None, None, None)
    assert stored(db, "leche").dietary_tags == ["sin_lactosa"]
    assert stored(db, "gluten").dietary_tags == []


@pytest.mark.db
@needs_db
def test_the_catalog_quality_backfill_is_idempotent(db):
    add_product(
        db,
        "actimel",
        "Actimel 12 x 100 g",
        price="5.99",
        price_per_unit="59.90",
        quantity="0.1",
        unit="kg",
    )
    add_product(
        db,
        "yogur",
        "Yogur griego natural 500 g",
        price="0.65",
        price_per_unit="6500",
        quantity="0.0001",
        unit="kg",
    )

    backfill_catalog_quality(db.url)
    again = backfill_catalog_quality(db.url)

    assert again.products == 2
    assert (again.multipacks_fixed, again.outliers_sanitized, again.dietary_tagged) == (0, 0, 0)
    assert stored(db, "actimel").price_per_unit == D("4.9917")
    assert stored(db, "yogur").price_per_unit == D("1.3")


@pytest.mark.db
@needs_db
def test_backfill_accepts_a_session_and_leaves_the_commit_to_the_caller(db):
    add_product(
        db,
        "leche",
        "Leche entera sin lactosa 1 l",
        price="1.00",
        price_per_unit="1.00",
        quantity="1",
        unit="l",
    )

    with session_scope(db.url) as session:
        summary = backfill_catalog_quality(session)

    assert summary.dietary_tagged == 1
    assert scalar(db, "select dietary_tags from chain_product where chain_sku = 'leche'") == [
        "sin_lactosa"
    ]


class FixedAdapter:
    """An adapter with a fixed script, so the store test never touches the network."""

    chain_code = "carrefour"
    zone_kind = "salepoint"

    def __init__(self, observations: tuple) -> None:
        self.observations = observations

    def crawl(self, zone_code: str, *, max_categories: int | None = None):
        yield from self.observations


@pytest.mark.db
@needs_db
def test_store_fills_dietary_tags_and_sanitizes_unit_prices_on_crawls(db, tmp_path: Path):
    observations = (
        CategoryObservation(code="420", name="Lacteos", parent_code=None),
        ProductObservation(
            sku="leche",
            name="Leche entera sin lactosa 1 l",
            packaging=None,
            url=None,
            category_code="420",
            base_quantity=D("1"),
            base_unit="l",
            pack_count=1,
            price=D("1.00"),
            price_per_unit=D("0.01"),
        ),
    )

    ingest_catalog(FixedAdapter(observations), "0001", data_dir=tmp_path, database_url=db.url)

    leche = stored(db, "leche")
    assert leche.dietary_tags == ["sin_lactosa"]
    assert leche.price_per_unit == D("1")
