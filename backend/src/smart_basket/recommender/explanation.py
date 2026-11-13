"""Spanish explanation of a recommendation: one sentence per store list and per missing line."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from smart_basket.optimizer.models import BasketResult, MissingLine, MissingReason

CENT = Decimal("0.01")
ONE = Decimal("1")


def explain(
    result: BasketResult,
    names_by_id: Mapping[int, str],
    line_texts: Mapping[str, str],
    extra_missing: Sequence[MissingLine] = (),
) -> str:
    """The user-visible summary, with comma decimals and whole minutes."""
    stores = _join([names_by_id[s.store_id] for s in result.stores])
    vuelta = " (ida y vuelta)" if result.return_to_origin else ""
    sentences = [
        f"Compra en {stores}. Total: {money(result.total_cost)} € y "
        f"{minutes(result.minutes)} min de trayecto{vuelta}."
    ]
    for missing in (*result.missing, *extra_missing):
        text = line_texts.get(missing.line_id, "")
        match missing.reason:
            case MissingReason.NOT_AVAILABLE:
                sentences.append(f"No hemos encontrado «{text}» en las tiendas cercanas.")
            case MissingReason.SEPARATE_STOP if missing.stop is not None:
                stop = missing.stop
                sentences.append(
                    f"«{text}» está en {names_by_id[stop.store_id]}: añadirlo hoy supone "
                    f"{minutes(stop.extra_minutes)} min más; puedes comprarlo otro día."
                )
            case _:
                sentences.append(f"No hay forma de llegar a la tienda que tiene «{text}».")
    return " ".join(sentences)


def money(value: Decimal) -> str:
    """Two decimals with a comma, as written in Spanish ("11,70")."""
    quantized = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}".replace(".", ",")


def minutes(value: Decimal) -> str:
    """Travel minutes rounded to a whole number."""
    return f"{value.quantize(ONE, rounding=ROUND_HALF_UP):.0f}"


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " y " + names[-1]
