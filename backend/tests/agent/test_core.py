"""Perceive-act loop: limits, retries, two-phase effects, low confidence and pause/resume."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from smart_basket.agent.actions import ActionKind, CandidateAction, valid_actions
from smart_basket.agent.core import (
    AgentHarness,
    DefaultPolicy,
    HarnessConfig,
    NoOpExecutor,
    PolicyDecision,
    Proposal,
    ScriptedPolicy,
    StepRecord,
)
from smart_basket.agent.observations import Observation, ObservationKind
from smart_basket.agent.state import AgentState, LineState, RunStatus


class RecordingExecutor:
    """Executor that logs the two phases and can mutate the state when applied."""

    def __init__(
        self,
        transform: Callable[[AgentState, CandidateAction], AgentState] | None = None,
    ) -> None:
        self.transform = transform
        self.proposed: list[str] = []
        self.validated: list[str] = []
        self.applied: list[str] = []

    def propose(self, state: AgentState, action: CandidateAction) -> Proposal:
        self.proposed.append(action.key)
        return Proposal(action=action, summary=f"executed {action.kind.value}")

    def validate(self, state: AgentState, proposal: Proposal) -> str | None:
        self.validated.append(proposal.action.key)
        return None

    def apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        self.applied.append(proposal.action.key)
        if self.transform is not None:
            return self.transform(state, proposal.action)
        return state


class RejectingExecutor(RecordingExecutor):
    """Executor whose validation always fails, so `apply` must never run."""

    def validate(self, state: AgentState, proposal: Proposal) -> str | None:
        self.validated.append(proposal.action.key)
        return "rejected by test"


class StepClock:
    """Fake clock that advances a fixed amount on every read, in milliseconds."""

    def __init__(self, step_ms: int) -> None:
        self.step_ms = step_ms
        self.reads = 0

    def __call__(self) -> float:
        value = self.reads * self.step_ms / 1000.0
        self.reads += 1
        return value


def all_noop() -> dict[ActionKind, NoOpExecutor]:
    return {kind: NoOpExecutor() for kind in ActionKind}


def _missing() -> Observation:
    return Observation(
        kind=ObservationKind.MISSING_EVERYWHERE,
        summary="no está en ninguna tienda",
        line_index=0,
        details={"substitute_allowed": False},
    )


def _near_tie() -> Observation:
    return Observation(kind=ObservationKind.NEAR_TIE, summary="dos planes casi empatados")


def test_loop_reacts_to_the_observation_emitted_by_the_previous_action() -> None:
    follow_up = _near_tie()

    def emit(current: AgentState, action: CandidateAction) -> AgentState:
        return replace(current, observations=(*current.observations, follow_up))

    executors = all_noop()
    executors[ActionKind.DEJAR_SIN_COMPRAR] = RecordingExecutor(emit)
    state = AgentState(lines=(LineState(index=0, raw_text="tahini"),), observations=(_missing(),))

    result = AgentHarness().run(
        state, ScriptedPolicy(["dejar_sin_comprar", "no_hacer_nada"]), executors
    )

    assert result.status is RunStatus.COMPLETED
    assert [step.observation.kind for step in result.steps] == [
        ObservationKind.MISSING_EVERYWHERE,
        ObservationKind.NEAR_TIE,
    ]
    assert result.state.observations == ()
    assert result.state.steps_taken == 2


def test_max_steps_is_a_hard_cap() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),) * 10)

    result = AgentHarness(HarnessConfig(max_steps=6)).run(state, DefaultPolicy(), all_noop())

    assert result.status is RunStatus.COMPLETED
    assert len(result.steps) == 6
    assert result.state.steps_taken == 6
    assert len(result.state.observations) == 4


def test_time_budget_stops_the_loop_before_the_next_step() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),) * 10)
    harness = AgentHarness(HarnessConfig(max_steps=10, time_budget_ms=10_000))

    result = harness.run(state, DefaultPolicy(), all_noop(), clock=StepClock(step_ms=4_000))

    assert result.status is RunStatus.TIMED_OUT
    assert len(result.steps) == 1


def test_no_observations_completes_without_steps() -> None:
    result = AgentHarness().run(AgentState(lines=()), DefaultPolicy(), all_noop())

    assert result.status is RunStatus.COMPLETED
    assert result.steps == ()
    assert result.state.status is RunStatus.COMPLETED


def test_invalid_action_key_is_retried_once() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),))

    result = AgentHarness().run(state, ScriptedPolicy(["desconocida", "no_hacer_nada"]), all_noop())

    step = result.steps[0]
    assert step.retries == 1
    assert step.used_default is False
    assert step.chosen_action == "no_hacer_nada"
    assert step.error is None
    assert result.status is RunStatus.COMPLETED


def test_policy_exception_is_retried_once() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),))

    result = AgentHarness().run(
        state, ScriptedPolicy([ValueError("boom"), "no_hacer_nada"]), all_noop()
    )

    step = result.steps[0]
    assert step.retries == 1
    assert step.used_default is False
    assert step.chosen_action == "no_hacer_nada"


def test_three_failures_fall_back_to_the_default_policy() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),))

    result = AgentHarness().run(state, ScriptedPolicy(["uno", "dos", "tres"]), all_noop())

    step = result.steps[0]
    assert step.retries == 2
    assert step.used_default is True
    assert step.chosen_action == "no_hacer_nada"
    assert step.error is not None
    assert "unknown action_key" in step.error
    assert result.status is RunStatus.COMPLETED


def test_low_confidence_forces_a_question_and_pauses() -> None:
    executor = RecordingExecutor()
    executors = all_noop()
    executors[ActionKind.PREGUNTAR] = executor
    state = AgentState(
        lines=(LineState(index=0, raw_text="fruta"),),
        observations=(
            Observation(kind=ObservationKind.VAGUE_LINE, summary="fruta es vago", line_index=0),
        ),
    )
    harness = AgentHarness(HarnessConfig(low_confidence_threshold=0.5))

    result = harness.run(
        state,
        ScriptedPolicy([PolicyDecision(action_key="dejar_sin_comprar", confidence=0.1)]),
        executors,
    )

    step = result.steps[0]
    assert step.chosen_action == "preguntar"
    assert executor.applied == ["preguntar"]
    assert result.status is RunStatus.WAITING_SHOPPER
    assert result.state.pending_question is not None
    assert result.state.pending_question.line_index == 0
    assert "fruta es vago" in result.state.pending_question.prompt


def test_validation_failure_prevents_apply_and_keeps_the_state() -> None:
    executor = RejectingExecutor()
    executors = all_noop()
    executors[ActionKind.DEJAR_SIN_COMPRAR] = executor
    state = AgentState(lines=(LineState(index=0, raw_text="tahini"),), observations=(_missing(),))

    result = AgentHarness().run(state, DefaultPolicy(), executors)

    assert executor.validated == ["dejar_sin_comprar"]
    assert executor.applied == []
    step = result.steps[0]
    assert step.chosen_action == "dejar_sin_comprar"
    assert step.error == "validation failed: rejected by test"
    assert result.state.lines == state.lines
    assert result.state.observations == ()
    assert result.status is RunStatus.COMPLETED


def test_step_record_round_trips_through_json() -> None:
    state = AgentState(lines=(), observations=(_near_tie(),))

    result = AgentHarness().run(state, DefaultPolicy(), all_noop())

    dumped = json.loads(json.dumps(result.steps[0].to_dict()))
    assert StepRecord.from_dict(dumped) == result.steps[0]


def test_pause_and_resume_from_the_serialized_state() -> None:
    state = AgentState(
        lines=(LineState(index=0, raw_text="fruta"),),
        observations=(
            Observation(kind=ObservationKind.VAGUE_LINE, summary="fruta es vago", line_index=0),
        ),
    )
    paused = AgentHarness().run(state, ScriptedPolicy(["preguntar"]), all_noop())

    assert paused.status is RunStatus.WAITING_SHOPPER
    assert paused.state.pending_question is not None
    assert json.loads(json.dumps(paused.state.to_dict()))["pending_question"] is not None

    restored = AgentState.from_dict(json.loads(json.dumps(paused.state.to_dict())))
    resumed = AgentHarness().resume(restored, {"message": "plátanos"}, DefaultPolicy(), all_noop())

    assert resumed.status is RunStatus.COMPLETED
    assert resumed.state.shopper_message == "plátanos"
    assert resumed.state.pending_question is None
    assert resumed.state.observations == ()
    assert len(resumed.steps) == 1
    assert resumed.steps[0].observation.kind is ObservationKind.SHOPPER_REQUEST


def test_resume_can_apply_the_answer_with_a_hook() -> None:
    paused_state = AgentState(
        lines=(LineState(index=0, raw_text="fruta"),),
        steps_taken=1,
        status=RunStatus.WAITING_SHOPPER,
    )
    follow_up = _near_tie()

    def apply_answer(current: AgentState, answer: dict[str, Any]) -> AgentState:
        line = replace(
            current.lines[0],
            canonical_id=answer["canonical_id"],
            canonical_name=answer["name"],
        )
        return replace(current, lines=(line,), observations=(follow_up,))

    resumed = AgentHarness().resume(
        paused_state,
        {"canonical_id": 7, "name": "Plátano"},
        DefaultPolicy(),
        all_noop(),
        apply_answer=apply_answer,
    )

    assert resumed.status is RunStatus.COMPLETED
    assert resumed.state.lines[0].canonical_name == "Plátano"
    assert resumed.state.steps_taken == 2
    assert [step.observation.kind for step in resumed.steps] == [ObservationKind.NEAR_TIE]


@pytest.mark.parametrize(
    ("observation_kind", "expected"),
    [
        (ObservationKind.VAGUE_LINE, ActionKind.PREGUNTAR),
        (ObservationKind.MISSING_EVERYWHERE, ActionKind.DEJAR_SIN_COMPRAR),
        (ObservationKind.NEAR_TIE, ActionKind.NO_HACER_NADA),
        (ObservationKind.SHOPPER_REQUEST, ActionKind.NO_HACER_NADA),
    ],
)
def test_default_policy_maps_every_observation(
    observation_kind: ObservationKind, expected: ActionKind
) -> None:
    line = LineState(index=0, raw_text="x")
    state = AgentState(lines=(line,))
    observation = Observation(kind=observation_kind, summary="x", line_index=0)
    candidates = valid_actions(state, observation)

    decision = DefaultPolicy().choose(state, observation, candidates)

    chosen = next(candidate for candidate in candidates if candidate.key == decision.action_key)
    assert chosen.kind is expected


def test_default_policy_falls_back_when_the_mapped_action_is_absent() -> None:
    observation = Observation(kind=ObservationKind.VAGUE_LINE, summary="x")
    candidates = (
        CandidateAction(
            key="explicar",
            kind=ActionKind.EXPLICAR,
            args={},
            label="Explicar",
        ),
    )

    decision = DefaultPolicy().choose(AgentState(lines=()), observation, candidates)

    assert decision.action_key == "explicar"
