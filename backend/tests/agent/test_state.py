"""The agent state must survive a JSON round trip without losing decimals or nested data."""

from __future__ import annotations

import json
from decimal import Decimal

from smart_basket.agent.observations import Observation, ObservationKind
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineHabit,
    LineState,
    PendingQuestion,
    PlanSnapshot,
    RunStatus,
)


def build_state() -> AgentState:
    habit = LineHabit(term="fruta", canonical_id=42, canonical_name="Plátano", count=9, total=10)
    lines = (
        LineState(
            index=0,
            raw_text="fruta",
            canonical_id=42,
            canonical_name="Plátano",
            quantity=Decimal("1.5"),
            unit="kg",
            brand="Pascual",
            brand_pinned=True,
            exact_only=True,
            habit=habit,
            candidate_options=({"canonical_id": 7, "name": "Manzana"},),
            substitute_options=({"canonical_id": 8, "name": "Pera"},),
        ),
        LineState(index=1, raw_text="pan"),
    )
    plan = PlanSnapshot(
        store_names=("Mercadona", "Lidl"),
        total_cost=Decimal("30.10"),
        travel_minutes=Decimal("21"),
        comparable_cost=Decimal("30.40"),
        alternatives=(
            AlternativePlanSummary(
                store_names=("Mercadona",),
                total_cost=Decimal("30.40"),
                travel_minutes=Decimal("9"),
                objective_delta=Decimal("0.30"),
            ),
        ),
    )
    return AgentState(
        lines=lines,
        mode="walk",
        priority="balanced",
        excluded_chains=("Lidl",),
        dietary_rules=("sin gluten",),
        plan=plan,
        observations=(
            Observation(
                kind=ObservationKind.VAGUE_LINE,
                summary="«fruta» es vago",
                line_index=0,
                details={"options": [7, 8], "score": 0.75},
            ),
        ),
        pending_question=PendingQuestion(
            line_index=0,
            prompt="¿Qué fruta quieres?",
            options=({"canonical_id": 7, "name": "Manzana"},),
        ),
        shopper_message="hola",
        buyer_summary="Resumen del plan",
        alternatives_shown=({"mode": "car"},),
        steps_taken=2,
        status=RunStatus.WAITING_SHOPPER,
    )


def test_state_round_trip_is_lossless() -> None:
    state = build_state()
    payload = json.loads(json.dumps(state.to_dict()))

    restored = AgentState.from_dict(payload)

    assert restored == state
    assert restored.status is RunStatus.WAITING_SHOPPER
    assert restored.plan.alternatives[0].total_cost == Decimal("30.40")
    assert payload["lines"][0]["quantity"] == "1.5"
    assert payload["plan"]["total_cost"] == "30.10"


def test_empty_state_round_trips_with_defaults() -> None:
    state = AgentState(lines=())

    restored = AgentState.from_dict(json.loads(json.dumps(state.to_dict())))

    assert restored == state
    assert restored.status is RunStatus.RUNNING
    assert restored.plan == PlanSnapshot()


def test_pending_question_round_trips() -> None:
    question = PendingQuestion(
        line_index=3,
        prompt="¿Qué marca prefieres?",
        options=({"brand": "Hacendado"},),
    )

    restored = PendingQuestion.from_dict(json.loads(json.dumps(question.to_dict())))

    assert restored == question


def test_line_state_without_habit_round_trips() -> None:
    line = LineState(index=4, raw_text="pilas AAA", quantity=Decimal("2"), unit="ud")

    restored = LineState.from_dict(json.loads(json.dumps(line.to_dict())))

    assert restored == line
    assert restored.quantity == Decimal(2)
