"""Candidate generation must be concrete, deterministic, unique and safe for every phenomenon."""

from __future__ import annotations

import json

import pytest

from smart_basket.agent.actions import (
    ActionKind,
    CandidateAction,
    valid_actions,
)
from smart_basket.agent.observations import Observation, ObservationKind
from smart_basket.agent.state import AgentState, LineHabit, LineState


def _state(lines: tuple[LineState, ...] = (), mode: str = "walk") -> AgentState:
    return AgentState(lines=lines, mode=mode)


def _keys(candidates: tuple[CandidateAction, ...]) -> set[str]:
    return {candidate.key for candidate in candidates}


def _kinds(candidates: tuple[CandidateAction, ...]) -> set[ActionKind]:
    return {candidate.kind for candidate in candidates}


def test_vague_line_with_habit_offers_applying_it() -> None:
    habit = LineHabit(term="fruta", canonical_id=7, canonical_name="Plátano", count=9, total=10)
    state = _state((LineState(index=0, raw_text="fruta", habit=habit),))

    candidates = valid_actions(
        state, Observation(kind=ObservationKind.VAGUE_LINE, summary="fruta", line_index=0)
    )

    assert _kinds(candidates) == {
        ActionKind.PREGUNTAR,
        ActionKind.APLICAR_HABITUAL,
        ActionKind.DEJAR_SIN_COMPRAR,
        ActionKind.NO_HACER_NADA,
    }
    ask = next(item for item in candidates if item.kind is ActionKind.PREGUNTAR)
    assert ask.args["line_index"] == 0


def test_vague_line_without_habit_does_not_offer_it() -> None:
    state = _state((LineState(index=0, raw_text="algo para la cena"),))

    candidates = valid_actions(
        state,
        Observation(kind=ObservationKind.VAGUE_LINE, summary="vago", line_index=0),
    )

    assert ActionKind.APLICAR_HABITUAL not in _kinds(candidates)
    assert ActionKind.PREGUNTAR in _kinds(candidates)


def test_missing_everywhere_offers_pinned_brand_and_extra_stop() -> None:
    line = LineState(
        index=0,
        raw_text="leche sin lactosa",
        brand_pinned=True,
        substitute_options=({"canonical_id": 9},),
    )
    state = _state((line,))

    candidates = valid_actions(
        state,
        Observation(
            kind=ObservationKind.MISSING_EVERYWHERE,
            summary="no está en ninguna tienda",
            line_index=0,
            details={"extra_minutes": "6"},
        ),
    )

    assert _kinds(candidates) == {
        ActionKind.BUSCAR_SUSTITUTO,
        ActionKind.PREGUNTAR,
        ActionKind.DEJAR_SIN_COMPRAR,
        ActionKind.CAMBIAR_MARCA,
        ActionKind.COMPARAR_ESCENARIOS,
        ActionKind.NO_HACER_NADA,
    }


def test_missing_everywhere_respects_no_substitute_and_no_extra_stop() -> None:
    state = _state((LineState(index=0, raw_text="pilas AAA"),))

    candidates = valid_actions(
        state,
        Observation(
            kind=ObservationKind.MISSING_EVERYWHERE,
            summary="pilas AAA",
            line_index=0,
            details={"substitute_allowed": False},
        ),
    )

    assert _kinds(candidates) == {
        ActionKind.PREGUNTAR,
        ActionKind.DEJAR_SIN_COMPRAR,
        ActionKind.NO_HACER_NADA,
    }


def test_near_tie_offers_comparison_and_explanation() -> None:
    candidates = valid_actions(
        _state(), Observation(kind=ObservationKind.NEAR_TIE, summary="dos planes casi empatados")
    )

    assert _kinds(candidates) == {
        ActionKind.COMPARAR_ESCENARIOS,
        ActionKind.PREGUNTAR,
        ActionKind.EXPLICAR,
        ActionKind.NO_HACER_NADA,
    }


def test_shopper_request_fills_concrete_arguments() -> None:
    state = _state(
        (
            LineState(index=0, raw_text="pan"),
            LineState(index=1, raw_text="leche"),
        )
    )

    candidates = valid_actions(
        state,
        Observation(
            kind=ObservationKind.SHOPPER_REQUEST,
            summary="mejor voy en coche y quiero dos litros",
            details={"text": "huevos", "quantity": "2", "brand": "Hacendado", "chain": "Lidl"},
        ),
    )

    keys = _keys(candidates)
    assert keys == {
        "cambiar_modo",
        "comparar_escenarios",
        "quitar_linea:0",
        "quitar_linea:1",
        "modificar_cantidad:0",
        "modificar_cantidad:1",
        "cambiar_marca:0",
        "cambiar_marca:1",
        "anadir_linea:huevos",
        "excluir_cadena:Lidl",
        "explicar",
        "preguntar",
        "no_hacer_nada",
    }
    mode = next(item for item in candidates if item.kind is ActionKind.CAMBIAR_MODO)
    assert mode.args["mode"] == "car"
    quantity = next(item for item in candidates if item.key == "modificar_cantidad:0")
    assert quantity.args == {"line_index": 0, "quantity": "2"}
    brand = next(item for item in candidates if item.key == "cambiar_marca:1")
    assert brand.args == {"line_index": 1, "brand": "Hacendado"}


def test_shopper_request_with_line_index_targets_only_that_line() -> None:
    state = _state(
        (
            LineState(index=0, raw_text="pan"),
            LineState(index=1, raw_text="leche"),
        )
    )

    candidates = valid_actions(
        state,
        Observation(
            kind=ObservationKind.SHOPPER_REQUEST,
            summary="quita la leche",
            line_index=1,
        ),
    )

    keys = _keys(candidates)
    assert "quitar_linea:1" in keys
    assert "quitar_linea:0" not in keys


def test_shopper_request_flips_the_mode() -> None:
    state = _state(mode="car")

    candidates = valid_actions(
        state, Observation(kind=ObservationKind.SHOPPER_REQUEST, summary="¿y a pie?")
    )

    mode = next(item for item in candidates if item.kind is ActionKind.CAMBIAR_MODO)
    assert mode.args["mode"] == "walk"


@pytest.mark.parametrize(
    ("state", "observation"),
    [
        (
            _state((LineState(index=0, raw_text="fruta"),)),
            Observation(kind=ObservationKind.VAGUE_LINE, summary="vago", line_index=0),
        ),
        (
            _state((LineState(index=0, raw_text="tahini"),)),
            Observation(kind=ObservationKind.MISSING_EVERYWHERE, summary="falta", line_index=0),
        ),
        (_state(), Observation(kind=ObservationKind.NEAR_TIE, summary="empate")),
        (_state(), Observation(kind=ObservationKind.SHOPPER_REQUEST, summary="hola")),
    ],
)
def test_no_change_is_always_available(state: AgentState, observation: Observation) -> None:
    candidates = valid_actions(state, observation)

    assert candidates[-1].kind is ActionKind.NO_HACER_NADA
    assert len(_keys(candidates)) == len(candidates)


def test_candidate_action_round_trips() -> None:
    candidate = CandidateAction(
        key="quitar_linea:2",
        kind=ActionKind.QUITAR_LINEA,
        args={"line_index": 2},
        label="Quitar la línea",
    )

    restored = CandidateAction.from_dict(json.loads(json.dumps(candidate.to_dict())))

    assert restored == candidate
