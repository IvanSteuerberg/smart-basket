"""Seed loading against a real PostgreSQL, same setup as `tests/db/test_migrations.py`.

Skipped unless TEST_DATABASE_URL points at a disposable database (CI sets it). Every test
starts from empty seed tables and uses the small synthetic fixtures.
"""

import json
import os
import shutil
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smart_basket.db.migrate import alembic_config
from smart_basket.seed.loader import load_seed

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


@pytest.fixture(scope="module")
def engine():
    command.upgrade(alembic_config(URL), "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        session.execute(text("truncate chain, category restart identity cascade"))
        session.commit()
        yield session


def load(session: Session, data_dir: Path):
    report = load_seed(session, data_dir)
    session.commit()
    return report


def copy_seed(seed_dir: Path, tmp_path: Path) -> Path:
    target = tmp_path / "seed"
    shutil.copytree(seed_dir, target)
    return target


def update_json(path: Path, update: Callable[[dict], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    update(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def closure_of(session: Session, key: str) -> list[tuple[str, int]]:
    rows = session.execute(
        text(
            "select ancestor.key, cc.depth from category_closure cc "
            "join category ancestor on ancestor.id = cc.ancestor_id "
            "join category descendant on descendant.id = cc.descendant_id "
            "where descendant.key = :key order by cc.depth"
        ),
        {"key": key},
    )
    return [(row[0], row[1]) for row in rows]


def count(session: Session, table: str) -> int:
    return session.execute(text(f"select count(*) from {table}")).scalar_one()


def test_load_twice_has_no_duplicates_and_correct_closure(session, seed_dir):
    first = load(session, seed_dir)
    assert (first.chain.inserted, first.chain.updated) == (2, 0)
    assert (first.zone.inserted, first.zone.updated) == (3, 0)
    assert (first.category.inserted, first.category.updated) == (6, 0)
    assert (first.chain_category.inserted, first.chain_category.updated) == (3, 0)
    assert first.category_closure.inserted == 12
    assert (first.brand.inserted, first.brand.updated) == (3, 0)

    second = load(session, seed_dir)
    assert (second.chain.inserted, second.chain.updated) == (0, 2)
    assert (second.zone.inserted, second.zone.updated) == (0, 3)
    assert (second.category.inserted, second.category.updated) == (0, 6)
    assert (second.chain_category.inserted, second.chain_category.updated) == (0, 3)
    assert second.category_closure.inserted == 12
    assert (second.brand.inserted, second.brand.updated) == (0, 3)

    for table, expected in [
        ("chain", 2),
        ("zone", 3),
        ("category", 6),
        ("chain_category", 3),
        ("category_closure", 12),
        ("brand", 3),
    ]:
        assert count(session, table) == expected, table
    assert closure_of(session, "yogur_griego") == [
        ("yogur_griego", 0),
        ("yogures", 1),
        ("lacteos_huevos", 2),
    ]
    assert closure_of(session, "agua") == [("agua", 0), ("bebidas", 1)]
    assert closure_of(session, "lacteos_huevos") == [("lacteos_huevos", 0)]


def test_optional_fields_and_defaults_are_stored(session, seed_dir):
    load(session, seed_dir)
    row = session.execute(
        text(
            "select level, base_unit, default_quantity, forms, is_vague "
            "from category where key = 'yogur_griego'"
        )
    ).one()
    assert row.level == 3
    assert row.base_unit == "kg"
    assert row.default_quantity == Decimal("0.5")
    assert row.forms == ["yogur griego", "griego"]
    assert row.is_vague is False

    natural = session.execute(
        text("select default_quantity, forms from category where key = 'yogur_natural'")
    ).one()
    assert natural.default_quantity is None
    assert natural.forms == ["yogur natural"]

    yogures = session.execute(
        text("select base_unit, forms, is_vague from category where key = 'yogures'")
    ).one()
    assert yogures.base_unit is None
    assert yogures.forms == ["yogur", "yogures"]
    assert yogures.is_vague is True


def test_mapping_change_on_the_second_load_updates_category_id(session, seed_dir, tmp_path):
    data_dir = copy_seed(seed_dir, tmp_path)
    load(session, data_dir)

    def remap(data: dict) -> None:
        for category in data["categories"]:
            if category["code"] == "1011":
                category["category"] = "yogur_natural"

    update_json(data_dir / "chain_categories" / "mercadona.json", remap)
    report = load(session, data_dir)
    assert (report.chain_category.inserted, report.chain_category.updated) == (0, 3)

    mapped = session.execute(
        text(
            "select c.key from chain_category cc join category c on c.id = cc.category_id "
            "where cc.code = '1011'"
        )
    ).scalar_one()
    assert mapped == "yogur_natural"


def test_category_removed_from_the_file_stays_and_is_reported_stale(session, seed_dir, tmp_path):
    data_dir = copy_seed(seed_dir, tmp_path)
    load(session, data_dir)

    update_json(
        data_dir / "taxonomy_es.json",
        lambda data: data.update(
            categories=[c for c in data["categories"] if c["key"] != "bebidas"]
        ),
    )
    report = load(session, data_dir)
    assert report.stale_categories == ["agua", "bebidas"]
    keys = set(session.execute(text("select key from category")).scalars())
    assert {"agua", "bebidas"} <= keys
    assert closure_of(session, "agua") == [("agua", 0), ("bebidas", 1)]


def test_renamed_key_with_same_name_and_parent_reloads(session, seed_dir, tmp_path):
    data_dir = copy_seed(seed_dir, tmp_path)
    load(session, data_dir)

    def rename(data: dict) -> None:
        for root in data["categories"]:
            for child in root.get("children", []):
                if child["key"] == "agua":
                    child["key"] = "agua_mineral"

    update_json(data_dir / "taxonomy_es.json", rename)
    report = load(session, data_dir)

    assert report.stale_categories == ["agua"]
    stale = session.execute(text("select name, forms from category where key = 'agua'")).one()
    assert stale.name == "Agua (obsoleta agua)"
    assert stale.forms == []
    forms = session.execute(
        text("select forms from category where key = 'agua_mineral'")
    ).scalar_one()
    assert forms == ["agua"]


def test_chain_wide_zone_exists_once_per_chain(session, seed_dir):
    load(session, seed_dir)
    load(session, seed_dir)
    rows = session.execute(
        text(
            "select c.code, z.code from zone z join chain c on c.id = z.chain_id "
            "where z.kind = 'chain' order by c.code"
        )
    ).all()
    assert rows == [("carrefour", "all"), ("mercadona", "all")]


def test_private_label_has_its_chain_and_manufacturer_has_none(session, seed_dir):
    load(session, seed_dir)
    private = session.execute(
        text(
            "select b.is_private_label, b.aliases, b.implies_category, b.match_name, c.code "
            "from brand b join chain c on c.id = b.owner_chain_id where b.name = 'Marca Blanca'"
        )
    ).one()
    assert private.is_private_label is True
    assert private.code == "mercadona"
    assert private.aliases == ["blanca"]
    assert private.implies_category is None
    assert private.match_name is False

    manufacturer = session.execute(
        text(
            "select is_private_label, owner_chain_id, aliases, implies_category, match_name "
            "from brand where name = 'Coca-Cola'"
        )
    ).one()
    assert manufacturer.is_private_label is False
    assert manufacturer.owner_chain_id is None
    assert manufacturer.aliases == ["coca cola", "cocacola"]
    assert manufacturer.implies_category == "yogur_natural"
    assert manufacturer.match_name is True


def test_brand_removed_from_the_file_stays_and_is_reported_stale(session, seed_dir, tmp_path):
    data_dir = copy_seed(seed_dir, tmp_path)
    load(session, data_dir)

    update_json(
        data_dir / "brands_es.json",
        lambda data: data.update(brands=[b for b in data["brands"] if b["name"] != "Otra Marca"]),
    )
    report = load(session, data_dir)
    assert report.stale_brands == ["Otra Marca"]
    names = set(session.execute(text("select name from brand")).scalars())
    assert "Otra Marca" in names
