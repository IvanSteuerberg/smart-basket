"""In-house perceive-act harness for the recommender agent (ADR 0022).

The loop starts on an observation, lets a `Policy` choose one candidate action, and applies its
effect in two phases (`propose` → `validate` → `apply`). It enforces a step cap, a time budget,
bounded retries with a deterministic fallback, a low-confidence override that asks the shopper,
and a pause/resume cycle around `waiting_shopper`. The module is pure: no network, no database.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from smart_basket.agent.actions import ActionKind, CandidateAction, valid_actions
from smart_basket.agent.observations import Observation, ObservationKind, _jsonable
from smart_basket.agent.state import AgentState, PendingQuestion, RunStatus


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """What a policy returns: the chosen candidate key and, when available, its confidence."""

    action_key: str
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    raw_response: str | None = None
    model_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_key": self.action_key,
            "confidence": self.confidence,
            "probabilities": _jsonable(self.probabilities),
            "raw_response": self.raw_response,
            "model_name": self.model_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PolicyDecision:
        return cls(
            action_key=str(data["action_key"]),
            confidence=data.get("confidence"),
            probabilities=dict(data["probabilities"]) if data.get("probabilities") else None,
            raw_response=data.get("raw_response"),
            model_name=data.get("model_name"),
        )


class Policy(Protocol):
    """Anything that can choose one candidate action for an observation."""

    name: str

    def choose(
        self,
        state: AgentState,
        observation: Observation,
        candidates: Sequence[CandidateAction],
    ) -> PolicyDecision: ...


@dataclass(frozen=True, slots=True)
class Proposal:
    """First phase of an effect: what the executor intends to do, before touching the state."""

    action: CandidateAction
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


class ActionExecutor(Protocol):
    """Two-phase effect: propose, validate, then apply. `validate` returns an error or None."""

    def propose(self, state: AgentState, action: CandidateAction) -> Proposal: ...

    def validate(self, state: AgentState, proposal: Proposal) -> str | None: ...

    def apply(self, state: AgentState, proposal: Proposal) -> AgentState: ...


class NoOpExecutor:
    """Executor that always succeeds and keeps the state: `no_hacer_nada` and tests."""

    def propose(self, state: AgentState, action: CandidateAction) -> Proposal:
        return Proposal(action=action, summary=action.label)

    def validate(self, state: AgentState, proposal: Proposal) -> str | None:
        return None

    def apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return state


_DEFAULT_ACTION_KINDS: dict[ObservationKind, ActionKind] = {
    ObservationKind.VAGUE_LINE: ActionKind.PREGUNTAR,
    ObservationKind.MISSING_EVERYWHERE: ActionKind.DEJAR_SIN_COMPRAR,
    ObservationKind.NEAR_TIE: ActionKind.NO_HACER_NADA,
    ObservationKind.SHOPPER_REQUEST: ActionKind.NO_HACER_NADA,
}


class DefaultPolicy:
    """Deterministic degradation mode: a fixed table, no model, used for the ablation (FR-41)."""

    name = "default"

    def choose(
        self,
        state: AgentState,
        observation: Observation,
        candidates: Sequence[CandidateAction],
    ) -> PolicyDecision:
        target = _DEFAULT_ACTION_KINDS[observation.kind]
        chosen = next((item for item in candidates if item.kind is target), None)
        if chosen is None:
            chosen = next(
                (item for item in candidates if item.kind is ActionKind.NO_HACER_NADA),
                candidates[0] if candidates else None,
            )
        key = chosen.key if chosen is not None else ActionKind.NO_HACER_NADA.value
        return PolicyDecision(action_key=key)


ScriptedItem = (
    PolicyDecision | str | Exception | Callable[[AgentState, Observation], PolicyDecision | str]
)


class ScriptedPolicy:
    """Policy for deterministic tests: replays decisions, keys, exceptions or callables."""

    name = "scripted"

    def __init__(self, script: Sequence[ScriptedItem]) -> None:
        self._script = list(script)
        self._position = 0

    def choose(
        self,
        state: AgentState,
        observation: Observation,
        candidates: Sequence[CandidateAction],
    ) -> PolicyDecision:
        if self._position >= len(self._script):
            raise RuntimeError("ScriptedPolicy script exhausted")
        item = self._script[self._position]
        self._position += 1
        if isinstance(item, Exception):
            raise item
        if isinstance(item, PolicyDecision):
            return item
        if callable(item):
            item = item(state, observation)
            if isinstance(item, PolicyDecision):
                return item
        return PolicyDecision(action_key=str(item))


@dataclass(frozen=True, slots=True)
class StepRecord:
    """One row of the run trace: the observation, the choice and what happened."""

    step_number: int
    observation: Observation | None
    candidates: tuple[CandidateAction, ...]
    chosen_action: str | None
    action_args: dict[str, Any]
    confidence: float | None
    probabilities: dict[str, float] | None
    retries: int
    result: str | None
    latency_ms: float
    error: str | None
    used_default: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "observation": self.observation.to_dict() if self.observation is not None else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "chosen_action": self.chosen_action,
            "action_args": _jsonable(self.action_args),
            "confidence": self.confidence,
            "probabilities": _jsonable(self.probabilities),
            "retries": self.retries,
            "result": self.result,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "used_default": self.used_default,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StepRecord:
        observation = data.get("observation")
        return cls(
            step_number=int(data["step_number"]),
            observation=Observation.from_dict(observation) if observation is not None else None,
            candidates=tuple(
                CandidateAction.from_dict(item) for item in data.get("candidates") or ()
            ),
            chosen_action=data.get("chosen_action"),
            action_args=dict(data.get("action_args") or {}),
            confidence=data.get("confidence"),
            probabilities=dict(data["probabilities"]) if data.get("probabilities") else None,
            retries=int(data.get("retries", 0)),
            result=data.get("result"),
            latency_ms=float(data.get("latency_ms", 0.0)),
            error=data.get("error"),
            used_default=bool(data.get("used_default", False)),
        )


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of one run: the final state, its trace and the limits it hit."""

    state: AgentState
    steps: tuple[StepRecord, ...]
    status: RunStatus
    total_latency_ms: float
    policy_name: str
    model_name: str | None


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    """Limits fixed by ADR 0022: six steps and two retries, with an optional time budget."""

    max_steps: int = 6
    time_budget_ms: int = 10_000
    max_retries: int = 2
    low_confidence_threshold: float | None = None


class AgentHarness:
    """Runs the perceive-act loop of a `Policy`, enforcing every limit of ADR 0022."""

    def __init__(self, config: HarnessConfig | None = None) -> None:
        self.config = config if config is not None else HarnessConfig()

    def run(
        self,
        state: AgentState,
        policy: Policy,
        executors: Mapping[ActionKind, ActionExecutor],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> RunResult:
        return self._loop(state, policy, executors, clock)

    def resume(
        self,
        state: AgentState,
        answer: Mapping[str, Any],
        policy: Policy,
        executors: Mapping[ActionKind, ActionExecutor],
        *,
        apply_answer: Callable[[AgentState, Mapping[str, Any]], AgentState] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> RunResult:
        """Continue a paused run with the shopper's answer.

        `apply_answer` may turn the answer into state changes or new observations. Without it,
        the answer's `message` becomes a `shopper_request` observation so the loop can react.
        """
        if apply_answer is not None:
            updated = apply_answer(state, answer)
        else:
            message = answer.get("message")
            observations = state.observations
            if isinstance(message, str) and message.strip():
                observations = (
                    *observations,
                    Observation(
                        kind=ObservationKind.SHOPPER_REQUEST,
                        summary=message.strip(),
                        details={"message": message.strip()},
                    ),
                )
            updated = replace(
                state,
                observations=observations,
                shopper_message=message if isinstance(message, str) else state.shopper_message,
            )
        updated = replace(updated, pending_question=None, status=RunStatus.RUNNING)
        return self._loop(updated, policy, executors, clock)

    def _loop(
        self,
        state: AgentState,
        policy: Policy,
        executors: Mapping[ActionKind, ActionExecutor],
        clock: Callable[[], float],
    ) -> RunResult:
        started = clock()
        steps: list[StepRecord] = []
        model_name: str | None = None
        status = RunStatus.COMPLETED

        while True:
            if state.status is RunStatus.WAITING_SHOPPER:
                status = RunStatus.WAITING_SHOPPER
                break
            if state.status is RunStatus.FAILED:
                status = RunStatus.FAILED
                break
            if not state.observations:
                status = RunStatus.COMPLETED
                break
            if state.steps_taken >= self.config.max_steps:
                status = RunStatus.COMPLETED
                break
            if (clock() - started) * 1000.0 >= self.config.time_budget_ms:
                status = RunStatus.TIMED_OUT
                break

            step_started = clock()
            observation = state.observations[0]
            remaining = state.observations[1:]
            candidates = valid_actions(state, observation)
            decision, action, retries, used_default, error = self._choose(
                policy, state, observation, candidates
            )
            if decision.model_name is not None:
                model_name = decision.model_name
            action = self._apply_confidence_override(decision, action, candidates)

            # Executors work on a state where the handled observation is already consumed.
            working = replace(state, observations=remaining)
            new_state = working
            result: str | None = None
            if action is None:
                error = error or "no valid action to apply"
                applied = False
            elif (executor := executors.get(action.kind)) is None:
                error = f"no executor for action {action.kind.value}"
                applied = False
            else:
                applied, new_state, result, execution_error = self._execute(
                    executor, working, action
                )
                if execution_error is not None:
                    error = execution_error

            step_number = state.steps_taken + 1
            state = replace(new_state if applied else working, steps_taken=step_number)

            if applied and action is not None and action.kind is ActionKind.PREGUNTAR:
                state = replace(
                    state,
                    pending_question=state.pending_question or _question_for(action, observation),
                    status=RunStatus.WAITING_SHOPPER,
                )

            steps.append(
                StepRecord(
                    step_number=step_number,
                    observation=observation,
                    candidates=candidates,
                    chosen_action=action.key if action is not None else None,
                    action_args=dict(action.args) if action is not None else {},
                    confidence=decision.confidence,
                    probabilities=decision.probabilities,
                    retries=retries,
                    result=result,
                    latency_ms=(clock() - step_started) * 1000.0,
                    error=error,
                    used_default=used_default,
                )
            )

        return RunResult(
            state=replace(state, status=status),
            steps=tuple(steps),
            status=status,
            total_latency_ms=(clock() - started) * 1000.0,
            policy_name=policy.name,
            model_name=model_name,
        )

    def _choose(
        self,
        policy: Policy,
        state: AgentState,
        observation: Observation,
        candidates: Sequence[CandidateAction],
    ) -> tuple[PolicyDecision, CandidateAction | None, int, bool, str | None]:
        attempts = 0
        last_error: str | None = None
        while True:
            attempts += 1
            try:
                decision = policy.choose(state, observation, candidates)
                action = _resolve(candidates, decision.action_key)
                if action is None:
                    raise ValueError(f"unknown action_key {decision.action_key!r}")
                return decision, action, attempts - 1, False, None
            except Exception as exc:  # a policy may raise anything; the harness retries
                last_error = _describe(exc)
                if attempts > self.config.max_retries:
                    break
        fallback = DefaultPolicy().choose(state, observation, candidates)
        action = _resolve(candidates, fallback.action_key)
        if action is None and candidates:
            action = candidates[0]
        return fallback, action, self.config.max_retries, True, last_error

    def _apply_confidence_override(
        self,
        decision: PolicyDecision,
        action: CandidateAction | None,
        candidates: Sequence[CandidateAction],
    ) -> CandidateAction | None:
        threshold = self.config.low_confidence_threshold
        if threshold is None or decision.confidence is None or decision.confidence >= threshold:
            return action
        ask = next((item for item in candidates if item.kind is ActionKind.PREGUNTAR), None)
        return ask if ask is not None else action

    def _execute(
        self,
        executor: ActionExecutor,
        state: AgentState,
        action: CandidateAction,
    ) -> tuple[bool, AgentState, str | None, str | None]:
        try:
            proposal = executor.propose(state, action)
            problem = executor.validate(state, proposal)
            if problem is not None:
                return False, state, None, f"validation failed: {problem}"
            return True, executor.apply(state, proposal), proposal.summary, None
        except Exception as exc:  # an executor failure must not corrupt the state
            return False, state, None, _describe(exc)


def _resolve(candidates: Sequence[CandidateAction], key: str) -> CandidateAction | None:
    return next((item for item in candidates if item.key == key), None)


def _question_for(action: CandidateAction, observation: Observation) -> PendingQuestion:
    index = action.args.get("line_index")
    return PendingQuestion(
        line_index=index if isinstance(index, int) else None,
        prompt=f"El agente necesita tu ayuda: {observation.summary}",
        options=tuple(dict(item) for item in action.args.get("options") or ()),
    )


def _describe(exc: Exception) -> str:
    message = str(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
