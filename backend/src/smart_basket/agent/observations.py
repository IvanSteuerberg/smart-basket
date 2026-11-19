"""Typed observations emitted by the deterministic detector (ADR 0022).

An observation is the input the perceive-act loop reacts to: a vague line, an item no store
carries, a near tie between plans, or a message from the shopper. Observations are pure data
and serialize losslessly to JSON.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ObservationKind(StrEnum):
    """The four phenomena the detector can report to the agent."""

    VAGUE_LINE = "vague_line"
    MISSING_EVERYWHERE = "missing_everywhere"
    NEAR_TIE = "near_tie"
    SHOPPER_REQUEST = "shopper_request"


@dataclass(frozen=True, slots=True)
class Observation:
    """One phenomenon observed in the list or in the plan.

    `details` carries the typed evidence the actions need (candidate options, a target
    quantity, an extra stop...) and must hold JSON-safe values.
    """

    kind: ObservationKind
    summary: str
    line_index: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
            "line_index": self.line_index,
            "details": _jsonable(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Observation:
        return cls(
            kind=ObservationKind(data["kind"]),
            summary=str(data["summary"]),
            line_index=data.get("line_index"),
            details=dict(data.get("details") or {}),
        )


def _jsonable(value: Any) -> Any:
    """Convert decimals, enums, mappings and sequences into JSON-safe values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value
