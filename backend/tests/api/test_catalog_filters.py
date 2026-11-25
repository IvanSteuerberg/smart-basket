"""Catalog filters of the product and canonical listings (iteration 17, task E3).

The nine filter families of the assignment over PostgreSQL: search relevance, taxonomy keys,
multi-chain codes, brand names and private labels, dietary tags, active promotions, price
bounds, the PostGIS origin with its travel modes, and every sort order. Chains, zones and
taxonomy come from the packaged seed; the products, stores and promotions exist only in the test
database and are rolled back after each test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.products import (
    CATEGORY_ERROR,
    LATITUDE_ERROR,
    LONGITUDE_ERROR,
    MAX_PRICE_ERROR,
    MIN_PRICE_ERROR,
    MODE_ERROR,
    NEAR_PAIR_ERROR,
    PRICE_RANGE_ERROR,
    SECTION_ERROR,
    SORT_ERROR,
)
from tests.api.test_products import _canonical, _chain_category, _product, _scalar

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

ACEITE = "Aceite de oliva virgen extra"
ATUN = "Atún en aceite de oliva"
PASCUAL = "Leche entera Pascual"
CONDENSADA = "Leche condensada azucarada La Lechera"
GAL_HACENDADO = "Galletas maría Hacendado"
GAL_FONTANEDA = "Galletas maría Fontaneda"
GAL_GULLON = "Galletas maría Gullón"
YOGUR_CLA = "Yogur natural Central Lechera Asturiana"
LECHE_DIA = "Leche entera Delicious"
LECHE_CARREFOUR = "Leche entera Carrefour"

#: The origin of the near tests, inside the city of León.
LEON_LAT = 42.6
LEON_LON = -5.57

PRICE_ORDER = [
    LECHE_DIA,
    PASCUAL,
    GAL_FONTANEDA,
    LECHE_CARREFOUR,
    GAL_GULLON,
    GAL_HACENDADO,
    YOGUR_CLA,
    CONDENSADA,
    ATUN,
    ACEITE,
]
UNIT_PRICE_ORDER = [
    LECHE_DIA,
    PASCUAL,
    LECHE_CARREFOUR,
    YOGUR_CLA,
    GAL_FONTANEDA,
    GAL_GULLON,
    GAL_HACENDADO,
    CONDENSADA,
    ACEITE,
    ATUN,
]
NAME_ORDER = [
    ACEITE,
    ATUN,
    GAL_FONTANEDA,
    GAL_GULLON,
    GAL_HACENDADO,
    CONDENSADA,
    LECHE_CARREFOUR,
    LECHE_DIA,
    PASCUAL,
    YOGUR_CLA,
]
#: The canonical of "Leche entera" is sold by three chains, the other two by one each.
POPULAR_ORDER = [
    LECHE_DIA,
    PASCUAL,
    LECHE_CARREFOUR,
    ATUN,
    ACEITE,
    GAL_FONTANEDA,
    GAL_GULLON,
    GAL_HACENDADO,
    YOGUR_CLA,
    CONDENSADA,
]

CANON_LECHE = "Leche entera"
CANON_COVERAGE_ORDER = [CANON_LECHE, ATUN, ACEITE]
CANON_POPULAR_ORDER = [CANON_LECHE, ACEITE, ATUN]
CANON_UNIT_PRICE_ORDER = [CANON_LECHE, ACEITE, ATUN]
CANON_PRICE_ORDER = [CANON_LECHE, ATUN, ACEITE]
CANON_NAME_ORDER = [ACEITE, ATUN, CANON_LECHE]


@dataclass(frozen=True)
class FilterCatalog:
    products: dict[str, int]
    canonicals: dict[str, int]


def _store(
    session: Session, chain_id: int, zone_id: int, name: str, *, lon: float, lat: float
) -> None:
    session.execute(
        text(
            "insert into store (chain_id, zone_id, name, geom)"
            " values (:chain, :zone, :name, st_setsrid(st_makepoint(:lon, :lat), 4326)::geography)"
        ),
        {"chain": chain_id, "zone": zone_id, "name": name, "lon": lon, "lat": lat},
    )


def _zone(session: Session, chain_id: int, code: str) -> int:
    return _scalar(
        session,
        "insert into zone (chain_id, kind, code, name)"
        " values (:chain, 'postal_code', :code, 'Lejana') returning id",
        chain=chain_id,
        code=code,
    )


def _dietary(session: Session, product_id: int, tags: tuple[str, ...]) -> None:
    session.execute(
        text("update chain_product set dietary_tags = :tags where id = :id"),
        {"tags": list(tags), "id": product_id},
    )


def _promo(
    session: Session,
    chain_id: int,
    product_id: int,
    *,
    back: int,
    ahead: int,
    zone_id: int | None = None,
) -> int:
    """A `promo_price` promotion valid from `back` days ago to `ahead` days ahead."""
    promo_id = _scalar(
        session,
        "insert into promotion (chain_id, kind, promo_price, valid, source)"
        " values (:chain, 'promo_price', 0.01,"
        " daterange(current_date - :back, current_date + :ahead), 'web') returning id",
        chain=chain_id,
        back=back,
        ahead=ahead,
    )
    session.execute(
        text("insert into promotion_target (promotion_id, chain_product_id) values (:p, :product)"),
        {"p": promo_id, "product": product_id},
    )
    if zone_id is not None:
        session.execute(
            text("insert into promotion_zone (promotion_id, zone_id) values (:p, :zone)"),
            {"p": promo_id, "zone": zone_id},
        )
    return promo_id


def seed_filter_catalog(session: Session) -> FilterCatalog:
    """A three-chain catalog around the León origin used by the near tests."""
    mercadona = _scalar(session, "select id from chain where code = 'mercadona'")
    dia = _scalar(session, "select id from chain where code = 'dia'")
    carrefour = _scalar(session, "select id from chain where code = 'carrefour'")
    zone_mercadona = _scalar(
        session, "select id from zone where chain_id = :chain order by id limit 1", chain=mercadona
    )
    zone_dia = _scalar(
        session, "select id from zone where chain_id = :chain order by id limit 1", chain=dia
    )
    zone_carrefour = _scalar(
        session, "select id from zone where chain_id = :chain order by id limit 1", chain=carrefour
    )
    # Active stores: Mercadona and Dia inside the walking radius, Carrefour about 12 km away,
    # outside the walking radius but within the driving one.
    _store(session, mercadona, zone_mercadona, "Mercadona E3", lon=-5.570, lat=42.600)
    _store(session, dia, zone_dia, "Dia E3", lon=-5.572, lat=42.599)
    _store(session, carrefour, zone_carrefour, "Carrefour E3", lon=-5.720, lat=42.600)

    m_aceite = _chain_category(session, mercadona, "T-E3-ACEITE", "aceite_oliva_virgen_extra")
    m_atun = _chain_category(session, mercadona, "T-E3-ATUN", "atun")
    m_leche = _chain_category(session, mercadona, "T-E3-LECHE", "leche")
    m_condensada = _chain_category(session, mercadona, "T-E3-CONDENSADA", "leche_condensada")
    m_galletas = _chain_category(session, mercadona, "T-E3-GALLETAS", "galletas_maria")
    m_yogur = _chain_category(session, mercadona, "T-E3-YOGUR", "yogur_natural")
    d_leche = _chain_category(session, dia, "T-E3-LECHE-DIA", "leche")
    c_leche = _chain_category(session, carrefour, "T-E3-LECHE-CARREFOUR", "leche")

    canonicals = {
        "leche": _canonical(session, "leche", CANON_LECHE),
        "aceite": _canonical(session, "aceite_oliva_virgen_extra", ACEITE),
        "atun": _canonical(session, "atun", ATUN),
    }

    products: dict[str, int] = {}

    def add(
        key: str,
        chain_id: int,
        zone_id: int,
        chain_category_id: int,
        sku: str,
        name: str,
        price: str,
        quantity: str,
        unit: str,
        canonical_id: int | None = None,
        dietary: tuple[str, ...] = (),
    ) -> None:
        products[key] = _product(
            session,
            chain_id=chain_id,
            chain_category_id=chain_category_id,
            zone_id=zone_id,
            sku=sku,
            name=name,
            price=price,
            quantity=quantity,
            unit=unit,
            canonical_id=canonical_id,
        )
        if dietary:
            _dietary(session, products[key], dietary)

    add(
        "aceite",
        mercadona,
        zone_mercadona,
        m_aceite,
        "e3-aceite",
        ACEITE,
        "8.50",
        "1",
        "l",
        canonical_id=canonicals["aceite"],
    )
    add(
        "atun",
        mercadona,
        zone_mercadona,
        m_atun,
        "e3-atun",
        ATUN,
        "3.00",
        "0.08",
        "kg",
        canonical_id=canonicals["atun"],
    )
    add(
        "pascual",
        mercadona,
        zone_mercadona,
        m_leche,
        "e3-leche-pascual",
        PASCUAL,
        "0.95",
        "1",
        "l",
        canonical_id=canonicals["leche"],
    )
    add(
        "condensada",
        mercadona,
        zone_mercadona,
        m_condensada,
        "e3-condensada",
        CONDENSADA,
        "2.50",
        "0.4",
        "kg",
    )
    add(
        "hacendado",
        mercadona,
        zone_mercadona,
        m_galletas,
        "e3-gal-hacendado",
        GAL_HACENDADO,
        "1.20",
        "0.2",
        "kg",
        dietary=("sin_gluten",),
    )
    add(
        "fontaneda",
        mercadona,
        zone_mercadona,
        m_galletas,
        "e3-gal-fontaneda",
        GAL_FONTANEDA,
        "1.00",
        "0.2",
        "kg",
        dietary=("sin_gluten", "sin_lactosa"),
    )
    add(
        "gullon",
        mercadona,
        zone_mercadona,
        m_galletas,
        "e3-gal-gullon",
        GAL_GULLON,
        "1.10",
        "0.2",
        "kg",
        dietary=("sin_lactosa",),
    )
    add("yogur", mercadona, zone_mercadona, m_yogur, "e3-yogur-cla", YOGUR_CLA, "1.50", "1", "kg")
    add(
        "delicious",
        dia,
        zone_dia,
        d_leche,
        "e3-leche-dia",
        LECHE_DIA,
        "0.89",
        "1",
        "l",
        canonical_id=canonicals["leche"],
    )
    add(
        "carrefour",
        carrefour,
        zone_carrefour,
        c_leche,
        "e3-leche-carrefour",
        LECHE_CARREFOUR,
        "1.05",
        "1",
        "l",
        canonical_id=canonicals["leche"],
    )

    # A chain-wide promotion active today, one that expired yesterday, and one that only
    # applies to a zone none of the chain's active stores belongs to.
    _promo(session, mercadona, products["pascual"], back=10, ahead=10)
    _promo(session, mercadona, products["aceite"], back=30, ahead=-1)
    far_zone = _zone(session, mercadona, "24099")
    _promo(session, mercadona, products["yogur"], back=5, ahead=5, zone_id=far_zone)
    session.flush()
    return FilterCatalog(products=products, canonicals=canonicals)


@pytest.fixture
def catalog(session: Session) -> FilterCatalog:
    return seed_filter_catalog(session)


def _products(client, **params) -> list[dict]:
    response = client.get("/api/products", params={"size": 60, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _names(client, **params) -> list[str]:
    return [item["name"] for item in _products(client, **params)]


def _canonicals(client, **params) -> dict:
    response = client.get("/api/canonicals", params={"size": 60, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _canonical_names(client, **params) -> list[str]:
    return [item["name"] for item in _canonicals(client, **params)["items"]]


def test_search_ranks_the_whole_phrase_above_late_word_matches(client, catalog):
    # "Aceite de oliva virgen extra" starts with the whole phrase; "Atún en aceite de oliva"
    # only carries both words later in its name.
    assert _names(client, q="aceite de oliva") == [ACEITE, ATUN]
    assert _canonical_names(client, q="aceite de oliva") == [ACEITE, ATUN]


def test_search_ranks_the_common_product_above_rare_variants(client, catalog):
    # The three chains sell the canonical "Leche entera", so the whole-word matches of the
    # query come first; the one-chain condensed variant only shares the first word.
    expected = [LECHE_DIA, PASCUAL, LECHE_CARREFOUR, CONDENSADA]
    assert _names(client, q="leche") == expected
    assert _names(client, q="leche", sort="relevance") == expected
    assert YOGUR_CLA not in _names(client, q="leche")


def test_section_and_category_filters_use_the_subtree(client, catalog):
    assert len(_names(client, section="despensa")) == 5
    assert len(_names(client, section="lacteos_huevos")) == 5
    # A second-level group and third-level leaves.
    assert len(_names(client, category="leche_bebidas")) == 4
    assert len(_names(client, category="leche")) == 3
    assert len(_names(client, category="galletas_maria")) == 3
    assert _names(client, category="aceite_oliva_virgen_extra") == [ACEITE]
    assert _names(client, category="leche", chains="dia") == [LECHE_DIA]


def test_unknown_section_or_category_is_a_spanish_422(client, catalog):
    cases = [
        ({"section": "no-existe"}, SECTION_ERROR),
        ({"category": "no-existe"}, CATEGORY_ERROR),
    ]
    for params, message in cases:
        for endpoint in ("/api/products", "/api/canonicals"):
            response = client.get(endpoint, params=params)
            assert response.status_code == 422, (endpoint, params)
            assert response.json()["detail"] == message


def test_chains_filter_accepts_several_codes_and_the_single_alias(client, catalog):
    assert len(_names(client)) == 10
    names = _names(client, chains="mercadona,dia")
    assert len(names) == 9
    assert LECHE_CARREFOUR not in names
    assert _names(client, chains="carrefour") == [LECHE_CARREFOUR]
    assert _names(client, chain="dia") == [LECHE_DIA]
    # The values are trimmed and case-folded.
    assert len(_names(client, chains="Dia, MERCADONA")) == 9
    assert _names(client, chains="otra") == []

    data = _canonicals(client, chain="dia")
    assert data["total"] == 1
    item = data["items"][0]
    assert item["name"] == CANON_LECHE
    assert item["product_count"] == 1
    assert item["from_price"] == "0.89"
    assert item["chains"] == ["carrefour", "dia", "mercadona"]

    item = _canonicals(client, chains="mercadona,dia")["items"][0]
    assert item["product_count"] == 2
    assert item["from_price"] == "0.89"


def test_brand_filter_matches_the_name_and_the_aliases(client, catalog):
    items = _products(client, brand="hacendado")
    assert [item["name"] for item in items] == [GAL_HACENDADO]
    assert items[0]["brand"] == "Hacendado"
    assert _names(client, brand="pascual") == [PASCUAL]
    # "Central Lechera" is an alias of "Central Lechera Asturiana" in the brand seed.
    assert _names(client, brand="central lechera") == [YOGUR_CLA]
    assert _names(client, brand="Central Lechera Asturiana") == [YOGUR_CLA]
    assert _names(client, brand="bimbo") == []
    assert _names(client, brand="carrefour", chains="dia") == []


def test_private_label_filter(client, catalog):
    assert set(_names(client, private_label="true")) == {
        GAL_HACENDADO,
        LECHE_DIA,
        LECHE_CARREFOUR,
    }
    assert set(_names(client, private_label="false")) == {
        ACEITE,
        ATUN,
        PASCUAL,
        CONDENSADA,
        GAL_FONTANEDA,
        GAL_GULLON,
        YOGUR_CLA,
    }
    items = {item["name"]: item for item in _products(client)}
    assert items[GAL_HACENDADO]["private_label"] is True
    assert items[PASCUAL]["private_label"] is False


def test_dietary_filter_requires_every_tag(client, catalog):
    assert _names(client, dietary="sin_gluten") == [GAL_FONTANEDA, GAL_HACENDADO]
    assert _names(client, dietary="sin_gluten,sin_lactosa") == [GAL_FONTANEDA]
    assert _names(client, dietary="sin_lactosa") == [GAL_FONTANEDA, GAL_GULLON]
    items = _products(client, dietary="sin_gluten,sin_lactosa")
    assert items[0]["dietary_tags"] == ["sin_gluten", "sin_lactosa"]
    plain = {item["name"]: item for item in _products(client)}
    assert plain[PASCUAL]["dietary_tags"] == []


def test_on_promo_flag_and_filter(client, catalog):
    items = {item["name"]: item for item in _products(client)}
    assert items[PASCUAL]["on_promo"] is True
    assert items[ACEITE]["on_promo"] is False  # the promotion expired yesterday
    assert items[YOGUR_CLA]["on_promo"] is False  # only promoted in an unused zone
    assert items[LECHE_DIA]["on_promo"] is False  # the promotion belongs to another chain
    assert _names(client, on_promo="true") == [PASCUAL]
    assert len(_names(client, on_promo="false")) == 9
    detail = client.get(f"/api/products/{catalog.products['pascual']}").json()
    assert detail["on_promo"] is True


def test_price_bounds_filter_and_validation(client, catalog):
    assert len(_names(client, min_price="1.00")) == 8
    assert len(_names(client, max_price="1.10")) == 5
    assert len(_names(client, min_price="1.00", max_price="1.20")) == 4
    cases = [
        ({"min_price": "-1"}, MIN_PRICE_ERROR),
        ({"max_price": "-0.5"}, MAX_PRICE_ERROR),
        ({"min_price": "5", "max_price": "1"}, PRICE_RANGE_ERROR),
    ]
    for params, message in cases:
        response = client.get("/api/products", params=params)
        assert response.status_code == 422, params
        assert response.json()["detail"] == message
    # The canonical listing validates the same bounds.
    response = client.get("/api/canonicals", params={"min_price": "5", "max_price": "1"})
    assert response.status_code == 422
    assert response.json()["detail"] == PRICE_RANGE_ERROR


def test_near_filter_uses_the_store_radius_and_the_travel_mode(client, catalog):
    walk = {"near_lat": LEON_LAT, "near_lon": LEON_LON, "mode": "walk"}
    names = _names(client, **walk)
    assert len(names) == 9
    assert LECHE_CARREFOUR not in names
    assert LECHE_DIA in names
    # The default mode is walking.
    assert len(_names(client, near_lat=LEON_LAT, near_lon=LEON_LON)) == 9
    # By car the 20 km radius reaches the far store.
    names = _names(client, near_lat=LEON_LAT, near_lon=LEON_LON, mode="car")
    assert len(names) == 10
    assert LECHE_CARREFOUR in names
    # A chain filter intersects with the nearby chains.
    data = client.get("/api/products", params={"chains": "carrefour", **walk}).json()
    assert data["total"] == 0
    data = client.get(
        "/api/products",
        params={"chains": "carrefour", "near_lat": LEON_LAT, "near_lon": LEON_LON, "mode": "car"},
    ).json()
    assert data["total"] == 1
    # The canonical listing keeps the three canonicals of the nearby chains.
    data = _canonicals(client, **walk)
    assert data["total"] == 3
    assert sorted(item["name"] for item in data["items"]) == [ACEITE, ATUN, CANON_LECHE]


def test_near_validation_errors(client, catalog):
    cases = [
        ({"near_lat": LEON_LAT}, NEAR_PAIR_ERROR),
        ({"near_lon": LEON_LON}, NEAR_PAIR_ERROR),
        ({"near_lat": LEON_LAT, "near_lon": LEON_LON, "mode": "bike"}, MODE_ERROR),
        ({"near_lat": 95, "near_lon": LEON_LON}, LATITUDE_ERROR),
        ({"near_lat": LEON_LAT, "near_lon": -200}, LONGITUDE_ERROR),
    ]
    for params, message in cases:
        for endpoint in ("/api/products", "/api/canonicals"):
            response = client.get(endpoint, params=params)
            assert response.status_code == 422, (endpoint, params)
            assert response.json()["detail"] == message


def test_product_sort_orders(client, catalog):
    assert _names(client, sort="price") == PRICE_ORDER
    assert _names(client, sort="unit_price") == UNIT_PRICE_ORDER
    assert _names(client, sort="name") == NAME_ORDER
    assert _names(client, sort="popular") == POPULAR_ORDER
    # Without a query the relevance order falls back to popularity.
    assert _names(client, sort="relevance") == POPULAR_ORDER


def test_canonical_sort_orders(client, catalog):
    assert _canonical_names(client, sort="relevance") == CANON_COVERAGE_ORDER
    assert _canonical_names(client, sort="popular") == CANON_POPULAR_ORDER
    assert _canonical_names(client, sort="unit_price") == CANON_UNIT_PRICE_ORDER
    assert _canonical_names(client, sort="price") == CANON_PRICE_ORDER
    assert _canonical_names(client, sort="name") == CANON_NAME_ORDER


def test_invalid_sort_is_a_spanish_422(client, catalog):
    for endpoint in ("/api/products", "/api/canonicals"):
        response = client.get(endpoint, params={"sort": "cheapest"})
        assert response.status_code == 422, endpoint
        assert response.json()["detail"] == SORT_ERROR
