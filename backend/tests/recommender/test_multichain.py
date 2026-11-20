"""Multi-chain Mercadona + Dia integration tests against a synthetic catalog (database tests).

Nothing here is collected data (NFR-07): chains, stores, canonical products and prices exist only
in the test database and are rolled back after each test.
"""

# ruff: noqa: F811

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from smart_basket.agent.core import PolicyDecision, ScriptedPolicy
from smart_basket.api.agent import get_agent_policy
from smart_basket.api.app import create_app
from smart_basket.api.recommendations import get_routing_engine, get_today
from smart_basket.db import get_session

from .conftest import (
    ORIGIN,
    SEEN_ZONE_ONE,
    STORE_ONE,
    STORE_TWO,
    FakeRouting,
    World,
    _canonical,
    _category,
    _chain_category,
    _closure,
    _price,
    _store,
    _zone,
    engine,  # noqa: F401
    scalar,
)

pytestmark = pytest.mark.db


def _insert_chain_product(
    connection: Connection,
    *,
    chain_id: int,
    zone_id: int,
    chain_category_id: int,
    canonical_id: int,
    sku: str,
    name: str,
    quantity: str,
    unit: str,
    pack_count: int,
    price: str,
) -> int:
    product_id = scalar(
        connection,
        "insert into chain_product (chain_id, chain_sku, name, base_quantity, base_unit, "
        "pack_count, chain_category_id, canonical_id, match_method, match_confidence) "
        "values (:chain, :sku, :name, :quantity, :unit, :pack, :category, :canonical, "
        "'rule', 1.0) returning id",
        chain=chain_id,
        sku=sku,
        name=name,
        quantity=Decimal(quantity),
        unit=unit,
        pack=pack_count,
        category=chain_category_id,
        canonical=canonical_id,
    )
    _price(connection, product_id, zone_id, Decimal(price), SEEN_ZONE_ONE)
    return product_id


def _seed_multichain(connection: Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    ids["mercadona"] = scalar(
        connection, "insert into chain (code, name) values ('mercadona', 'Mercadona') returning id"
    )
    ids["dia"] = scalar(
        connection, "insert into chain (code, name) values ('dia', 'Dia') returning id"
    )
    ids["z_merc"] = _zone(connection, ids["mercadona"], "24001", "León")
    ids["z_dia"] = _zone(connection, ids["dia"], "24002", "León")

    ids["store_merc"] = _store(
        connection, ids["mercadona"], ids["z_merc"], "Mercadona León", STORE_ONE, "Calle Ancha 1"
    )
    ids["store_dia"] = _store(
        connection, ids["dia"], ids["z_dia"], "Dia León", STORE_TWO, "Avenida Ordoño II 10"
    )

    specs = [
        ("leche", "Leche", "l", "Leche semidesnatada", "1", "l", 1, "0.90", "1.90"),
        ("pasta", "Pasta", "kg", "Espaguetis", "1", "kg", 1, "1.00", "2.00"),
        ("huevos", "Huevos", "ud", "Huevos L", "1", "ud", 12, "3.00", "2.00"),
        ("aceite", "Aceite de oliva", "l", "Aceite de oliva virgen", "1", "l", 1, "6.00", "5.00"),
    ]
    for key, cat_name, base_unit, prod_name, qty, unit, pack, price_merc, price_dia in specs:
        cat_id = _category(connection, key, cat_name, 1, base_unit=base_unit)
        _closure(connection, cat_id, cat_id, 0)
        cc_merc = _chain_category(connection, ids["mercadona"], f"m-{key}", cat_name, cat_id)
        cc_dia = _chain_category(connection, ids["dia"], f"d-{key}", cat_name, cat_id)
        canon_id = _canonical(connection, cat_id, prod_name, "", base_unit)

        _insert_chain_product(
            connection,
            chain_id=ids["mercadona"],
            zone_id=ids["z_merc"],
            chain_category_id=cc_merc,
            canonical_id=canon_id,
            sku=f"M-{key}",
            name=f"{prod_name} Hacendado",
            quantity=qty,
            unit=unit,
            pack_count=pack,
            price=price_merc,
        )
        _insert_chain_product(
            connection,
            chain_id=ids["dia"],
            zone_id=ids["z_dia"],
            chain_category_id=cc_dia,
            canonical_id=canon_id,
            sku=f"D-{key}",
            name=f"{prod_name} Dia",
            quantity=qty,
            unit=unit,
            pack_count=pack,
            price=price_dia,
        )

    return ids


@pytest.fixture
def multichain_world(engine) -> Iterator[World]:
    """Synthetic two-chain world (Mercadona + Dia in León) rolled back after each test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        ids = _seed_multichain(connection)
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


def _basket() -> list[dict]:
    return [
        {
            "text": "leche",
            "category_key": "leche",
            "quantity": "1",
            "unit": "l",
            "brand": None,
            "private_label_ok": True,
        },
        {
            "text": "pasta",
            "category_key": "pasta",
            "quantity": "1",
            "unit": "kg",
            "brand": None,
            "private_label_ok": True,
        },
        {
            "text": "huevos",
            "category_key": "huevos",
            "quantity": "12",
            "unit": "ud",
            "brand": None,
            "private_label_ok": True,
        },
        {
            "text": "aceite de oliva",
            "category_key": "aceite",
            "quantity": "1",
            "unit": "l",
            "brand": None,
            "private_label_ok": True,
        },
    ]


def _payload(**overrides) -> dict:
    body = {
        "items": _basket(),
        "origin": {"lat": ORIGIN.latitude, "lon": ORIGIN.longitude},
        "mode": "walk",
        "max_stores": 2,
        "priority_mode": "savings",
        "return_to_origin": True,
        "degraded": False,
    }
    body.update(overrides)
    return body


def test_multichain_splits_in_savings_and_stays_single_in_time(multichain_world: World) -> None:
    savings_resp = multichain_world.client.post(
        "/api/recommendations", json=_payload(priority_mode="savings")
    )
    assert savings_resp.status_code == 200
    savings = savings_resp.json()
    assert savings["total_cost"] == "8.90"
    assert [store["chain"] for store in savings["stores"]] == ["Mercadona", "Dia"]

    time_resp = multichain_world.client.post(
        "/api/recommendations", json=_payload(priority_mode="time")
    )
    assert time_resp.status_code == 200
    time_body = time_resp.json()
    assert time_body["total_cost"] == "10.90"
    assert [store["chain"] for store in time_body["stores"]] == ["Mercadona"]


def test_multichain_chain_filter_restricts_to_dia_or_mercadona(multichain_world: World) -> None:
    dia_resp = multichain_world.client.post("/api/recommendations", json=_payload(chains=["dia"]))
    assert dia_resp.status_code == 200
    dia_body = dia_resp.json()
    assert dia_body["total_cost"] == "10.90"
    assert [store["chain"] for store in dia_body["stores"]] == ["Dia"]

    merc_resp = multichain_world.client.post(
        "/api/recommendations", json=_payload(chains=["mercadona"])
    )
    assert merc_resp.status_code == 200
    merc_body = merc_resp.json()
    assert merc_body["total_cost"] == "10.90"
    assert [store["chain"] for store in merc_body["stores"]] == ["Mercadona"]


def test_multichain_agent_exclude_chain_switches_from_both_to_mercadona(
    multichain_world: World,
) -> None:
    scripted = ScriptedPolicy(
        [
            PolicyDecision(
                action_key="excluir_cadena:0",
                confidence=0.95,
                probabilities={"excluir_cadena:0": 0.95, "no_hacer_nada": 0.05},
                model_name="scripted-model",
            )
        ]
    )
    multichain_world.client.app.dependency_overrides[get_agent_policy] = lambda: scripted

    resp = multichain_world.client.post(
        "/api/agent/runs",
        json={
            "request": _payload(priority_mode="savings"),
            "shopper_message": "no quiero ir al Dia",
        },
    )
    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "completed"
    assert run["excluded_chains"] == ["dia"]
    assert run["recommendation"] is not None
    assert run["recommendation"]["total_cost"] == "10.90"
    assert [store["chain"] for store in run["recommendation"]["stores"]] == ["Mercadona"]
