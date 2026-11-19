"""Closed action catalog and concrete candidate generation (ADR 0022).

The agent never calls tools freely: for each observation, code lists the actions that are valid
in the current state, already filled with concrete arguments. The model only chooses one key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from smart_basket.agent.observations import Observation, ObservationKind, jsonable
from smart_basket.agent.state import AgentState, LineState


class ActionKind(StrEnum):
    """The thirteen actions of the closed catalog (`experiments/decision-spike/scenarios.json`)."""

    BUSCAR_SUSTITUTO = "buscar_sustituto"
    PREGUNTAR = "preguntar"
    DEJAR_SIN_COMPRAR = "dejar_sin_comprar"
    APLICAR_HABITUAL = "aplicar_habitual"
    CAMBIAR_MODO = "cambiar_modo"
    COMPARAR_ESCENARIOS = "comparar_escenarios"
    QUITAR_LINEA = "quitar_linea"
    ANADIR_LINEA = "anadir_linea"
    MODIFICAR_CANTIDAD = "modificar_cantidad"
    CAMBIAR_MARCA = "cambiar_marca"
    EXCLUIR_CADENA = "excluir_cadena"
    EXPLICAR = "explicar"
    NO_HACER_NADA = "no_hacer_nada"


@dataclass(frozen=True, slots=True)
class CandidateAction:
    """One concrete option offered to the policy: a stable `key`, its kind and its arguments.

    `args` may hold rich Python values while the run is in memory; serialization normalizes it
    to JSON-native primitives (`str`, `int`, `float`, `bool`, `None`, `list`, `dict`), with
    `Decimal` travelling as `str` (see `jsonable`).
    """

    key: str
    kind: ActionKind
    args: dict[str, Any]
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "args": jsonable(self.args),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidateAction:
        return cls(
            key=str(data["key"]),
            kind=ActionKind(data["kind"]),
            args=dict(data.get("args") or {}),
            label=str(data["label"]),
        )


_LABELS: dict[ActionKind, str] = {
    ActionKind.BUSCAR_SUSTITUTO: "Buscar un sustituto",
    ActionKind.PREGUNTAR: "Preguntar al comprador",
    ActionKind.DEJAR_SIN_COMPRAR: "Dejar la línea sin comprar",
    ActionKind.APLICAR_HABITUAL: "Aplicar la elección habitual",
    ActionKind.CAMBIAR_MODO: "Cambiar el modo de desplazamiento",
    ActionKind.COMPARAR_ESCENARIOS: "Comparar escenarios",
    ActionKind.QUITAR_LINEA: "Quitar la línea",
    ActionKind.ANADIR_LINEA: "Añadir una línea",
    ActionKind.MODIFICAR_CANTIDAD: "Cambiar la cantidad",
    ActionKind.CAMBIAR_MARCA: "Cambiar la marca",
    ActionKind.EXCLUIR_CADENA: "Excluir una cadena",
    ActionKind.EXPLICAR: "Explicar el plan",
    ActionKind.NO_HACER_NADA: "No hacer nada",
}


def valid_actions(state: AgentState, observation: Observation) -> tuple[CandidateAction, ...]:
    """List the concrete actions valid for `observation` in `state`.

    Keys are deterministic and unique, and `no_hacer_nada` is always offered as the safe option.
    """
    match observation.kind:
        case ObservationKind.VAGUE_LINE:
            candidates = _vague_line(state, observation)
        case ObservationKind.MISSING_EVERYWHERE:
            candidates = _missing_everywhere(state, observation)
        case ObservationKind.NEAR_TIE:
            candidates = _near_tie()
        case ObservationKind.SHOPPER_REQUEST:
            candidates = _shopper_request(state, observation)
        case _:  # pragma: no cover - ObservationKind is closed
            candidates = _no_change()
    return _dedupe(candidates)


def _vague_line(state: AgentState, observation: Observation) -> list[CandidateAction]:
    line = _line_at(state, observation.line_index)
    if line is None:
        # The observation points at a line that is not in the state: never target it. A generic
        # question is still safe; everything else needs a concrete line.
        return [_candidate(ActionKind.PREGUNTAR), _no_change()]
    candidates = [
        _candidate(
            ActionKind.PREGUNTAR,
            line_index=line.index,
            options=list(line.candidate_options),
        )
    ]
    if line.habit is not None:
        candidates.append(_candidate(ActionKind.APLICAR_HABITUAL, line_index=line.index))
    candidates.append(_candidate(ActionKind.DEJAR_SIN_COMPRAR, line_index=line.index))
    return [*candidates, _no_change()]


def _missing_everywhere(state: AgentState, observation: Observation) -> list[CandidateAction]:
    line = _line_at(state, observation.line_index)
    substitute_allowed = observation.details.get("substitute_allowed", True) is not False
    candidates: list[CandidateAction] = []
    if line is None:
        # No valid target line: only line-free actions are safe.
        candidates.append(_candidate(ActionKind.PREGUNTAR))
        if _has_extra_stop(observation.details):
            candidates.append(_candidate(ActionKind.COMPARAR_ESCENARIOS))
        return [*candidates, _no_change()]
    if substitute_allowed or line.substitute_options:
        candidates.append(_candidate(ActionKind.BUSCAR_SUSTITUTO, line_index=line.index))
    candidates.append(_candidate(ActionKind.PREGUNTAR, line_index=line.index))
    candidates.append(_candidate(ActionKind.DEJAR_SIN_COMPRAR, line_index=line.index))
    if line.brand_pinned:
        candidates.append(_candidate(ActionKind.CAMBIAR_MARCA, line_index=line.index))
    if _has_extra_stop(observation.details):
        candidates.append(_candidate(ActionKind.COMPARAR_ESCENARIOS, line_index=line.index))
    return [*candidates, _no_change()]


def _near_tie() -> list[CandidateAction]:
    return [
        _candidate(ActionKind.COMPARAR_ESCENARIOS),
        _candidate(ActionKind.PREGUNTAR),
        _candidate(ActionKind.EXPLICAR),
        _no_change(),
    ]


def _shopper_request(state: AgentState, observation: Observation) -> list[CandidateAction]:
    other_mode = "car" if state.mode == "walk" else "walk"
    details = observation.details
    candidates = [
        _candidate(ActionKind.CAMBIAR_MODO, mode=other_mode),
        _candidate(ActionKind.COMPARAR_ESCENARIOS, mode=other_mode),
    ]

    # Only existing lines can be targeted; a request naming a missing line still allows the
    # line-free actions (add an item, exclude a chain, explain, ask).
    if observation.line_index is not None:
        line = _line_at(state, observation.line_index)
        targets = (line.index,) if line is not None else ()
    else:
        targets = tuple(line.index for line in state.lines)

    quantity = _positive_quantity(details.get("quantity"))
    for index in targets:
        candidates.append(_candidate(ActionKind.QUITAR_LINEA, line_index=index, suffix=index))
        if quantity is not None:
            candidates.append(
                _candidate(
                    ActionKind.MODIFICAR_CANTIDAD,
                    line_index=index,
                    quantity=str(quantity),
                    suffix=index,
                )
            )
    if "brand" in details or details.get("accept_any_brand"):
        for index in targets:
            candidates.append(
                _candidate(
                    ActionKind.CAMBIAR_MARCA,
                    line_index=index,
                    brand=details.get("brand"),
                    suffix=index,
                )
            )
    # Keys stay opaque: free text from the shopper travels only in `args`, never in the key.
    text = details.get("text")
    if text:
        candidates.append(_candidate(ActionKind.ANADIR_LINEA, text=str(text), suffix=0))
    chain = details.get("chain")
    if chain:
        candidates.append(_candidate(ActionKind.EXCLUIR_CADENA, chain=str(chain), suffix=0))
    candidates.extend(
        [
            _candidate(ActionKind.EXPLICAR),
            _candidate(ActionKind.PREGUNTAR),
            _no_change(),
        ]
    )
    return candidates


def _candidate(
    kind: ActionKind,
    *,
    key: str | None = None,
    suffix: str | int | None = None,
    **args: Any,
) -> CandidateAction:
    """Build a candidate; `suffix` namespaces its key (e.g. `quitar_linea:0`)."""
    return CandidateAction(
        key=key or (kind.value if suffix is None else f"{kind.value}:{suffix}"),
        kind=kind,
        args=args,
        label=_LABELS[kind],
    )


def _positive_quantity(value: Any) -> Decimal | None:
    """Parse `value` as a finite positive `Decimal`, or return None when it is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        quantity = Decimal(str(value))
    except InvalidOperation, ValueError:
        return None
    if not quantity.is_finite() or quantity <= 0:
        return None
    return quantity


def _no_change() -> CandidateAction:
    return _candidate(ActionKind.NO_HACER_NADA)


def _line_at(state: AgentState, index: int | None) -> LineState | None:
    if index is None:
        return None
    return next((line for line in state.lines if line.index == index), None)


def _has_extra_stop(details: Mapping[str, Any]) -> bool:
    return bool(
        details.get("extra_stop")
        or details.get("extra_minutes") is not None
        or details.get("extra_objective") is not None
    )


def _dedupe(candidates: Sequence[CandidateAction]) -> tuple[CandidateAction, ...]:
    seen: set[str] = set()
    unique: list[CandidateAction] = []
    for candidate in candidates:
        if candidate.key not in seen:
            seen.add(candidate.key)
            unique.append(candidate)
    return tuple(unique)
