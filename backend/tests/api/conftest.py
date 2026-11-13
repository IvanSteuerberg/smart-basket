"""Shared fixtures of the API tests: a TestClient over the real packaged seed."""

import os
from collections.abc import Callable, Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smart_basket.api.app import create_app
from smart_basket.api.lexicon_cache import default_cache
from smart_basket.db.engine import get_session
from smart_basket.db.migrate import alembic_config
from smart_basket.seed import DEFAULT_DATA_DIR
from smart_basket.seed.loader import load_seed

URL = os.environ.get("TEST_DATABASE_URL")


class FakeClock:
    """A monotonic clock that only moves when asked; `sleep` advances it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    command.upgrade(alembic_config(URL), "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        session.execute(text("truncate chain, category, brand restart identity cascade"))
        load_seed(session, DEFAULT_DATA_DIR)
        session.commit()
        yield session


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    default_cache.reset()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def add_product(session: Session) -> Callable[..., int]:
    """Insert a synthetic chain product (and its zone availability) in a seeded category."""

    def add(category_key: str, *, sku: str, active: bool = True, available: bool = True) -> int:
        product_id = session.execute(
            text(
                "insert into chain_product"
                " (chain_id, chain_sku, name, chain_category_id, is_active)"
                " select cc.chain_id, :sku, :name, cc.id, :active"
                " from chain_category cc"
                " join category c on c.id = cc.category_id"
                " where c.key = :key"
                " order by cc.id"
                " limit 1"
                " returning id"
            ),
            {"sku": sku, "name": f"Producto {sku}", "active": active, "key": category_key},
        ).scalar_one()
        session.execute(
            text(
                "insert into chain_product_zone (chain_product_id, zone_id, is_available)"
                " select :product, z.id, :available"
                " from zone z join chain c on c.id = z.chain_id"
                " where c.code = 'mercadona'"
                " order by z.id"
                " limit 1"
            ),
            {"product": product_id, "available": available},
        )
        return product_id

    return add
