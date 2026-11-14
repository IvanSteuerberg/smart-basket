"""Synthetic catalog of the classifier tests: a three-level taxonomy and one chain.

Nothing here is collected data: every row lives in the test database inside a transaction that
is rolled back after each test. The shape mirrors the seed taxonomy (section, group, leaf) and
the products cover the rules of the task: a name in a group section, a variant, a flavour, a
section that mixes products, an outside leaf, a group with no named leaf and a tie.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session

from smart_basket.db.migrate import alembic_config

URL = os.environ.get("TEST_DATABASE_URL")

#: key, name, level, parent key, base unit, vague, forms.
CATEGORIES = (
    ("frescos", "Frescos", 1, None, None, False, ()),
    ("fruta", "Fruta", 2, "frescos", None, True, ("fruta",)),
    ("platano", "Plátano", 3, "fruta", "kg", False, ("plátano", "banana")),
    ("manzana", "Manzana", 3, "fruta", "kg", False, ("manzana",)),
    ("uva", "Uva", 3, "fruta", "kg", False, ("uva",)),
    ("lacteos", "Lácteos", 2, "frescos", None, True, ("lácteos",)),
    (
        "leche",
        "Leche",
        3,
        "lacteos",
        "l",
        False,
        ("leche", "leche entera", "leche semidesnatada", "leche sin lactosa"),
    ),
    ("leche_condensada", "Leche condensada", 3, "lacteos", "l", False, ("leche condensada",)),
    ("yogur", "Yogur", 3, "lacteos", "ud", False, ("yogur", "yogur natural")),
    ("petit_suisse", "Petit suisse", 3, "lacteos", "kg", False, ("petit suisse", "petit")),
    ("queso", "Queso", 3, "lacteos", "kg", False, ("queso",)),
    ("carnes", "Carnes", 2, "frescos", None, True, ("carne",)),
    ("pollo", "Pollo", 3, "carnes", "kg", False, ("pollo", "pechuga de pollo", "alitas")),
    ("pavo", "Pavo", 3, "carnes", "kg", False, ("pavo", "muslo de pavo")),
    ("despensa", "Despensa", 1, None, None, False, ()),
    ("dulces", "Dulces", 2, "despensa", None, True, ()),
    ("galletas", "Galletas", 3, "dulces", "kg", False, ("galletas", "galletas maria")),
)

#: code, name, parent code, taxonomy key.
CHAIN_CATEGORIES = (
    ("1", "Lácteos", None, "lacteos"),
    ("2", "Fruta", None, "fruta"),
    ("3", "Pollo", None, "pollo"),
    ("4", "Queso", None, "queso"),
    ("5", "Plátano", None, "platano"),
)

#: sku, name, chain category code.
PRODUCTS = (
    ("M1", "Plátano de Canarias IGP", "2"),
    ("M2", "Leche sin lactosa Hacendado", "1"),
    ("M3", "Petit sabor fresa Hacendado", "1"),
    ("M4", "Fruta de temporada", "5"),
    ("M5", "Galletas María", "4"),
    ("M6", "Muslo de pavo Hacendado", "3"),
    ("M7", "Algo raro", "2"),
    ("M8", "Manzana y plátano", "2"),
    ("M9", "Leche condensada Hacendado", "1"),
)


@dataclass
class Catalog:
    """The session of a test plus the ids of the synthetic rows."""

    session: Session
    products: dict[str, int]
    categories: dict[str, int]


@pytest.fixture(scope="module")
def engine():
    if not URL:
        pytest.skip("TEST_DATABASE_URL not set")
    command.upgrade(alembic_config(URL), "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def catalog(engine) -> Iterator[Catalog]:
    with engine.connect() as connection:
        transaction = connection.begin()
        ids = _seed(connection)
        session = Session(bind=connection)
        yield Catalog(session, ids["products"], ids["categories"])
        session.close()
        transaction.rollback()


def _scalar(connection: Connection, sql: str, **params):
    return connection.execute(text(sql), params).scalar_one()


def _seed(connection: Connection) -> dict[str, dict[str, int]]:
    connection.execute(
        text(
            "truncate chain, category, brand, chain_product, canonical_product, match_review, "
            "product_match restart identity cascade"
        )
    )
    chain_id = _scalar(
        connection, "insert into chain (code, name) values ('mercadona', 'Mercadona') returning id"
    )
    connection.execute(
        text(
            "insert into brand (name, is_private_label, owner_chain_id) "
            "values ('Hacendado', true, :chain)"
        ),
        {"chain": chain_id},
    )

    categories: dict[str, int] = {}
    for key, name, level, parent, unit, vague, forms in CATEGORIES:
        categories[key] = _scalar(
            connection,
            "insert into category (key, name, level, parent_id, base_unit, is_vague, forms) "
            "values (:key, :name, :level, :parent, :unit, :vague, :forms) returning id",
            key=key,
            name=name,
            level=level,
            parent=categories.get(parent) if parent else None,
            unit=unit,
            vague=vague,
            forms=list(forms),
        )
    parents = {row[0]: row[3] for row in CATEGORIES}
    for key in categories:
        depth = 0
        node = key
        while node is not None:
            connection.execute(
                text(
                    "insert into category_closure (ancestor_id, descendant_id, depth) "
                    "values (:ancestor, :descendant, :depth)"
                ),
                {
                    "ancestor": categories[node],
                    "descendant": categories[key],
                    "depth": depth,
                },
            )
            node = parents[node]
            depth += 1

    chain_categories = {
        code: _scalar(
            connection,
            "insert into chain_category (chain_id, code, name, parent_code, category_id) "
            "values (:chain, :code, :name, :parent, :category) returning id",
            chain=chain_id,
            code=code,
            name=name,
            parent=parent,
            category=categories[key],
        )
        for code, name, parent, key in CHAIN_CATEGORIES
    }

    products = {
        sku: _scalar(
            connection,
            "insert into chain_product (chain_id, chain_sku, name, chain_category_id) "
            "values (:chain, :sku, :name, :category) returning id",
            chain=chain_id,
            sku=sku,
            name=name,
            category=chain_categories[code],
        )
        for sku, name, code in PRODUCTS
    }
    return {"products": products, "categories": categories}
