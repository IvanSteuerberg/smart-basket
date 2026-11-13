"""Catalog tree, search and the process-wide preprocessor over the real seed."""

import os

import pytest
from sqlalchemy import text

from smart_basket.api.lexicon_cache import LexiconCache
from tests.api.conftest import FakeClock

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


def node(nodes: list[dict], key: str) -> dict | None:
    for item in nodes:
        if item["key"] == key:
            return item
        found = node(item.get("children", []), key)
        if found is not None:
            return found
    return None


def test_categories_are_sections_groups_and_leaves(client):
    sections = client.get("/api/categories").json()["sections"]
    assert node(sections, "panaderia") is not None
    assert node(sections, "yogures") is not None

    section = node(sections, "panaderia")
    assert set(section) == {"key", "name", "children"}
    group = node(section["children"], "pan")
    assert set(group) == {"key", "name", "vague", "products", "children"}
    assert group["vague"] is True
    leaf = node(group["children"], "pan_molde")
    assert set(leaf) == {"key", "name", "base_unit", "products"}
    assert leaf["base_unit"] == "kg"
    assert leaf["products"] == 0


def test_stale_categories_are_left_out(client, session):
    session.execute(
        text(
            "insert into category (key, name, level) values ('vieja', 'Vieja (obsoleta vieja)', 1)"
        )
    )
    session.flush()
    sections = client.get("/api/categories").json()["sections"]
    assert node(sections, "vieja") is None


def test_a_stale_parent_does_not_break_its_children(client, session):
    parent_id = session.execute(
        text(
            "insert into category (key, name, level)"
            " values ('vieja', 'Vieja (obsoleta vieja)', 1) returning id"
        )
    ).scalar_one()
    session.execute(
        text(
            "insert into category (key, name, level, parent_id)"
            " values ('hija', 'Hija de la vieja', 2, :parent)"
        ),
        {"parent": parent_id},
    )
    session.flush()

    response = client.get("/api/categories")
    assert response.status_code == 200
    assert node(response.json()["sections"], "hija") is None

    results = client.get("/api/search", params={"q": "hija"}).json()["results"]
    assert results[0]["key"] == "hija"
    assert results[0]["path"] == ""


def test_products_count_availability_of_the_category_and_its_descendants(client, add_product):
    add_product("pan_molde", sku="pan-1")
    add_product("pan_molde", sku="pan-2")
    add_product("pan_molde", sku="pan-3", available=False)
    add_product("pan_molde", sku="pan-4", active=False)
    add_product("yogur_natural", sku="yogur-1")

    sections = client.get("/api/categories").json()["sections"]
    leaf = node(sections, "pan_molde")
    group = node(sections, "pan")
    assert leaf["products"] == 2
    assert group["products"] == 2
    assert node(sections, "yogur_natural")["products"] == 1


def test_search_finds_the_most_specific_category_first(client):
    results = client.get("/api/search", params={"q": "pan de molde"}).json()["results"]
    assert results[0]["key"] == "pan_molde"
    assert results[0]["kind"] == "leaf"
    assert results[0]["path"] == "Panadería y pastelería › Pan"
    assert len(results) <= 10


def test_search_finds_the_yogurt_group(client):
    results = client.get("/api/search", params={"q": "yogurt"}).json()["results"]
    group = next(result for result in results if result["key"] == "yogures")
    assert group["kind"] == "group"
    assert group["path"] == "Lácteos y huevos"


def test_search_ignores_accents_and_typos(client):
    results = client.get("/api/search", params={"q": "platano"}).json()["results"]
    assert results[0]["key"] == "platano"
    results = client.get("/api/search", params={"q": "yogurt natural"}).json()["results"]
    assert results[0]["key"] == "yogur_natural"


def test_search_ranks_exact_and_prefix_matches_first(client):
    results = client.get("/api/search", params={"q": "pan"}).json()["results"]
    keys = [result["key"] for result in results]
    assert keys[0] == "pan"
    assert keys.index("pan_molde") < keys.index("panales")


def test_search_needs_two_characters_once_stripped(client):
    for query in ("p", "", "   "):
        assert client.get("/api/search", params={"q": query}).status_code == 422


def test_preprocessor_is_reused_and_rebuilt_when_the_seed_changes(session):
    clock = FakeClock()
    cache = LexiconCache(check_interval=60.0, clock=clock)
    first = cache.preprocessor(session)
    assert cache.preprocessor(session) is first

    session.execute(text("insert into brand (name) values ('Marca de prueba')"))
    session.flush()
    clock.now += 30.0
    assert cache.preprocessor(session) is first

    clock.now += 31.0
    assert cache.preprocessor(session) is not first


def test_lexicon_is_rebuilt_when_a_category_is_renamed_or_its_forms_change(session):
    clock = FakeClock()
    cache = LexiconCache(check_interval=60.0, clock=clock)
    first = cache.preprocessor(session)
    forms = cache.search_forms(session)
    category_id = session.execute(
        text("select id from category where key = 'pan_molde'")
    ).scalar_one()
    assert forms[category_id][0] == "pan de molde"

    session.execute(
        text("update category set name = 'Pan de molde integral' where id = :id"),
        {"id": category_id},
    )
    session.flush()
    clock.now += 61.0
    assert cache.preprocessor(session) is not first
    assert cache.search_forms(session)[category_id][0] == "pan de molde integral"

    second = cache.preprocessor(session)
    session.execute(
        text("update category set forms = array['pan sandwich'] where id = :id"),
        {"id": category_id},
    )
    session.flush()
    clock.now += 61.0
    assert cache.preprocessor(session) is not second
    assert cache.search_forms(session)[category_id] == ("pan de molde integral", "pan sandwich")
