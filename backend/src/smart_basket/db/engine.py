"""SQLAlchemy engine and session helpers (SQLAlchemy Core and ORM sessions over psycopg 3)."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from smart_basket.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    """Process-wide engine. `pool_pre_ping` survives database restarts."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=5)


@lru_cache
def _session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    session = _session_factory(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session per request."""
    with session_scope() as session:
        yield session


def check_database(engine: Engine | None = None) -> bool:
    """True if the database answers a trivial query."""
    try:
        with (engine or get_engine()).connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
