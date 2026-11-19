"""Parsing of Dia `plp-insight` payloads and Spanish size expressions, with synthetic data."""

from decimal import Decimal as D

import pytest

from smart_basket.ingestion.base import CategoryObservation, ProductObservation
from smart_basket.ingestion.dia import (
    parse_dia_menu,
    parse_dia_products,
    parse_dia_size,
)


def nested_menu() -> dict[str, object]:
    return {
        "menu_analytics": {
            "menu": [
                {
                    "code": "L1_bebidas",
                    "name": "Bebidas",
                    "children": [
                        {"code": "L2_agua", "name": "Agua"},
                        {"code": "L2_refrescos", "name": "Refrescos"},
                        {"code": "L2_todo_bebidas", "name": "Todo en bebidas"},
                        {"code": "L1_bebidas", "name": "Bebidas"},
                    ],
                },
                {
                    "code": "L1_limpieza",
                    "name": "Limpieza",
                    "children": [{"code": "L2_hogar", "name": "Hogar"}],
                },
            ]
        }
    }


def flat_menu() -> dict[str, object]:
    return {
        "menu_analytics": [
            {
                "parent_code": "L1_bebidas",
                "parent_name": "Bebidas",
                "child_code": "L2_agua",
                "child_name": "Agua",
            },
            {
                "parent_code": "L1_bebidas",
                "parent_name": "Bebidas",
                "child_code": "L2_refrescos",
                "child_name": "Refrescos",
            },
            {
                "parent_code": "L1_bebidas",
                "parent_name": "Bebidas",
                "child_code": "L2_todo_bebidas",
                "child_name": "Todo en bebidas",
            },
            {
                "parent_code": "L1_bebidas",
                "parent_name": "Bebidas",
                "child_code": "L1_bebidas",
                "child_name": "Bebidas",
            },
            {
                "parent_code": "L1_limpieza",
                "parent_name": "Limpieza",
                "child_code": "L2_hogar",
                "child_name": "Hogar",
            },
        ]
    }


def keyed_menu() -> dict[str, object]:
    """The real shape: dict keyed by level 1 code, with `parameter`, `path` and `children`."""
    return {
        "menu_analytics": {
            "L101": {
                "parameter": "L1_quesos",
                "path": "/quesos/c/L101",
                "children": {
                    "L101": {"parameter": "L2_todo quesos", "path": "/quesos/c/L101"},
                    "L2007": {"parameter": "L2_curado", "path": "/quesos/curado/c/L2007"},
                    "L2008": {"parameter": "L2_frescos", "path": "/quesos/frescos/c/L2008"},
                },
            },
            "L102": {
                "parameter": "L1_lacteos",
                "path": "/lacteos/c/L102",
                "children": {
                    "L2009": {"parameter": "L2_leche", "path": "/lacteos/leche/c/L2009"},
                },
            },
        }
    }


def make_product(
    *,
    sku: str = "100",
    display_name: str = "Agua mineral 1,5 l",
    price: object = "0,65 €",
    stock_availability: object = True,
    url: object = "/supermercado/agua-mineral",
) -> dict[str, object]:
    return {
        "object_id": sku,
        "display_name": display_name,
        "prices_price": price,
        "stock_availability": stock_availability,
        "url": url,
    }


@pytest.mark.parametrize("payload", [nested_menu(), flat_menu()])
def test_parse_dia_menu_keeps_level_one_and_two_and_drops_self_links(payload):
    categories = parse_dia_menu(payload)

    assert CategoryObservation("bebidas", "Bebidas", None) in categories
    assert CategoryObservation("agua", "Agua", "bebidas") in categories
    assert CategoryObservation("refrescos", "Refrescos", "bebidas") in categories
    assert CategoryObservation("limpieza", "Limpieza", None) in categories
    assert CategoryObservation("hogar", "Hogar", "limpieza") in categories
    assert tuple(category.code for category in categories) == (
        "bebidas",
        "agua",
        "refrescos",
        "limpieza",
        "hogar",
    )


def test_parse_dia_menu_reads_the_real_dict_keyed_shape():
    categories = parse_dia_menu(keyed_menu())

    assert tuple(
        (category.code, category.name, category.parent_code) for category in categories
    ) == (
        ("L101", "quesos", None),
        ("L2007", "curado", "L101"),
        ("L2008", "frescos", "L101"),
        ("L102", "lacteos", None),
        ("L2009", "leche", "L102"),
    )


def test_parse_dia_menu_ignores_todo_umbrella_links():
    codes = [category.code for category in parse_dia_menu(nested_menu())]

    assert "todo_bebidas" not in codes
    assert all("todo" not in code for code in codes)


def test_parse_dia_menu_without_menu_analytics_is_empty():
    assert parse_dia_menu({"page_product_analytics": {}}) == []
    assert parse_dia_menu({"menu_analytics": {}}) == []


@pytest.mark.parametrize(
    ("name", "quantity", "unit", "pack"),
    [
        ("Agua 33 cl", D("0.33"), "l", 1),
        ("Harina 200 g", D("0.2"), "kg", 1),
        ("Leche 1,5 l", D("1.5"), "l", 1),
        ("Zumo 750 ml", D("0.75"), "l", 1),
        ("Azúcar 1 kg", D("1"), "kg", 1),
        ("Refresco 6 x 33 cl", D("0.33"), "l", 6),
        ("Galletas pack 4 x 125 g", D("0.125"), "kg", 4),
        ("Caja 6 uds", D("6"), "ud", 1),
        ("Pack 2 x 1 l", D("1"), "l", 2),
    ],
)
def test_parse_dia_size_normalizes_spanish_expressions(name, quantity, unit, pack):
    assert parse_dia_size(name) == (quantity, unit, pack)


@pytest.mark.parametrize("name", ["Producto sin tamaño", "", "Bolsa reutilizable"])
def test_parse_dia_size_leaves_names_without_a_size_empty(name):
    assert parse_dia_size(name) == (None, None, 1)


def test_a_zero_pack_count_is_rejected():
    assert parse_dia_size("Pack 0 x 33 cl") == (None, None, 1)


def test_a_product_gets_decimal_price_size_per_unit_and_deterministic_image():
    payload = {"page_product_analytics": {"products": [make_product()]}}

    products = parse_dia_products(payload, category_code="agua")

    assert len(products) == 1
    product = products[0]
    assert product.sku == "100"
    assert product.name == "Agua mineral 1,5 l"
    assert product.price == D("0.65")
    assert (product.base_quantity, product.base_unit) == (D("1.5"), "l")
    assert product.pack_count == 1
    assert product.price_per_unit == D("0.4333")
    assert product.category_code == "agua"
    assert product.url == "https://www.dia.es/supermercado/agua-mineral"
    assert product.image_url == (
        "https://www.dia.es/product_images/100/100_ISO_0_ES.jpg?imwidth=384"
    )


def test_a_multipack_keeps_the_per_unit_size_and_the_pack_count():
    payload = {
        "page_product_analytics": {
            "products": [make_product(sku="200", display_name="Galletas pack 4 x 125 g", price=4.0)]
        }
    }

    product = parse_dia_products(payload, category_code="galletas")[0]

    assert (product.base_quantity, product.base_unit) == (D("0.125"), "kg")
    assert product.pack_count == 4
    assert product.price == D("4.00")
    assert product.price_per_unit == D("8.0000")


def test_a_product_without_a_recognizable_size_has_no_price_per_unit():
    payload = {
        "page_product_analytics": {
            "products": [make_product(display_name="Bolsa reutilizable", price="1.00")]
        }
    }

    product = parse_dia_products(payload, category_code="hogar")[0]

    assert (product.base_quantity, product.base_unit) == (None, None)
    assert product.price_per_unit is None


def test_out_of_stock_products_are_dropped():
    payload = {
        "page_product_analytics": {
            "products": [
                make_product(sku="1", stock_availability=False),
                make_product(sku="2", stock_availability=True),
            ]
        }
    }

    assert [product.sku for product in parse_dia_products(payload, category_code="agua")] == ["2"]


@pytest.mark.parametrize("price", [None, "", "sin precio", -1])
def test_products_with_a_missing_or_invalid_price_are_dropped(price):
    payload = {"page_product_analytics": {"products": [make_product(price=price)]}}

    assert parse_dia_products(payload, category_code="agua") == []


def test_the_listing_alternate_keys_are_accepted():
    payload = {
        "page_product_analytics": {
            "plp_items": [
                {
                    "id": "300",
                    "name": "Leche 1 l",
                    "price": "0,99",
                    "stock_availability": True,
                }
            ]
        }
    }

    product = parse_dia_products(payload, category_code="lacteos")[0]

    assert product.sku == "300"
    assert product.price == D("0.99")
    assert product.base_quantity == D("1")
    assert product.base_unit == "l"


def test_parse_dia_products_reads_the_real_dict_keyed_shape():
    payload = {
        "page_product_analytics": {
            "192": {
                "item_id": "192",
                "item_name": "cerveza clasica dia ramblers 33 cl",
                "item_brand": "dia ramblers",
                "price": 0.32,
                "stock_availability": True,
            },
            "193": {
                "item_id": "193",
                "item_name": "cerveza tostada dia ramblers 33 cl",
                "item_brand": "dia ramblers",
                "price": 0.35,
                "stock_availability": False,
            },
        }
    }

    products = parse_dia_products(payload, category_code="cervezas")

    assert [product.sku for product in products] == ["192"]
    assert products[0].name == "cerveza clasica dia ramblers 33 cl"
    assert products[0].price == D("0.32")
    assert (products[0].base_quantity, products[0].base_unit) == (D("0.33"), "l")


def test_an_empty_or_missing_product_page_yields_no_products():
    assert parse_dia_products({}, category_code="agua") == []
    assert parse_dia_products({"page_product_analytics": {}}, category_code="agua") == []
    assert parse_dia_products({"page_product_analytics": {"products": []}}, category_code="x") == []


def test_a_product_is_a_frozen_observation():
    payload = {"page_product_analytics": {"products": [make_product()]}}

    assert isinstance(parse_dia_products(payload, category_code="agua")[0], ProductObservation)
