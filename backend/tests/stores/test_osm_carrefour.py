"""Carrefour and other chain-named convenience stores in OSM (finding A7)."""

import pytest

from smart_basket.stores import BoundingBox, chain_for_tags, parse_elements, store_format


def _node(osm_id: int, tags: dict[str, str]) -> dict:
    return {"type": "node", "id": osm_id, "lat": 42.587, "lon": -5.56, "tags": tags}


@pytest.mark.parametrize(
    "tags",
    [
        {"name": "Carrefour León"},
        {"name": "Hipermercado Carrefour"},
        {"name": "Carrefour Express León"},
        {"name": "Carrefour Market León"},
        {"brand": "Carrefour", "name": "Cualquier cosa"},
        {"operator": "Carrefour"},
    ],
)
def test_carrefour_spellings_resolve_to_the_chain(tags):
    assert chain_for_tags(tags) == "carrefour"


@pytest.mark.parametrize(
    ("name", "chain"),
    [
        ("Supermercados Alimerka", "alimerka"),
        ("Lidl León", "lidl"),
        ("Mercadona León", "mercadona"),
    ],
)
def test_leading_chain_names_resolve(name, chain):
    assert chain_for_tags({"name": name}) == chain


@pytest.mark.parametrize("name", ["Restaurante Carrefour", "Parking Mercadona", "Bar Dia"])
def test_a_chain_in_the_middle_of_a_name_does_not_count(name):
    assert chain_for_tags({"name": name}) is None


def test_a_hypermarket_named_carrefour_leon_is_a_store():
    (store,) = parse_elements([_node(1, {"shop": "supermarket", "name": "Carrefour León"})])

    assert store.chain_code == "carrefour"
    assert store.name == "Carrefour León"


def test_a_carrefour_express_mapped_as_convenience_is_a_store():
    (store,) = parse_elements([_node(2, {"shop": "convenience", "name": "Carrefour Express León"})])

    assert store.chain_code == "carrefour"
    assert store.format == "Express"


def test_a_carrefour_market_is_a_store():
    (store,) = parse_elements([_node(3, {"shop": "supermarket", "name": "Carrefour Market León"})])

    assert store.chain_code == "carrefour"
    assert store_format({"name": "Carrefour Market León", "shop": "supermarket"}) == "Market"


def test_a_carrefour_hypermarket_inside_a_mall_is_a_store():
    (store,) = parse_elements([_node(4, {"shop": "mall", "name": "Hipermercado Carrefour"})])

    assert store.chain_code == "carrefour"


def test_a_carrefour_petrol_station_is_rejected():
    assert parse_elements([_node(5, {"amenity": "fuel", "brand": "Carrefour"})]) == ()
    assert (
        parse_elements([_node(6, {"amenity": "fuel", "shop": "convenience", "brand": "Carrefour"})])
        == ()
    )


def test_a_generic_convenience_store_is_rejected():
    assert parse_elements([_node(7, {"shop": "convenience", "name": "Bazar Chino"})]) == ()
    assert parse_elements([_node(8, {"shop": "convenience"})]) == ()


def test_the_query_asks_for_chain_named_convenience_stores_and_malls():
    query = BoundingBox.parse("42.56,-5.62,42.63,-5.52").query()

    assert "convenience" in query
    assert "mall" in query
    assert "carrefour" in query
