"""Overpass parsing and the tag-to-chain mapping, with synthetic elements and a fake transport."""

import httpx
import pytest

from smart_basket.stores import (
    BoundingBox,
    OverpassClient,
    OverpassError,
    StoreObservation,
    build_address,
    chain_for_tags,
    fetch_stores,
    parse_elements,
    store_format,
)

BBOX = BoundingBox.parse("42.56,-5.62,42.63,-5.52")

MERCADONA = {
    "type": "node",
    "id": 1,
    "lat": 42.6,
    "lon": -5.57,
    "tags": {
        "shop": "supermarket",
        "brand": "Mercadona",
        "name": "Mercadona",
        "opening_hours": "Mo-Sa 09:00-21:00",
    },
}


def make_client(handler) -> OverpassClient:
    return OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), url="https://overpass.test/api"
    )


@pytest.mark.parametrize(
    ("tags", "code"),
    [
        ({"brand": "Mercadona"}, "mercadona"),
        ({"name": "MERCADONA"}, "mercadona"),
        ({"brand": "Dia"}, "dia"),
        ({"brand": "DIA"}, "dia"),
        ({"brand": "Dia&Go"}, "dia"),
        ({"brand": "Dia Maxi"}, "dia"),
        ({"brand": "Maxi Dia"}, "dia"),
        ({"brand": "Dia Market"}, "dia"),
        ({"brand": "La Plaza de Día"}, "dia"),
        ({"brand": "Alimerka"}, "alimerka"),
        ({"brand": "Lidl"}, "lidl"),
        ({"brand": "Alcampo"}, "alcampo"),
        ({"brand": "Alcampo Supermercado"}, "alcampo"),
        ({"brand": "Mi Alcampo"}, "alcampo"),
        ({"brand": "E. Leclerc"}, "eleclerc"),
        ({"brand": "Leclerc"}, "eleclerc"),
        ({"brand": "Lupa"}, "lupa"),
        ({"brand": "Carrefour"}, "carrefour"),
        ({"brand": "Carrefour Express"}, "carrefour"),
        ({"brand": "Carrefour Market"}, "carrefour"),
        ({"brand": "Gadis"}, "gadis"),
        ({"name": "Claudio"}, "gadis"),
        ({"brand": "Aldi"}, "aldi"),
    ],
)
def test_known_brands_map_to_their_chain(tags, code):
    assert chain_for_tags(tags) == code


def test_unknown_brands_and_untagged_stores_are_ignored():
    assert chain_for_tags({"brand": "Eroski"}) is None
    assert chain_for_tags({"name": "Supermercado Centro"}) is None
    assert chain_for_tags({"name": "Supermercados Diamante"}) is None
    assert chain_for_tags({}) is None


def test_the_brand_wins_over_the_name():
    tags = {"brand": "Lidl", "name": "Mercadona"}
    assert chain_for_tags(tags) == "lidl"


def test_an_unknown_brand_falls_back_to_the_name():
    assert chain_for_tags({"brand": "Eroski", "name": "Lidl"}) == "lidl"


def test_address_is_built_from_the_osm_parts():
    tags = {
        "addr:street": "Calle Ancha",
        "addr:housenumber": "12",
        "addr:postcode": "24001",
        "addr:city": "León",
    }
    assert build_address(tags) == "Calle Ancha 12, 24001 León"


def test_address_keeps_the_parts_it_has():
    assert build_address({"addr:street": "Calle Ancha"}) == "Calle Ancha"
    assert build_address({"addr:postcode": "24001", "addr:city": "León"}) == "24001 León"
    assert build_address({}) is None


def test_the_brand_variant_names_the_format():
    assert store_format({"brand": "Carrefour Express", "shop": "supermarket"}) == "Express"
    assert store_format({"brand": "Carrefour Market", "shop": "supermarket"}) == "Market"
    assert store_format({"brand": "DIA&Go", "shop": "supermarket"}) == "Dia&Go"
    assert store_format({"brand": "Mercadona", "shop": "supermarket"}) == "supermarket"
    assert store_format({"brand": "Mercadona"}) is None


def test_a_node_becomes_an_observation():
    (observation,) = parse_elements([MERCADONA])

    assert observation == StoreObservation(
        osm_id="node/1",
        chain_code="mercadona",
        name="Mercadona",
        format="supermarket",
        address=None,
        lon=-5.57,
        lat=42.6,
        opening_hours="Mo-Sa 09:00-21:00",
    )


def test_a_hypermarket_keeps_its_shop_value_as_the_format():
    hypermarket = {
        "type": "node",
        "id": 6,
        "lat": 42.6,
        "lon": -5.57,
        "tags": {"shop": "hypermarket", "brand": "Carrefour"},
    }

    (observation,) = parse_elements([hypermarket])

    assert observation.chain_code == "carrefour"
    assert observation.format == "hypermarket"


def test_a_way_uses_the_centre_of_its_outline():
    way = {
        "type": "way",
        "id": 2,
        "center": {"lat": 42.6, "lon": -5.57},
        "tags": {"shop": "supermarket", "brand": "Lidl", "addr:street": "Calle Ancha"},
    }

    (observation,) = parse_elements([way])

    assert observation.osm_id == "way/2"
    assert (observation.lon, observation.lat) == (-5.57, 42.6)
    assert observation.address == "Calle Ancha"


def test_elements_without_a_position_or_of_other_brands_are_skipped():
    relation = {"type": "relation", "id": 3, "tags": {"shop": "supermarket", "brand": "Lidl"}}
    other = {
        "type": "node",
        "id": 4,
        "lat": 42.6,
        "lon": -5.57,
        "tags": {"shop": "supermarket", "brand": "Eroski"},
    }

    assert parse_elements([relation, other]) == ()


def test_the_chain_name_replaces_a_missing_osm_name():
    node = {
        "type": "node",
        "id": 5,
        "lat": 42.6,
        "lon": -5.57,
        "tags": {"shop": "supermarket", "brand": "E.Leclerc"},
    }

    assert parse_elements([node])[0].name == "E.Leclerc"


def test_the_bbox_parses():
    assert (BBOX.south, BBOX.west, BBOX.north, BBOX.east) == (42.56, -5.62, 42.63, -5.52)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("42.56,-5.62,42.63", "four numbers"),
        ("a,-5.62,42.63,-5.52", "four numbers"),
        ("42.63,-5.62,42.56,-5.52", "south < north"),
        ("", "four numbers"),
    ],
)
def test_a_malformed_bbox_is_rejected(value, message):
    with pytest.raises(ValueError, match=message):
        BoundingBox.parse(value)


def test_the_query_asks_for_supermarkets_and_hypermarkets_inside_the_bbox():
    query = BBOX.query()

    assert 'nwr["shop"~"^(supermarket|hypermarket)$"](42.56,-5.62,42.63,-5.52)' in query
    assert query.endswith("out center tags;")


def test_the_client_posts_the_query_identifying_itself():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["agent"] = request.headers["user-agent"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"elements": []})

    assert make_client(handler).fetch(BBOX) == []
    assert seen["method"] == "POST"
    assert seen["agent"].startswith("smart-basket/")
    assert "shop" in seen["body"]
    assert "supermarket" in seen["body"]


def test_a_server_error_is_retried_once():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"elements": [MERCADONA]})

    assert [element["id"] for element in make_client(handler).fetch(BBOX)] == [1]
    assert len(attempts) == 2


def test_a_persistent_failure_raises_overpass_error():
    with pytest.raises(OverpassError, match="HTTP 504"):
        make_client(lambda request: httpx.Response(504)).fetch(BBOX)


def test_a_client_error_is_not_retried():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400)

    with pytest.raises(OverpassError, match="HTTP 400"):
        make_client(handler).fetch(BBOX)
    assert len(attempts) == 1


def test_an_answer_without_elements_is_rejected():
    with pytest.raises(OverpassError, match="elements"):
        make_client(lambda request: httpx.Response(200, json={"version": 0.6})).fetch(BBOX)


def test_fetch_stores_keeps_only_the_ten_chains():
    other = {
        "type": "node",
        "id": 2,
        "lat": 42.6,
        "lon": -5.57,
        "tags": {"shop": "supermarket", "brand": "Eroski"},
    }
    client = make_client(lambda request: httpx.Response(200, json={"elements": [MERCADONA, other]}))

    assert [observation.osm_id for observation in fetch_stores(client, BBOX)] == ["node/1"]
