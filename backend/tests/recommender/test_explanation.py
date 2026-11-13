"""Spanish explanation templates, with hand-built optimizer results."""

from decimal import Decimal

from smart_basket.optimizer import (
    BaseUnit,
    BasketResult,
    CoverRule,
    LinePurchase,
    MissingLine,
    MissingReason,
    PriorityMode,
    SeparateStop,
    StorePurchase,
)
from smart_basket.recommender.explanation import explain


def basket(
    *store_ids: int,
    missing: tuple[MissingLine, ...] = (),
    total: str = "10.00",
    minutes: str = "12.5",
    return_to_origin: bool = True,
) -> BasketResult:
    return BasketResult(
        engine_version="basket-engine/1.1.0",
        stores=tuple(
            StorePurchase(store_id, 1, position, (), Decimal(0))
            for position, store_id in enumerate(store_ids, start=1)
        ),
        total_cost=Decimal(total),
        comparable_cost=Decimal(total),
        minutes=Decimal(minutes),
        lambda_per_minute=Decimal("0.15"),
        coverage_margin=Decimal("3"),
        objective=Decimal(0),
        priority_mode=PriorityMode.BALANCED,
        max_stores=3,
        return_to_origin=return_to_origin,
        missing=missing,
    )


def stop(store_id: int = 2, minutes: str = "8.0") -> SeparateStop:
    purchase = LinePurchase(
        line_id="1",
        canonical_id=1,
        base_unit=BaseUnit.KG,
        rule=CoverRule.COVER,
        quantity_requested=Decimal(1),
        quantity_bought=Decimal(1),
        cost=Decimal("2.10"),
        comparable_cost=Decimal("2.10"),
        packs=(),
    )
    return SeparateStop(
        store_id=store_id,
        chain_id=1,
        purchase=purchase,
        extra_minutes=Decimal(minutes),
        extra_objective=Decimal(0),
        exceeds_max_stores=False,
    )


NAMES = {1: "Mercadona", 2: "Mercadona Centro", 3: "Carrefour"}
TEXTS = {"0": "pan", "1": "salmón", "2": "harina"}


def test_stores_are_joined_and_minutes_rounded():
    explained = explain(basket(1, 2), NAMES, TEXTS)
    assert explained == (
        "Compra en Mercadona y Mercadona Centro. Total: 10,00 € y 13 min de trayecto "
        "(ida y vuelta)."
    )


def test_three_stores_comma_then_y_and_one_way_route():
    explained = explain(basket(1, 2, 3, return_to_origin=False), NAMES, TEXTS)
    assert explained == (
        "Compra en Mercadona, Mercadona Centro y Carrefour. Total: 10,00 € y 13 min de trayecto."
    )


def test_every_missing_reason_has_its_sentence():
    missing = (
        MissingLine("0", MissingReason.NOT_AVAILABLE),
        MissingLine("1", MissingReason.SEPARATE_STOP, stop()),
        MissingLine("2", MissingReason.UNREACHABLE),
    )
    explained = explain(basket(1, missing=missing), NAMES, TEXTS)
    assert explained.endswith(
        "No hemos encontrado «pan» en las tiendas cercanas. "
        "«salmón» está en Mercadona Centro: añadirlo hoy supone 8 min más; "
        "puedes comprarlo otro día. "
        "No hay forma de llegar a la tienda que tiene «harina»."
    )
