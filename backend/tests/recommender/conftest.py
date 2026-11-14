"""Synthetic world for the recommendation endpoint: two chains, three stores and a small taxonomy.

Nothing here is collected data: the chains, the products and the prices exist only in the test
database and are rolled back after each test. Every product that a generic line may choose is
matched to a canonical product, as the real catalog does (decision 0004).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session

from smart_basket.api.app import create_app
from smart_basket.api.recommendations import get_routing_engine, get_today
from smart_basket.db import get_session
from smart_basket.db.migrate import alembic_config
from smart_basket.optimizer import TravelTimes
from smart_basket.routing import GeoPoint, RoutingError, StoreLocation, TravelMode

URL = os.environ.get("TEST_DATABASE_URL")
ORIGIN = GeoPoint(42.5987, -5.5671)
STORE_ONE = (42.6, -5.57)
STORE_TWO = (42.61, -5.56)
SEEN_ZONE_ONE = datetime(2026, 11, 13, 5, 7, tzinfo=UTC)
SEEN_ZONE_TWO = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)


class FakeRouting:
    """Deterministic travel times and a shape that follows the given points."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def travel_times(
        self, origin: GeoPoint, stores: Sequence[StoreLocation], mode: TravelMode
    ) -> TravelTimes:
        if self.fail:
            raise RoutingError("routing is down")
        n = len(stores) + 1
        matrix = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    row.append(Decimal(0))
                elif 0 in (i, j):
                    other = j if i == 0 else i
                    row.append(Decimal("4.25") if other == 1 else Decimal(9))
                else:
                    row.append(Decimal(5))
            matrix.append(tuple(row))
        return TravelTimes(tuple(store.store_id for store in stores), tuple(matrix))

    def route_shape(
        self, points: Sequence[GeoPoint], mode: TravelMode
    ) -> list[tuple[float, float]]:
        if self.fail:
            raise RoutingError("routing is down")
        return [(point.latitude, point.longitude) for point in points]


@dataclass
class World:
    ids: dict[str, int]
    client: TestClient
    connection: Connection


@pytest.fixture(scope="session")
def engine():
    if not URL:
        pytest.skip("TEST_DATABASE_URL not set")
    # Start from an empty schema so a leftover of an earlier run cannot break the seed.
    config = alembic_config(URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def world(engine) -> Iterator[World]:
    with engine.connect() as connection:
        transaction = connection.begin()
        ids = _seed(connection)
        session = Session(bind=connection)
        app = create_app()

        def _session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_today] = lambda: date(2026, 11, 13)
        app.dependency_overrides[get_routing_engine] = lambda: FakeRouting()
        with TestClient(app) as client:
            yield World(ids, client, connection)
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()


def scalar(connection: Connection, sql: str, **params):
    return connection.execute(text(sql), params).scalar_one()


def _seed(connection: Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    ids["chain"] = scalar(
        connection, "insert into chain (code, name) values ('mercadona', 'Mercadona') returning id"
    )
    ids["z1"] = _zone(connection, ids["chain"], "24001", "León")
    ids["z2"] = _zone(connection, ids["chain"], "24002", "León norte")
    ids["chain2"] = scalar(
        connection, "insert into chain (code, name) values ('carrefour', 'Carrefour') returning id"
    )
    ids["z3"] = _zone(connection, ids["chain2"], "24003", "León sur")

    ids["lacteos"] = _category(connection, "lacteos", "Lácteos", 1)
    ids["leche"] = _category(connection, "leche", "Leche", 2, ids["lacteos"], "l")
    ids["yogur"] = _category(connection, "yogur", "Yogur", 2, ids["lacteos"], "ud")
    ids["queso"] = _category(connection, "queso", "Queso", 2, ids["lacteos"], "kg")
    ids["fruta"] = _category(connection, "fruta", "Fruta", 1)
    ids["platano"] = _category(connection, "platano", "Plátano", 2, ids["fruta"], "kg")
    ids["huevos"] = _category(connection, "huevos", "Huevos", 1, base_unit="ud")
    ids["arroz"] = _category(connection, "arroz", "Arroz", 1, base_unit="kg")
    ids["panaderia"] = _category(connection, "panaderia", "Panadería", 1)
    ids["pan"] = _category(connection, "pan", "Pan", 2, ids["panaderia"], "kg")
    ids["refresco"] = _category(connection, "refresco", "Refresco", 1, base_unit="ud")
    ids["drogueria"] = _category(connection, "drogueria", "Droguería", 1)
    ids["papel_horno"] = _category(
        connection, "papel_horno", "Papel de horno", 2, ids["drogueria"], "ud"
    )
    ids["aves"] = _category(connection, "aves", "Aves", 1, base_unit="kg")
    ids["pasta"] = _category(connection, "pasta", "Pasta", 1, base_unit="kg")
    ids["arroz_variedad"] = _category(connection, "arroz_variedad", "Arroz", 1, base_unit="kg")
    ids["atun"] = _category(connection, "atun", "Atún", 1, base_unit="ud")
    ids["cerveza"] = _category(connection, "cerveza", "Cerveza", 1, base_unit="ud")
    ids["refresco_cola"] = _category(
        connection, "refresco_cola", "Refresco de cola", 1, base_unit="ud"
    )
    ids["pollo"] = _category(connection, "pollo", "Pollo", 1, base_unit="kg")
    ids["carne"] = _category(connection, "carne", "Carne", 1, base_unit="kg")
    ids["vague"] = _category(
        connection, "vague", "Pollo preparado", 1, base_unit="kg", is_vague=True
    )
    ids["vacio"] = _category(connection, "vacio", "Sin productos", 1, base_unit="ud")
    for category in (
        "lacteos",
        "fruta",
        "huevos",
        "arroz",
        "panaderia",
        "refresco",
        "drogueria",
        "pasta",
        "arroz_variedad",
        "atun",
        "cerveza",
        "refresco_cola",
        "pollo",
        "carne",
        "vague",
        "vacio",
    ):
        _closure(connection, ids[category], ids[category], 0)
    for leaf in ("leche", "yogur", "queso"):
        _closure(connection, ids[leaf], ids[leaf], 0)
        _closure(connection, ids["lacteos"], ids[leaf], 1)
    _closure(connection, ids["platano"], ids["platano"], 0)
    _closure(connection, ids["fruta"], ids["platano"], 1)
    _closure(connection, ids["pan"], ids["pan"], 0)
    _closure(connection, ids["panaderia"], ids["pan"], 1)
    _closure(connection, ids["papel_horno"], ids["papel_horno"], 0)
    _closure(connection, ids["drogueria"], ids["papel_horno"], 1)
    _closure(connection, ids["aves"], ids["aves"], 0)

    _brand(connection, ids["chain"], "Hacendado", private_label=True)
    _brand(connection, ids["chain"], "Dia")
    _brand(connection, ids["chain"], "Pascual")
    _brand(connection, ids["chain"], "Coca Cola", aliases=("cocacola",))
    _brand(connection, ids["chain"], "Puleva")

    categories = {
        "leche": _chain_category(connection, ids["chain"], "121", "Leche", ids["leche"]),
        "yogur": _chain_category(connection, ids["chain"], "122", "Yogur", ids["yogur"]),
        "queso": _chain_category(connection, ids["chain"], "123", "Queso", ids["queso"]),
        "fruta": _chain_category(connection, ids["chain"], "13", "Fruta", ids["fruta"]),
        "huevos": _chain_category(connection, ids["chain"], "14", "Huevos", ids["huevos"]),
        "panaderia": _chain_category(connection, ids["chain"], "15", "Panadería", ids["panaderia"]),
        "refresco": _chain_category(connection, ids["chain"], "16", "Refresco", ids["refresco"]),
        "papel_horno": _chain_category(
            connection, ids["chain"], "17", "Papel de horno", ids["papel_horno"]
        ),
        "aves": _chain_category(connection, ids["chain"], "18", "Aves", ids["aves"]),
        "pasta": _chain_category(connection, ids["chain"], "19", "Pasta", ids["pasta"]),
        "pollo": _chain_category(connection, ids["chain"], "20", "Pollo", ids["pollo"]),
        "carne": _chain_category(connection, ids["chain"], "21", "Carne", ids["carne"]),
        "arroz_variedad": _chain_category(
            connection, ids["chain"], "22", "Arroz", ids["arroz_variedad"]
        ),
        "atun": _chain_category(connection, ids["chain"], "23", "Atún", ids["atun"]),
        "cerveza": _chain_category(connection, ids["chain"], "24", "Cerveza", ids["cerveza"]),
        "refresco_cola": _chain_category(
            connection, ids["chain"], "25", "Refresco de cola", ids["refresco_cola"]
        ),
    }
    yogur = _canonical(connection, ids["yogur"], "Yogur", "", "ud")
    products = {
        "leche": ("L1", "Leche semidesnatada Hacendado", "1", "l", 1, "0.95", "1.00"),
        "yogur": ("Y1", "Yogur natural Hacendado", "1", "ud", 4, "1.20", "1.30"),
        "fruta": ("F1", "Plátano de Canarias", "1", "kg", 1, "1.50", "1.60"),
        "queso": ("Q1", "Queso curado Hacendado", "0.5", "kg", 1, "5.00", "5.10"),
        "huevos": ("H1", "Huevos frescos Hacendado", "1", "ud", 12, "2.10", "2.20"),
    }
    for name, (sku, product_name, quantity, unit, pack, price_one, price_two) in products.items():
        canonical_name = "Leche semidesnatada" if name == "leche" else None
        variant = "semidesnatada" if name == "leche" else ""
        canonical_category = ids["platano"] if name == "fruta" else ids[name]
        keywords: dict[str, object] = {}
        if name == "yogur":
            keywords = {"canonical_id": yogur}
        _chain_product(
            connection,
            ids,
            categories[name],
            sku,
            product_name,
            quantity,
            unit,
            pack,
            price_one,
            price_two,
            canonical_category=canonical_category,
            canonical_name=canonical_name,
            variant_key=variant,
            image_url=(f"https://example.test/{sku.lower()}.jpg" if name == "leche" else None),
            **keywords,
        )
    # Another presentation of the same canonical product: "natural" is not a canonical
    # variant, so it only filters by name when the line says it.
    _chain_product(
        connection,
        ids,
        categories["yogur"],
        "Y2",
        "Yogur griego Hacendado",
        "1",
        "ud",
        4,
        "1.50",
        "1.60",
        canonical_id=yogur,
    )
    for sku, product_name, price_one, price_two in (
        ("P1", "Pan de pueblo", "2.00", "2.10"),
        ("S1", "Sartén antiadherente", "10.00", "11.00"),
    ):
        _chain_product(
            connection,
            ids,
            categories["panaderia"],
            sku,
            product_name,
            "1",
            "kg",
            1,
            price_one,
            price_two,
            canonical_category=ids["pan"],
            with_canonical=sku != "S1",
        )
    for sku, product_name, price_one, price_two in (
        ("R1", "Refresco Dia cola", "2.00", "2.10"),
        ("R2", "Refresco Diamante cola", "1.00", "1.10"),
        ("R3", "Refresco media naranja", "1.50", "1.60"),
    ):
        _chain_product(
            connection,
            ids,
            categories["refresco"],
            sku,
            product_name,
            "1",
            "ud",
            1,
            price_one,
            price_two,
            canonical_category=ids["refresco"],
        )
    # Two products of the same canonical product: exact lines buy one, equivalent lines may
    # take the cheaper one and report the savings.
    sin_lactosa = _canonical(connection, ids["leche"], "Leche sin lactosa", "sin_lactosa", "l")
    # Products for the catalog rules: a brand of the same leaf, a size of another dimension, an
    # alias and names that do or do not resemble the line.
    for category, sku, product_name, quantity, unit, price_one, price_two in (
        ("leche", "L2", "Leche entera Pascual", "1", "l", "1.10", "1.20"),
        ("leche", "L3", "Leche en polvo desnatada", "0.9", "kg", "10.80", "10.90"),
        ("refresco", "R4", "Coca Cola Zero", "1", "ud", "0.90", "1.00"),
        ("papel_horno", "PH1", "Papel de horno Bosque Verde", "1", "ud", "1.20", "1.30"),
        ("aves", "AV1", "Ala de pavo", "1", "kg", "3.00", "3.10"),
        ("aves", "AV2", "Muslo de pavo", "1", "kg", "2.50", "2.60"),
        ("leche", "L4", "Leche sin lactosa Hacendado", "1", "l", "1.05", "1.15"),
        ("pasta", "PA1", "Macarrón rayado integral Hacendado", "0.5", "kg", "1.00", "1.10"),
        ("pasta", "PA2", "Pasta tiburón Hacendado", "0.5", "kg", "0.80", "0.90"),
        (
            "pasta",
            "PA3",
            "Macarrón integral sin gluten Hacendado",
            "0.5",
            "kg",
            "1.30",
            "1.40",
        ),
        ("pollo", "PO1", "Muslo de pollo", "0.46", "kg", "4.00", "4.10"),
        ("pollo", "PO2", "Pollo entero", "0.63", "kg", "4.19", "4.29"),
        ("pollo", "PO3", "Alitas de pollo", "0.60", "kg", "4.80", "4.90"),
        (
            "pollo",
            "PO4",
            "Filetes pechuga de pollo marinadas empanadas sin gluten",
            "0.46",
            "kg",
            "4.00",
            "4.10",
        ),
        ("pollo", "PO5", "Pechugas enteras de pollo", "0.63", "kg", "4.19", "4.29"),
        ("carne", "CA1", "Preparado de carne picada cerdo", "0.5", "kg", "4.50", "4.60"),
        ("carne", "CA2", "Preparado de carne picada mixta", "0.5", "kg", "4.70", "4.80"),
        ("carne", "CA3", "Albóndigas de cerdo", "0.5", "kg", "4.55", "4.65"),
    ):
        keywords: dict[str, object] = {}
        if sku in ("L3",):
            keywords = {"canonical_name": "Leche en polvo", "variant_key": "desnatada"}
        elif sku == "L4":
            keywords = {"canonical_id": sin_lactosa}
        elif sku == "PA1":
            keywords = {"variant_key": "integral"}
        elif sku == "PA3":
            keywords = {"variant_key": "integral|sin_gluten"}
        elif sku in ("PH2", "PH3"):
            keywords = {"with_canonical": False}
        _chain_product(
            connection,
            ids,
            categories[category],
            sku,
            product_name,
            quantity,
            unit,
            1,
            price_one,
            price_two,
            canonical_category=ids[category],
            **keywords,
        )
    _chain_product(
        connection,
        ids,
        categories["leche"],
        "L5",
        "Leche sin lactosa Dia",
        "1",
        "l",
        1,
        "0.90",
        "0.95",
        canonical_id=sin_lactosa,
    )
    # Products of one canonical that a content word tells apart: the plain choice is the
    # cheaper one, and "arroz basmati" must still pick the basmati.
    arroz_variedad = _canonical(connection, ids["arroz_variedad"], "Arroz", "", "kg")
    for sku, product_name, price_one, price_two in (
        ("B1", "Arroz redondo Hacendado", "1.00", "1.10"),
        ("B2", "Arroz basmati Hacendado", "1.50", "1.60"),
    ):
        _chain_product(
            connection,
            ids,
            ids["arroz_variedad"],
            sku,
            product_name,
            "1",
            "kg",
            1,
            price_one,
            price_two,
            canonical_id=arroz_variedad,
            chain_category=categories["arroz_variedad"],
        )
    for sku, product_name, price_one, price_two in (
        ("PA4", "Espaguetis Hacendado", "1.20", "1.30"),
        ("PA5", "Estrellas de pasta Hacendado", "0.90", "1.00"),
    ):
        _chain_product(
            connection,
            ids,
            ids["pasta"],
            sku,
            product_name,
            "0.5",
            "kg",
            1,
            price_one,
            price_two,
            canonical_category=ids["pasta"],
            chain_category=categories["pasta"],
        )
    # A plain canonical of tinned tuna, next to two variants a line may ask for.
    atun = _canonical(connection, ids["atun"], "Atún", "", "ud")
    atun_natural = _canonical(connection, ids["atun"], "Atún al natural", "al_natural", "ud")
    atun_aceite = _canonical(
        connection, ids["atun"], "Atún en aceite de oliva", "en_aceite_oliva", "ud"
    )
    for sku, product_name, canonical_id, price_one, price_two in (
        ("AT1", "Atún en tomate Hacendado", atun, "1.00", "1.10"),
        ("AT2", "Atún al natural Hacendado", atun_natural, "2.00", "2.10"),
        ("AT3", "Atún en aceite de oliva Hacendado", atun_aceite, "2.50", "2.60"),
    ):
        _chain_product(
            connection,
            ids,
            ids["atun"],
            sku,
            product_name,
            "1",
            "ud",
            1,
            price_one,
            price_two,
            canonical_id=canonical_id,
            chain_category=categories["atun"],
        )
    # "sin alcohol" is a canonical variant a line must ask for; the plain beer wins by default.
    cerveza = _canonical(connection, ids["cerveza"], "Cerveza", "", "ud")
    cerveza_sin = _canonical(connection, ids["cerveza"], "Cerveza sin alcohol", "sin_alcohol", "ud")
    for sku, product_name, canonical_id, price_one, price_two in (
        ("CE1", "Cerveza normal Hacendado", cerveza, "1.00", "1.10"),
        ("CE2", "Cerveza sin alcohol Hacendado", cerveza_sin, "0.80", "0.90"),
    ):
        _chain_product(
            connection,
            ids,
            ids["cerveza"],
            sku,
            product_name,
            "1",
            "ud",
            1,
            price_one,
            price_two,
            canonical_id=canonical_id,
            chain_category=categories["cerveza"],
        )
    cola = _canonical(connection, ids["refresco_cola"], "Coca-Cola", "", "ud")
    cola_zero = _canonical(connection, ids["refresco_cola"], "Coca-Cola zero", "zero", "ud")
    for sku, product_name, canonical_id, price_one, price_two in (
        ("CO1", "Coca-Cola Hacendado", cola, "1.00", "1.10"),
        ("CO2", "Coca-Cola Zero Hacendado", cola_zero, "0.80", "0.90"),
    ):
        _chain_product(
            connection,
            ids,
            ids["refresco_cola"],
            sku,
            product_name,
            "1",
            "ud",
            1,
            price_one,
            price_two,
            canonical_id=canonical_id,
            chain_category=categories["refresco_cola"],
        )
    # A flavour is never plain: "yogur" keeps the natural one even if fresa is cheaper.
    yogur_fresa = _canonical(connection, ids["yogur"], "Yogur sabor fresa", "sabor:fresa", "ud")
    _chain_product(
        connection,
        ids,
        ids["yogur"],
        "Y3",
        "Yogur sabor fresa Hacendado",
        "1",
        "ud",
        4,
        "0.90",
        "1.00",
        canonical_id=yogur_fresa,
        chain_category=categories["yogur"],
    )
    # A second chain with one product, so the chain filter has somewhere else to buy.
    arroz = _canonical(connection, ids["arroz"], "Arroz redondo", "", "kg")
    carrefour_arroz = _chain_category(connection, ids["chain2"], "30", "Arroz", ids["arroz"])
    _chain_product(
        connection,
        ids,
        ids["arroz"],
        "C1",
        "Arroz redondo Carrefour",
        "1",
        "kg",
        1,
        "1.30",
        "1.40",
        chain=ids["chain2"],
        chain_category=carrefour_arroz,
        canonical_id=arroz,
        zones=(ids["z3"],),
    )

    _store(connection, ids["chain"], ids["z1"], "Mercadona", STORE_ONE, "Calle Ancha 1, León")
    _store(
        connection,
        ids["chain"],
        ids["z2"],
        "Mercadona Centro",
        STORE_TWO,
        "Avenida de Astorga 5, León",
    )
    _store(connection, ids["chain2"], ids["z3"], "Carrefour", (42.618, -5.555), "Calle Sur 9, León")
    return ids


def _brand(
    connection: Connection,
    chain_id: int,
    name: str,
    *,
    private_label: bool = False,
    aliases: tuple[str, ...] = (),
) -> int:
    return scalar(
        connection,
        "insert into brand (name, is_private_label, owner_chain_id, aliases) "
        "values (:name, :private_label, :owner, :aliases) returning id",
        name=name,
        private_label=private_label,
        owner=chain_id if private_label else None,
        aliases=list(aliases),
    )


def _canonical(
    connection: Connection,
    category_id: int,
    name: str,
    variant_key: str,
    base_unit: str,
) -> int:
    return scalar(
        connection,
        "insert into canonical_product (category_id, name, variant_key, base_unit) "
        "values (:category, :name, :variant, :unit) returning id",
        category=category_id,
        name=name,
        variant=variant_key,
        unit=base_unit,
    )


def _chain_product(
    connection: Connection,
    ids: dict[str, int],
    category_id: int,
    sku: str,
    name: str,
    quantity: str,
    unit: str,
    pack: int,
    price_one: str,
    price_two: str,
    *,
    canonical_id: int | None = None,
    canonical_category: int | None = None,
    canonical_name: str | None = None,
    variant_key: str = "",
    with_canonical: bool = True,
    image_url: str | None = None,
    chain: int | None = None,
    chain_category: int | None = None,
    zones: tuple[int, ...] | None = None,
) -> int:
    if canonical_id is None and with_canonical:
        canonical_id = _canonical(
            connection,
            canonical_category if canonical_category is not None else category_id,
            canonical_name or name,
            variant_key,
            unit,
        )
    product_id = scalar(
        connection,
        "insert into chain_product (chain_id, chain_sku, name, base_quantity, base_unit, "
        "pack_count, chain_category_id, canonical_id, match_method, match_confidence, image_url) "
        "values (:chain, :sku, :name, :quantity, :unit, :pack, :category, :canonical, "
        ":method, :confidence, :image) returning id",
        chain=chain or ids["chain"],
        sku=sku,
        name=name,
        quantity=Decimal(quantity),
        unit=unit,
        pack=pack,
        category=chain_category if chain_category is not None else category_id,
        canonical=canonical_id,
        method="rule" if canonical_id is not None else None,
        confidence=1.0 if canonical_id is not None else None,
        image=image_url,
    )
    prices = (
        [
            (ids["z1"], Decimal(price_one), SEEN_ZONE_ONE),
            (ids["z2"], Decimal(price_two), SEEN_ZONE_TWO),
        ]
        if zones is None
        else [(zones[0], Decimal(price_one), SEEN_ZONE_ONE)]
    )
    for zone_id, price, seen in prices:
        _price(connection, product_id, zone_id, price, seen)
    return product_id


def _zone(connection: Connection, chain_id: int, code: str, name: str) -> int:
    return scalar(
        connection,
        "insert into zone (chain_id, kind, code, name) "
        "values (:chain, 'postal_code', :code, :name) returning id",
        chain=chain_id,
        code=code,
        name=name,
    )


def _category(
    connection: Connection,
    key: str,
    name: str,
    level: int,
    parent_id: int | None = None,
    base_unit: str | None = None,
    *,
    is_vague: bool = False,
) -> int:
    return scalar(
        connection,
        "insert into category (key, name, level, parent_id, base_unit, is_vague) "
        "values (:key, :name, :level, :parent, :unit, :vague) returning id",
        key=key,
        name=name,
        level=level,
        parent=parent_id,
        unit=base_unit,
        vague=is_vague,
    )


def _closure(connection: Connection, ancestor: int, descendant: int, depth: int) -> None:
    connection.execute(
        text(
            "insert into category_closure (ancestor_id, descendant_id, depth) "
            "values (:ancestor, :descendant, :depth)"
        ),
        {"ancestor": ancestor, "descendant": descendant, "depth": depth},
    )


def _chain_category(
    connection: Connection, chain_id: int, code: str, name: str, category_id: int
) -> int:
    return scalar(
        connection,
        "insert into chain_category (chain_id, code, name, category_id) "
        "values (:chain, :code, :name, :category) returning id",
        chain=chain_id,
        code=code,
        name=name,
        category=category_id,
    )


def _price(
    connection: Connection,
    product_id: int,
    zone_id: int,
    price: Decimal,
    seen: datetime,
) -> None:
    connection.execute(
        text(
            "insert into chain_product_zone (chain_product_id, zone_id, is_available) "
            "values (:product, :zone, true)"
        ),
        {"product": product_id, "zone": zone_id},
    )
    connection.execute(
        text(
            "insert into price_current (chain_product_id, zone_id, price, valid_from, "
            "last_seen_at) values (:product, :zone, :price, '2026-11-13 05:00:00+00', :seen)"
        ),
        {"product": product_id, "zone": zone_id, "price": price, "seen": seen},
    )


def _store(
    connection: Connection,
    chain_id: int,
    zone_id: int,
    name: str,
    point: tuple[float, float],
    address: str | None = None,
) -> int:
    lat, lon = point
    return scalar(
        connection,
        "insert into store (chain_id, zone_id, name, address, geom) "
        "values (:chain, :zone, :name, :address, "
        "st_setsrid(st_makepoint(:lon, :lat), 4326)::geography) returning id",
        chain=chain_id,
        zone=zone_id,
        name=name,
        address=address,
        lon=lon,
        lat=lat,
    )
