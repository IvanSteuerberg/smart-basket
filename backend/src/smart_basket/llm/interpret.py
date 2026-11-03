"""Interpretation of the lines the preprocessor could not resolve (decision 0005, point 3).

Only the unresolved lines are sent, in one call. If the provider fails or answers with
something unusable, the rule-based items stay (degraded mode, FR-41).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smart_basket.llm.base import LLMError, LLMProvider
from smart_basket.preprocessor import PreprocessResult

UNITS = ["ud", "kg", "g", "l", "ml"]

#: Same shape as ITEM_SCHEMA in experiments/llm-benchmark/bench.py.
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": UNITS},
                    "brand": {"type": ["string", "null"]},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                    "ambiguous": {"type": "boolean"},
                },
                "required": ["item", "quantity", "unit", "ambiguous"],
            },
        }
    },
    "required": ["items"],
}

#: The interpretation prompt of the benchmark (decision 0005), unchanged.
SYSTEM_PROMPT = (
    "Eres el intérprete de listas de la compra de un recomendador de supermercados en España. "
    "Convierte la lista del usuario en artículos. Para cada artículo da: item (nombre genérico en "
    "español, sin cantidad), quantity (número), unit (ud, kg, g, l o ml; usa ud si no se indica), "
    "brand (solo si el usuario la pide), attributes (por ejemplo sin lactosa, integral, sin "
    'gluten) y ambiguous (true si el artículo es vago, como "algo para la cena"). Responde solo '
    "con el JSON pedido."
)


@dataclass(frozen=True, slots=True)
class Interpretation:
    items: list[dict[str, Any]]
    llm_used: bool
    degraded: bool
    error: str | None = None


def _valid(items: Any) -> bool:
    if not isinstance(items, list):
        return False
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("item"), str):
            return False
        if not isinstance(it.get("quantity"), int | float) or it.get("unit") not in UNITS:
            return False
        if not isinstance(it.get("ambiguous"), bool):
            return False
    return True


def interpret_unresolved(result: PreprocessResult, provider: LLMProvider | None) -> Interpretation:
    """Rule-based items for resolved lines plus the LLM's items for the rest, in list order."""
    rule_items = [i.to_item() for i in result.items]
    if not result.llm_lines:
        return Interpretation(rule_items, llm_used=False, degraded=False)
    if provider is None:
        return Interpretation(rule_items, llm_used=False, degraded=True)
    try:
        answer = provider.generate_json(SYSTEM_PROMPT, result.llm_input(), ITEM_SCHEMA)
    except LLMError as exc:
        return Interpretation(rule_items, llm_used=False, degraded=True, error=str(exc))
    llm_items = answer.get("items") if isinstance(answer, dict) else None
    if not _valid(llm_items):
        return Interpretation(
            rule_items, llm_used=False, degraded=True, error="invalid items from the LLM"
        )
    merged: list[dict[str, Any]] = []
    inserted = False
    for item in result.items:
        if item.resolved:
            merged.append(item.to_item())
        elif not inserted:
            # The LLM may split or merge vague lines, so its items replace them as a block,
            # at the position of the first unresolved line.
            merged.extend(llm_items)
            inserted = True
    return Interpretation(merged, llm_used=True, degraded=False)
