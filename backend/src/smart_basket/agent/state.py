"""Serializable state of an agent run (ADR 0022).

The state is the only thing the perceive-act loop carries between steps, so it is pure data:
immutable dataclasses with `to_dict` / `from_dict` that survive a JSON round trip. Money,
quantities and minutes are `Decimal` and travel as strings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from smart_basket.agent.observations import Observation, jsonable


class RunStatus(StrEnum):
    """Lifecycle of one agent run."""

    RUNNING = "running"
    WAITING_SHOPPER = "waiting_shopper"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class LineHabit:
    """What the shopper usually chooses for a term, as the profile knows it."""

    term: str
    canonical_id: int | None
    canonical_name: str
    count: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "count": self.count,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LineHabit:
        return cls(
            term=str(data["term"]),
            canonical_id=data.get("canonical_id"),
            canonical_name=str(data["canonical_name"]),
            count=int(data["count"]),
            total=int(data["total"]),
        )


@dataclass(frozen=True, slots=True)
class LineState:
    """One requested line as the agent sees it before or after the preprocessor."""

    index: int
    raw_text: str
    canonical_id: int | None = None
    canonical_name: str | None = None
    quantity: Decimal = Decimal(1)
    unit: str = "ud"
    brand: str | None = None
    brand_pinned: bool = False
    exact_only: bool = False
    status: str = "ok"
    habit: LineHabit | None = None
    candidate_options: tuple[dict[str, Any], ...] = ()
    substitute_options: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "raw_text": self.raw_text,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "quantity": str(self.quantity),
            "unit": self.unit,
            "brand": self.brand,
            "brand_pinned": self.brand_pinned,
            "exact_only": self.exact_only,
            "status": self.status,
            "habit": self.habit.to_dict() if self.habit is not None else None,
            "candidate_options": jsonable(self.candidate_options),
            "substitute_options": jsonable(self.substitute_options),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LineState:
        habit = data.get("habit")
        return cls(
            index=int(data["index"]),
            raw_text=str(data["raw_text"]),
            canonical_id=data.get("canonical_id"),
            canonical_name=data.get("canonical_name"),
            quantity=Decimal(str(data.get("quantity", "1"))),
            unit=str(data.get("unit", "ud")),
            brand=data.get("brand"),
            brand_pinned=bool(data.get("brand_pinned", False)),
            exact_only=bool(data.get("exact_only", False)),
            status=str(data.get("status", "ok")),
            habit=LineHabit.from_dict(habit) if habit is not None else None,
            candidate_options=_options(data.get("candidate_options")),
            substitute_options=_options(data.get("substitute_options")),
        )


@dataclass(frozen=True, slots=True)
class AlternativePlanSummary:
    """One alternative plan shown or compared, reduced to its figures."""

    store_names: tuple[str, ...]
    total_cost: Decimal
    travel_minutes: Decimal
    objective_delta: Decimal
    chain_codes: tuple[str, ...] = ()
    cost_delta: Decimal | None = None
    minutes_delta: Decimal | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_names": list(self.store_names),
            "total_cost": str(self.total_cost),
            "travel_minutes": str(self.travel_minutes),
            "objective_delta": str(self.objective_delta),
            "chain_codes": list(self.chain_codes),
            "cost_delta": str(self.cost_delta) if self.cost_delta is not None else None,
            "minutes_delta": str(self.minutes_delta) if self.minutes_delta is not None else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AlternativePlanSummary:
        cost_delta = data.get("cost_delta")
        minutes_delta = data.get("minutes_delta")
        return cls(
            store_names=tuple(str(name) for name in data.get("store_names") or ()),
            total_cost=Decimal(str(data["total_cost"])),
            travel_minutes=Decimal(str(data["travel_minutes"])),
            objective_delta=Decimal(str(data["objective_delta"])),
            chain_codes=tuple(str(code) for code in data.get("chain_codes") or ()),
            cost_delta=Decimal(str(cost_delta)) if cost_delta is not None else None,
            minutes_delta=Decimal(str(minutes_delta)) if minutes_delta is not None else None,
            reason=data.get("reason"),
        )


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    """The current plan as the agent remembers it: stores, figures and alternatives."""

    store_names: tuple[str, ...] = ()
    total_cost: Decimal = Decimal(0)
    travel_minutes: Decimal = Decimal(0)
    comparable_cost: Decimal = Decimal(0)
    alternatives: tuple[AlternativePlanSummary, ...] = ()
    chain_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_names": list(self.store_names),
            "total_cost": str(self.total_cost),
            "travel_minutes": str(self.travel_minutes),
            "comparable_cost": str(self.comparable_cost),
            "alternatives": [item.to_dict() for item in self.alternatives],
            "chain_codes": list(self.chain_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlanSnapshot:
        return cls(
            store_names=tuple(str(name) for name in data.get("store_names") or ()),
            total_cost=Decimal(str(data.get("total_cost", "0"))),
            travel_minutes=Decimal(str(data.get("travel_minutes", "0"))),
            comparable_cost=Decimal(str(data.get("comparable_cost", "0"))),
            alternatives=tuple(
                AlternativePlanSummary.from_dict(item) for item in data.get("alternatives") or ()
            ),
            chain_codes=tuple(str(code) for code in data.get("chain_codes") or ()),
        )


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """A question the agent left for the shopper before pausing."""

    line_index: int | None
    prompt: str
    options: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_index": self.line_index,
            "prompt": self.prompt,
            "options": jsonable(self.options),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PendingQuestion:
        return cls(
            line_index=data.get("line_index"),
            prompt=str(data["prompt"]),
            options=_options(data.get("options")),
        )


@dataclass(frozen=True, slots=True)
class AgentState:
    """Everything one run knows: the list, the plan, observations and the pause state."""

    lines: tuple[LineState, ...]
    mode: str = "walk"
    priority: str = "balanced"
    excluded_chains: tuple[str, ...] = ()
    dietary_rules: tuple[str, ...] = ()
    plan: PlanSnapshot = field(default_factory=PlanSnapshot)
    observations: tuple[Observation, ...] = ()
    pending_question: PendingQuestion | None = None
    shopper_message: str | None = None
    buyer_summary: str | None = None
    alternatives_shown: tuple[dict[str, Any], ...] = ()
    steps_taken: int = 0
    status: RunStatus = RunStatus.RUNNING

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "mode": self.mode,
            "priority": self.priority,
            "excluded_chains": list(self.excluded_chains),
            "dietary_rules": list(self.dietary_rules),
            "plan": self.plan.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "pending_question": (
                self.pending_question.to_dict() if self.pending_question is not None else None
            ),
            "shopper_message": self.shopper_message,
            "buyer_summary": self.buyer_summary,
            "alternatives_shown": jsonable(self.alternatives_shown),
            "steps_taken": self.steps_taken,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentState:
        question = data.get("pending_question")
        return cls(
            lines=tuple(LineState.from_dict(line) for line in data.get("lines") or ()),
            mode=str(data.get("mode", "walk")),
            priority=str(data.get("priority", "balanced")),
            excluded_chains=tuple(str(chain) for chain in data.get("excluded_chains") or ()),
            dietary_rules=tuple(str(rule) for rule in data.get("dietary_rules") or ()),
            plan=PlanSnapshot.from_dict(data.get("plan") or {}),
            observations=tuple(
                Observation.from_dict(item) for item in data.get("observations") or ()
            ),
            pending_question=PendingQuestion.from_dict(question) if question is not None else None,
            shopper_message=data.get("shopper_message"),
            buyer_summary=data.get("buyer_summary"),
            alternatives_shown=_options(data.get("alternatives_shown")),
            steps_taken=int(data.get("steps_taken", 0)),
            status=RunStatus(data.get("status", RunStatus.RUNNING.value)),
        )


def _options(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in value or ())
