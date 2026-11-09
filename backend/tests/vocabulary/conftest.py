"""Database fixtures for the vocabulary tests, same setup as `tests/seed/test_loader.py`."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smart_basket.db.migrate import alembic_config
from smart_basket.preprocessor import InMemoryLexicon, Preprocessor
from smart_basket.seed.__main__ import DEFAULT_DATA_DIR
from smart_basket.seed.loader import load_seed
from smart_basket.vocabulary import build_lexicon

URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def engine():
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
def lexicon(session: Session) -> InMemoryLexicon:
    return build_lexicon(session)


@pytest.fixture
def pp(lexicon: InMemoryLexicon) -> Preprocessor:
    return Preprocessor(lexicon)
