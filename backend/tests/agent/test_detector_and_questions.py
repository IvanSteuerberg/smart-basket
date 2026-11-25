"""Observation priority, near-tie filtering, concrete questions and `apply_shopper_answer` (E4).

Everything here is pure: the simulated executors need no database.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

from smart_basket.agent.actions import ActionKind, CandidateAction
from smart_basket.agent.detector import (
    _near_tie_observation,
    alternative_reason,
    detect_observations,
)
from smart_basket.agent.executors import apply_shopper_answer, build_simulated_executors
from smart_basket.agent.observations import ObservationKind
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineState,
    PendingQuestion,
    PlanSnapshot,
)

GENERIC = "El agente necesita tu ayuda para elegir esta línea."


def alt(
    names: tuple[str, ...],
    codes: tuple[str, ...],
    cost: str = "10.10",
    minutes: str = "5",
    delta: str = "0.10",
) -> AlternativePlanSummary:
    return AlternativePlanSummary(
        store_names=names,
        total_cost=D(cost),
        travel_minutes=D(minutes),
        objective_delta=D(delta),
        chain_codes=codes,
        cost_delta=D(cost) - D("10.00"),
        minutes_delta=D(minutes) - D("5"),
        reason="Opción similar (+0,10 €)",
    )


def state_with(*alternatives: AlternativePlanSummary, **kw) -> AgentState:
    plan = PlanSnapshot(
        store_names=("Alimerka Centro", "Dia Norte"),
        total_cost=D("10.00"),
        travel_minutes=D("5"),
        alternatives=alternatives,
        chain_codes=("alimerka", "dia"),
    )
    return AgentState(lines=(LineState(0, "leche"),), plan=plan, **kw)


def ask(state: AgentState, **args):
    executors = build_simulated_executors()
    action = CandidateAction("preguntar", ActionKind.PREGUNTAR, args, "Preguntar")
    executor = executors[ActionKind.PREGUNTAR]
    proposal = executor.propose(state, action)
    assert executor.validate(state, proposal) is None
    return executor.apply(state, proposal).pending_question


def test_shopper_request_goes_first_even_with_a_near_tie():
    tie = alt(("Lidl",), ("lidl",))
    state = state_with(tie, shopper_message="Pide un cambio")
    kinds = [o.kind for o in detect_observations(state)]
    assert kinds[0] is ObservationKind.SHOPPER_REQUEST
    assert ObservationKind.NEAR_TIE in kinds


def test_no_near_tie_between_branches_of_the_same_chains():
    same = alt(("Alimerka Sur", "Dia Este"), ("alimerka", "dia"))
    assert _near_tie_observation(state_with(same), D("0.20")) is None
    # Without chain codes (old state) the store names decide.
    same_names = alt(("dia norte", "ALIMERKA CENTRO"), ())
    assert _near_tie_observation(state_with(same_names), D("0.20")) is None


def test_near_tie_between_different_chains_carries_deltas_and_reason():
    other = alt(("Lidl",), ("lidl",))
    observation = _near_tie_observation(state_with(other), D("0.20"))
    assert observation is not None
    [shown] = observation.details["alternatives"]
    assert shown["chain_codes"] == ["lidl"]
    assert shown["cost_delta"] == "0.10"
    assert shown["minutes_delta"] == "0"
    assert shown["reason"]


def test_alternative_reason_texts():
    kw = {"current_stores": 2}
    assert (
        alternative_reason(stores=1, cost_delta=D("0.45"), minutes_delta=D("1"), **kw)
        == "Solo 1 tienda (+0,45 €)"
    )
    assert (
        alternative_reason(stores=2, cost_delta=D("-0.80"), minutes_delta=D("4"), **kw)
        == "Ahorra 0,80 € (+4 min)"
    )
    assert (
        alternative_reason(stores=2, cost_delta=D("0.30"), minutes_delta=D("-5"), **kw)
        == "5 min más rápido (+0,30 €)"
    )
    assert (
        alternative_reason(stores=2, cost_delta=D("0.10"), minutes_delta=D("0"), **kw)
        == "Opción similar (+0,10 €)"
    )


def test_question_for_a_vague_line_has_options_and_a_skip():
    option = {"label": "Pechuga", "canonical_id": 7}
    line = LineState(0, "pollo", status="vague", candidate_options=(option,))
    question = ask(replace(state_with(), lines=(line,)), line_index=0)
    assert question.prompt == "¿Qué tipo de «pollo» prefieres?"
    assert question.prompt != GENERIC
    assert question.options[0] == option
    assert question.options[-1]["action"] == "skip"


def test_question_for_a_missing_line_offers_substitutes_and_a_skip():
    substitute = {"label": "Salmón", "canonical_id": 9}
    line = LineState(0, "merluza", status="missing", substitute_options=(substitute,))
    question = ask(replace(state_with(), lines=(line,)), line_index=0)
    assert "«merluza» no está disponible" in question.prompt
    assert [o["label"] for o in question.options] == ["Salmón", "Dejar sin comprar"]


def test_question_for_a_tie_compares_plans_with_clickable_options():
    other = alt(("Lidl",), ("lidl",))
    question = ask(state_with(other), line_index=None)
    assert "Alimerka Centro + Dia Norte" in question.prompt
    assert "10.00 €" in question.prompt
    assert question.options[0]["action"] == "keep_plan"
    assert question.options[1]["action"] == "select_alternative"
    assert question.options[1]["chain_codes"] == ["lidl"]


def test_free_request_without_options_asks_to_be_more_specific():
    question = ask(state_with(shopper_message="haz algo raro"))
    assert question is not None
    assert "haz algo raro" in question.prompt


def paused(state: AgentState, question: PendingQuestion) -> AgentState:
    return replace(state, pending_question=question)


def vague_state() -> AgentState:
    options = (
        {"label": "Pechuga", "canonical_id": 7},
        {"label": "Muslo", "canonical_id": 8},
        {"label": "Dejar sin comprar", "action": "skip"},
    )
    line = LineState(0, "pollo", status="vague", candidate_options=options[:2])
    base = replace(state_with(), lines=(line,))
    return paused(base, PendingQuestion(0, "¿Qué tipo?", options))


def engine_for(state: AgentState):
    executor = build_simulated_executors()[ActionKind.PREGUNTAR]
    return executor.engine


def test_answer_by_option_index_resolves_the_line():
    state = vague_state()
    updated = apply_shopper_answer(engine_for(state), state, {"option_index": 1})
    line = updated.lines[0]
    assert line.status == "ok"
    assert line.canonical_id == 8
    assert not [o for o in updated.observations if o.line_index == 0]
    assert updated.pending_question is None


def test_answer_by_canonical_id_and_by_accented_label():
    state = vague_state()
    by_id = apply_shopper_answer(engine_for(state), state, {"canonical_id": 7})
    assert by_id.lines[0].canonical_id == 7
    by_label = apply_shopper_answer(engine_for(state), state, {"choice_label": "DEJAR SIN COMPRAR"})
    assert by_label.lines[0].status == "skipped"


def test_keep_plan_does_not_ask_the_same_tie_again():
    other = alt(("Lidl",), ("lidl",))
    base = state_with(other)
    question = PendingQuestion(None, "tie", ({"label": "Mantener", "action": "keep_plan"},))
    state = replace(paused(base, question), observations=detect_observations(base))
    updated = apply_shopper_answer(engine_for(state), state, {"option_index": 0})
    assert all(o.kind is not ObservationKind.NEAR_TIE for o in updated.observations)


def test_unmatched_free_text_becomes_a_shopper_request():
    state = vague_state()
    updated = apply_shopper_answer(engine_for(state), state, {"message": "mejor en coche"})
    assert updated.observations[0].kind is ObservationKind.SHOPPER_REQUEST
    assert updated.shopper_message == "mejor en coche"
