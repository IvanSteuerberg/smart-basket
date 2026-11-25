"""Recommender agent endpoints (ADR 0022): run, read and resume an agent trace.

`POST /api/agent/runs` runs the real recommendation pipeline and the perceive-act harness over
the resulting state, persisting one `agent_run` row and every `agent_step`. A run that asks the
shopper pauses in `waiting_shopper`; `POST /api/agent/runs/{id}/answer` restores the state, the
base query and the policy, and continues from the next step. The exact origin only lives in the
persisted state needed to re-optimize on resume, and only while the run stays paused: once it
completes, fails or times out, `_query` is stripped. It is never logged nor echoed in the trace.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.agent.actions import ActionKind
from smart_basket.agent.core import (
    ActionExecutor,
    AgentHarness,
    HarnessConfig,
    Policy,
    RunResult,
    StepRecord,
)
from smart_basket.agent.detector import (
    detect_observations,
    load_known_chains,
    state_from_recommendation,
)
from smart_basket.agent.executors import (
    answer_applier,
    build_recommender_executors,
    category_candidate_options,
    last_recommendation,
    plan_items,
    refresh_recommendation,
)
from smart_basket.agent.observations import ObservationKind, jsonable
from smart_basket.agent.policies import policy_from_settings
from smart_basket.agent.state import AgentState, LineHabit, RunStatus
from smart_basket.agent.trace import (
    AgentRunRow,
    AgentStepRow,
    append_step,
    create_run,
    get_run,
    update_run,
)
from smart_basket.api.recommendations import (
    BASKET_FAILED,
    NO_STORES,
    ROUTING_FAILED,
    OriginRequest,
    RecommendationRequest,
    get_routing_engine,
    get_today,
)
from smart_basket.config import Settings, get_settings
from smart_basket.db import get_session
from smart_basket.optimizer import PriorityMode, Unit
from smart_basket.recommender.candidates import candidate_stores
from smart_basket.recommender.catalog import Item, UnknownProduct
from smart_basket.recommender.service import (
    BasketCalculationError,
    ChoiceRequired,
    NoCandidateStores,
    RecommendationQuery,
    RecommendationResponse,
    recommend_with_basket,
)
from smart_basket.routing import GeoPoint, RoutingEngine, RoutingError, TravelMode

router = APIRouter(tags=["agent"])
logger = logging.getLogger(__name__)

#: The agent is shown enough alternative plans for the near-tie rule of ADR 0022.
MAX_ALTERNATIVES = 3
#: `agent_step.chosen_action` is `NOT NULL`; a step without an applicable action stores this.
NO_ACTION = "none"
AGENT_NAME = "recommender"
RUN_NOT_FOUND = "Agent run not found."


class HabitInput(BaseModel):
    """What the shopper usually chooses for a term, as the browser profile knows it."""

    term: str
    canonical_id: int | None = None
    canonical_name: str
    count: int
    total: int


class AgentRunRequest(BaseModel):
    """One agent run over a recommendation request."""

    request: RecommendationRequest
    recommendation_id: UUID | None = None
    #: Continue the conversation of another run: its lines, mode, priority, store limit and chain
    #: restrictions are inherited, and only `request.origin` and `shopper_message` are new.
    previous_run_id: UUID | None = None
    shopper_message: str | None = None
    habits: dict[str, HabitInput] = Field(default_factory=dict)
    dietary_rules: list[str] = Field(default_factory=list)
    #: Optional policy override; `"default"` forces the deterministic ablation mode.
    policy: Literal["default", "gemini_chat", "gemini_decision", "ollama_chat"] | None = None


class AgentMessageRequest(BaseModel):
    """A free-text shopper message bounded to a length a policy can carry.

    The exact `origin` is never stored once a run is completed, so the browser sends it with
    every message; a run still `waiting_shopper` keeps its own in the temporary `_query`.
    """

    message: str = Field(min_length=1, max_length=1000)
    origin: OriginRequest | None = None


class AgentAnswerRequest(BaseModel):
    """The shopper's answer to a question the agent left before pausing."""

    option_index: int | None = None
    choice_label: str | None = None
    canonical_id: int | None = None
    message: str | None = None


class AgentStepResponse(BaseModel):
    """One persisted step of an agent run."""

    step_number: int
    observation: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    chosen_action: str | None
    action_args: dict[str, Any]
    confidence: float | None
    probabilities: dict[str, float] | None
    retries: int
    used_default: bool
    result: dict[str, Any]
    latency_ms: int
    error: str | None


class AgentRunResponse(BaseModel):
    """A run with its state summary and its full ordered trace."""

    run_id: UUID
    recommendation_id: UUID | None
    status: str
    policy_name: str
    model_name: str | None
    steps_count: int
    total_latency_ms: int
    buyer_summary: str | None
    pending_question: dict[str, Any] | None
    alternatives_shown: list[dict[str, Any]]
    mode: str
    excluded_chains: list[str]
    #: What the conversation has accumulated so far besides the mode and the exclusions.
    allowed_chains: list[str] = Field(default_factory=list)
    max_stores: int | None = None
    priority: str | None = None
    recommendation: RecommendationResponse | None = None
    steps: list[AgentStepResponse]


def get_agent_policy(
    policy_override: Annotated[str | None, Query(alias="policy")] = None,
) -> Policy:
    """The configured policy; tests override this dependency to inject a scripted one."""
    return policy_from_settings(get_settings(), policy_override=policy_override)


def _harness_config(settings: Settings) -> HarnessConfig:
    return HarnessConfig(
        max_steps=settings.agent_max_steps,
        time_budget_ms=settings.agent_time_budget_ms,
        max_retries=2,
        low_confidence_threshold=settings.agent_low_confidence_threshold,
    )


def _item(item: Any) -> Item:
    """Convert one validated HTTP item into the pipeline's `Item`."""
    return Item(
        text=item.text,
        category_key=item.category_key,
        product_id=item.product_id,
        accept=item.accept,
        variants=tuple(item.variants) if item.variants is not None else None,
        quantity=item.quantity,
        unit=item.unit,
        brand=item.brand,
        private_label_ok=item.private_label_ok,
    )


def _query_from_request(request: RecommendationRequest) -> RecommendationQuery:
    # The exact origin never travels inside the payload: only the typed `origin` field keeps it,
    # and that is what the persistence layer rounds before storing (NFR-06).
    payload = request.model_dump(mode="json")
    payload.pop("origin", None)
    return RecommendationQuery(
        items=tuple(_item(item) for item in request.items),
        origin=GeoPoint(request.origin.lat, request.origin.lon),
        mode=request.mode,
        max_stores=request.max_stores,
        priority_mode=request.priority_mode,
        return_to_origin=request.return_to_origin,
        degraded=request.degraded,
        chains=tuple(request.chains or ()),
        payload=payload,
        max_alternatives=MAX_ALTERNATIVES,
    )


def _query_payload(query: RecommendationQuery) -> dict[str, Any]:
    """JSON-safe inputs needed to rebuild the query on resume.

    The exact origin travels only in the top-level `origin` field because re-optimizing
    requires it; it is never logged, and the whole payload is only persisted while the run is
    `waiting_shopper` (see `_state_payload`).
    """
    request_payload = {key: value for key, value in query.payload.items() if key != "origin"}
    return {
        "items": [_item_payload(item) for item in query.items],
        "origin": {"lat": query.origin.latitude, "lon": query.origin.longitude},
        "mode": query.mode.value,
        "max_stores": query.max_stores,
        "priority_mode": query.priority_mode.value,
        "return_to_origin": query.return_to_origin,
        "degraded": query.degraded,
        "chains": list(query.chains),
        "payload": request_payload,
    }


def _item_payload(item: Item) -> dict[str, Any]:
    return {
        "text": item.text,
        "category_key": item.category_key,
        "product_id": item.product_id,
        "accept": item.accept,
        "variants": list(item.variants) if item.variants is not None else None,
        "quantity": str(item.quantity),
        "unit": item.unit.value,
        "brand": item.brand,
        "private_label_ok": item.private_label_ok,
    }


def _item_from_payload(entry: Mapping[str, Any]) -> Item:
    return Item(
        text=entry["text"],
        category_key=entry.get("category_key"),
        product_id=entry.get("product_id"),
        accept=entry.get("accept", "equivalent"),
        variants=(tuple(entry["variants"]) if entry.get("variants") is not None else None),
        quantity=Decimal(str(entry["quantity"])),
        unit=Unit(entry["unit"]),
        brand=entry.get("brand"),
        private_label_ok=bool(entry.get("private_label_ok", True)),
    )


def _plan_spec(
    state: AgentState, query: RecommendationQuery, items: Mapping[int, Item]
) -> dict[str, Any]:
    """What a later message needs to rebuild the cumulative plan, with no origin and no route.

    Items keep their line index; the mode, priority and store limit are the ones the plan has
    now, and `chains` the restriction of the original request. The exact origin is not here
    (NFR-06): the browser sends it again with every message.
    """
    return {
        "items": [{"index": index, **_item_payload(item)} for index, item in sorted(items.items())],
        "mode": state.mode,
        "max_stores": state.max_stores,
        "priority_mode": state.priority,
        "return_to_origin": query.return_to_origin,
        "degraded": query.degraded,
        "chains": list(query.chains),
    }


def _query_from_spec(
    spec: Mapping[str, Any], origin: GeoPoint
) -> tuple[RecommendationQuery, dict[int, Item]]:
    """The base query of a continued conversation, with the origin of the request in hand."""
    items = {int(entry["index"]): _item_from_payload(entry) for entry in spec["items"]}
    query = RecommendationQuery(
        items=tuple(items[index] for index in sorted(items)),
        origin=origin,
        mode=TravelMode(spec["mode"]),
        max_stores=int(spec["max_stores"]),
        priority_mode=PriorityMode(spec["priority_mode"]),
        return_to_origin=bool(spec["return_to_origin"]),
        degraded=bool(spec["degraded"]),
        chains=tuple(str(chain) for chain in spec.get("chains") or ()),
        payload={},
        max_alternatives=MAX_ALTERNATIVES,
    )
    return query, items


def _query_from_payload(data: dict[str, Any]) -> RecommendationQuery:
    """Rebuild the pipeline query persisted in `state_json["_query"]`."""
    origin = data["origin"]
    return RecommendationQuery(
        items=tuple(_item_from_payload(entry) for entry in data["items"]),
        origin=GeoPoint(float(origin["lat"]), float(origin["lon"])),
        mode=TravelMode(data["mode"]),
        max_stores=int(data["max_stores"]),
        priority_mode=PriorityMode(data["priority_mode"]),
        return_to_origin=bool(data["return_to_origin"]),
        degraded=bool(data["degraded"]),
        chains=tuple(str(chain) for chain in data.get("chains") or ()),
        payload=dict(data.get("payload") or {}),
        max_alternatives=MAX_ALTERNATIVES,
    )


def _habits(inputs: dict[str, HabitInput]) -> dict[str, LineHabit]:
    return {
        key: LineHabit(
            term=habit.term,
            canonical_id=habit.canonical_id,
            canonical_name=habit.canonical_name,
            count=habit.count,
            total=habit.total,
        )
        for key, habit in inputs.items()
    }


def _plan_key(state: AgentState) -> tuple[Any, ...]:
    """The parts of the state a recommendation depends on, to detect whether it is stale."""
    return (
        state.mode,
        state.priority,
        state.excluded_chains,
        state.plan,
        tuple(
            (
                line.index,
                line.status,
                line.quantity,
                line.unit,
                line.canonical_id,
                line.brand,
                line.brand_pinned,
            )
            for line in state.lines
        ),
    )


def _recommendation_payload(response: RecommendationResponse) -> dict[str, Any]:
    """The response stored with the run: the route is dropped, as in the recommendation table."""
    data = response.model_dump(mode="json")
    data.pop("route", None)
    return data


def _state_payload(
    state: AgentState,
    query_payload: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
    plan_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The persisted state; the resume-only `_query` is kept only while the run is paused.

    `_query` carries the exact origin that `/answer` needs to re-optimize. Once the run leaves
    `waiting_shopper` it is stripped, so the table never holds the shopper's coordinates.
    `_plan_spec` is the origin-free part a later message needs to continue the plan.
    """
    payload = state.to_dict()
    if query_payload is not None:
        payload["_query"] = query_payload
    if recommendation is not None:
        payload["_recommendation"] = recommendation
    if plan_spec is not None:
        payload["_plan_spec"] = plan_spec
    return payload


def _persist_steps(
    session: Session, run_id: UUID, steps: tuple[StepRecord, ...], *, offset: int = 0
) -> None:
    for step in steps:
        append_step(
            session,
            run_id=run_id,
            step_number=step.step_number + offset,
            observation_json=(step.observation.to_dict() if step.observation is not None else {}),
            candidates_json=[candidate.to_dict() for candidate in step.candidates],
            chosen_action=step.chosen_action or NO_ACTION,
            action_args_json=jsonable(step.action_args),
            confidence=step.confidence,
            probabilities_json=(
                {str(key): float(value) for key, value in step.probabilities.items()}
                if step.probabilities
                else None
            ),
            retries=step.retries,
            used_default=step.used_default,
            result_json={"summary": step.result, "overridden": step.overridden},
            latency_ms=max(0, round(step.latency_ms)),
            error=step.error,
        )


def _finish_run(
    session: Session,
    run_id: UUID,
    *,
    status_value: str,
    steps_count: int,
    total_latency_ms: int,
) -> None:
    finished_at = (
        None
        if status_value in {RunStatus.WAITING_SHOPPER.value, RunStatus.RUNNING.value}
        else datetime.now(UTC)
    )
    update_run(
        session,
        run_id,
        status=status_value,
        steps_count=steps_count,
        total_latency_ms=max(0, total_latency_ms),
        finished_at=finished_at,
    )


def _step_response(row: AgentStepRow) -> AgentStepResponse:
    return AgentStepResponse(
        step_number=row.step_number,
        observation=row.observation_json or None,
        candidates=list(row.candidates_json or ()),
        chosen_action=row.chosen_action,
        action_args=dict(row.action_args_json or {}),
        confidence=row.confidence,
        probabilities=dict(row.probabilities_json) if row.probabilities_json else None,
        retries=row.retries,
        used_default=row.used_default,
        result=dict(row.result_json or {}),
        latency_ms=row.latency_ms,
        error=row.error,
    )


def _run_response(
    run: AgentRunRow, *, live_recommendation: RecommendationResponse | None = None
) -> AgentRunResponse:
    """The HTTP view of a run.

    `live_recommendation` carries the route of the request being served. The persisted copy has
    none (NFR-06), so a later read returns an empty `route`.
    """
    state = run.state_json or {}
    stored = state.get("_recommendation")
    if live_recommendation is not None:
        recommendation: RecommendationResponse | None = live_recommendation
    elif isinstance(stored, dict):
        recommendation = RecommendationResponse.model_validate({**stored, "route": []})
    else:
        recommendation = None
    return AgentRunResponse(
        run_id=run.id,
        recommendation_id=run.recommendation_id,
        status=run.status,
        policy_name=run.policy_name,
        model_name=run.model_name,
        steps_count=run.steps_count,
        total_latency_ms=run.total_latency_ms,
        buyer_summary=state.get("buyer_summary"),
        pending_question=state.get("pending_question"),
        alternatives_shown=list(state.get("alternatives_shown") or ()),
        mode=str(state.get("mode", "walk")),
        excluded_chains=[str(chain) for chain in state.get("excluded_chains") or ()],
        allowed_chains=[str(chain) for chain in state.get("allowed_chains") or ()],
        max_stores=state.get("max_stores"),
        priority=state.get("priority"),
        recommendation=recommendation,
        steps=[_step_response(step) for step in run.steps],
    )


def _resume_policy(name: str, injected: Policy, settings: Settings) -> Policy:
    """Keep the injected policy when it is the one the run used; rebuild it otherwise."""
    if injected.name == name:
        return injected
    return policy_from_settings(settings, policy_override=name)


def _answer_message(body: AgentAnswerRequest) -> str | None:
    """A shopper-style text for an answer that only carries a structured choice."""
    if body.choice_label:
        return body.choice_label
    if body.option_index is not None:
        return f"Opción {body.option_index + 1}"
    if body.canonical_id is not None:
        return f"Producto {body.canonical_id}"
    return None


def _fresh_start(
    body: AgentRunRequest,
    session: Session,
    routing: RoutingEngine,
    today: date,
    settings: Settings,
) -> tuple[
    RecommendationQuery,
    RecommendationResponse | None,
    AgentState,
    dict[ActionKind, ActionExecutor],
]:
    """Run the pipeline over the request and build the first state with its executors."""
    query = _query_from_request(body.request)
    vague_lines: tuple[dict[str, Any], ...] = ()
    try:
        response, basket = recommend_with_basket(
            session, query, routing, today, settings, persist=False
        )
    except ChoiceRequired as exc:
        # The preprocessor needs the shopper to narrow a vague line first: surface it so the
        # agent can ask, instead of failing the whole run with a 422.
        response, basket = None, None
        zones = {
            store.zone_id for store in candidate_stores(session, query.origin, query.mode, settings)
        }
        vague_lines = (
            {
                "line_id": exc.line_id,
                "category_key": exc.category_key,
                "candidate_options": category_candidate_options(
                    session, exc.category_key, sorted(zones)
                ),
            },
        )
    except UnknownProduct:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Producto desconocido."
        ) from None
    except NoCandidateStores:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NO_STORES
        ) from None
    except RoutingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROUTING_FAILED
        ) from None
    except BasketCalculationError as exc:
        # The message describes the basket, never the origin.
        logger.warning("agent basket calculation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=BASKET_FAILED
        ) from None

    state = state_from_recommendation(
        session,
        query,
        response,
        basket_result=basket,
        vague_lines=vague_lines,
        habits=_habits(body.habits),
        dietary_rules=body.dietary_rules,
        shopper_message=body.shopper_message,
    )
    executors = build_recommender_executors(session, routing, query, today=today, settings=settings)
    return query, response, state, executors


#: Observations that survive into the next turn of a conversation: what the shopper just asked
#: and the lines still waiting for an answer. A missing item or a near tie was settled before.
_CARRIED_OBSERVATIONS = frozenset({ObservationKind.SHOPPER_REQUEST, ObservationKind.VAGUE_LINE})


def _continued(
    session: Session,
    routing: RoutingEngine,
    today: date,
    settings: Settings,
    stored: Mapping[str, Any],
    *,
    origin: GeoPoint,
    message: str | None,
    dietary_rules: Sequence[str] = (),
) -> tuple[RecommendationQuery, AgentState, dict[ActionKind, ActionExecutor]]:
    """Rebuild the cumulative state of a stored run for one more shopper message.

    The stored `_plan_spec` has no origin, so the caller brings the exact one of this request.
    Lines, mode, priority, store limit and chain restrictions are all inherited.
    """
    spec = stored.get("_plan_spec")
    if not isinstance(spec, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este run no guarda un plan que se pueda continuar.",
        )
    try:
        query, items = _query_from_spec(spec, origin)
        state = AgentState.from_dict({k: v for k, v in stored.items() if not k.startswith("_")})
    except KeyError, ValueError, TypeError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El plan guardado de este run no se puede leer.",
        ) from None
    next_index = max((line.index for line in state.lines), default=-1) + 1
    executors = build_recommender_executors(
        session, routing, query, today=today, settings=settings, items=items, next_index=next_index
    )
    state = replace(
        state,
        shopper_message=message,
        pending_question=None,
        status=RunStatus.RUNNING,
        steps_taken=0,
        observations=(),
        alternatives_shown=(),
        dietary_rules=tuple(dietary_rules) or state.dietary_rules,
    )
    observations = detect_observations(state, known_chains=load_known_chains(session))
    state = replace(
        state,
        observations=tuple(o for o in observations if o.kind in _CARRIED_OBSERVATIONS),
    )
    return query, state, executors


@router.post("/agent/runs", response_model=AgentRunResponse)
def create_agent_run(
    body: AgentRunRequest,
    session: Annotated[Session, Depends(get_session)],
    routing: Annotated[RoutingEngine, Depends(get_routing_engine)],
    today: Annotated[date, Depends(get_today)],
    injected_policy: Annotated[Policy, Depends(get_agent_policy)],
) -> AgentRunResponse:
    """Run the pipeline and the agent, persist the trace and return the finished or paused run."""
    settings = get_settings()
    policy = (
        policy_from_settings(settings, policy_override=body.policy)
        if body.policy is not None
        else injected_policy
    )
    if body.recommendation_id is not None:
        exists = session.execute(
            text("select 1 from recommendation where id = :id"),
            {"id": body.recommendation_id},
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Recomendación no encontrada.",
            )
    response: RecommendationResponse | None
    if body.previous_run_id is not None:
        previous = get_run(session, body.previous_run_id)
        if previous is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND)
        query, state, executors = _continued(
            session,
            routing,
            today,
            settings,
            previous.state_json or {},
            origin=GeoPoint(body.request.origin.lat, body.request.origin.lon),
            message=body.shopper_message,
            dietary_rules=body.dietary_rules,
        )
        response = None
    else:
        query, response, state, executors = _fresh_start(body, session, routing, today, settings)
    initial = _plan_key(state)
    result = AgentHarness(_harness_config(settings)).run(state, policy, executors)
    recomputed = last_recommendation(executors)
    # Prefer the fresh recommendation from re-optimization; otherwise return the initial one
    # only if the plan did not change.
    recommendation = (
        recomputed
        if recomputed is not None
        else (response if _plan_key(result.state) == initial else None)
    )
    if (
        recommendation is None
        and body.previous_run_id is not None
        and result.status is RunStatus.COMPLETED
    ):
        # A continued plan that did not change is still served live, with its route.
        recommendation = refresh_recommendation(executors, result.state)
    recommendation_data = (
        _recommendation_payload(recommendation) if recommendation is not None else None
    )
    recommendation_id = body.recommendation_id
    run_id = create_run(
        session,
        agent_name=AGENT_NAME,
        policy_name=result.policy_name,
        model_name=result.model_name,
        recommendation_id=recommendation_id,
        state_json=_state_payload(
            result.state,
            _query_payload(query) if result.status is RunStatus.WAITING_SHOPPER else None,
            recommendation_data,
            _plan_spec(result.state, query, plan_items(executors)),
        ),
        status=result.status.value,
    )
    _persist_steps(session, run_id, result.steps)
    _finish_run(
        session,
        run_id,
        status_value=result.status.value,
        steps_count=len(result.steps),
        total_latency_ms=round(result.total_latency_ms),
    )
    run = get_run(session, run_id)
    if run is None:  # pragma: no cover - the row was just inserted
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _run_response(run, live_recommendation=recommendation)


@router.post("/agent/runs/{run_id}/answer", response_model=AgentRunResponse)
def answer_agent_run(
    run_id: UUID,
    body: AgentAnswerRequest,
    session: Annotated[Session, Depends(get_session)],
    routing: Annotated[RoutingEngine, Depends(get_routing_engine)],
    today: Annotated[date, Depends(get_today)],
    injected_policy: Annotated[Policy, Depends(get_agent_policy)],
) -> AgentRunResponse:
    """Resume a paused run with the shopper's answer and return the updated trace."""
    run = get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found.")
    if run.status != RunStatus.WAITING_SHOPPER.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The agent run is not waiting for an answer.",
        )
    question = (run.state_json or {}).get("pending_question") or {}
    options = question.get("options") or []
    if body.option_index is not None and not 0 <= body.option_index < len(options):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La opción elegida no existe.",
        )
    answer = body.model_dump(exclude_none=True)
    if "message" not in answer:
        message = _answer_message(body)
        if message is not None:
            answer["message"] = message
    return _resume_waiting(run, answer, session, routing, today, injected_policy)


def _resume_waiting(
    run: AgentRunRow,
    answer: dict[str, Any],
    session: Session,
    routing: RoutingEngine,
    today: date,
    injected_policy: Policy,
) -> AgentRunResponse:
    """Resume a run paused on `waiting_shopper` with the shopper's answer."""
    run_id = run.id
    # Claim the run atomically: of two concurrent answers only one may resume it, or both
    # would append steps with the same `(run_id, step_number)`.
    claimed = session.execute(
        text(
            "update agent_run set status = 'running', updated_at = now() "
            "where id = :run_id and status = 'waiting_shopper'"
        ),
        {"run_id": run_id},
    )
    if claimed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The agent run is not waiting for an answer.",
        )
    stored = run.state_json or {}
    query_payload = stored.get("_query")
    if not isinstance(query_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The agent run has no persisted query to resume.",
        )

    settings = get_settings()
    state = AgentState.from_dict(stored)
    base_query = _query_from_payload(query_payload)
    items: dict[int, Item] | None = None
    spec = stored.get("_plan_spec")
    if isinstance(spec, dict):
        # Lines keep their indexes across turns, so the catalog must as well.
        try:
            items = _query_from_spec(spec, base_query.origin)[1]
        except KeyError, ValueError, TypeError:
            items = None
    policy = _resume_policy(run.policy_name, injected_policy, settings)
    executors = build_recommender_executors(
        session,
        routing,
        base_query,
        today=today,
        settings=settings,
        items=items,
        next_index=max((line.index for line in state.lines), default=-1) + 1,
    )

    initial = _plan_key(state)
    result = AgentHarness(_harness_config(settings)).resume(
        state, answer, policy, executors, apply_answer=answer_applier(executors)
    )
    recomputed = last_recommendation(executors)
    if recomputed is not None:
        recommendation_data: dict[str, Any] | None = _recommendation_payload(recomputed)
    elif _plan_key(result.state) == initial and isinstance(stored.get("_recommendation"), dict):
        recommendation_data = stored.get("_recommendation")
    else:
        recommendation_data = None
    state_json = _state_payload(
        result.state,
        query_payload if result.status is RunStatus.WAITING_SHOPPER else None,
        recommendation_data,
        _plan_spec(result.state, base_query, plan_items(executors)),
    )
    update_run(
        session,
        run_id,
        state_json=state_json,
        status=result.status.value,
        steps_count=run.steps_count + len(result.steps),
        total_latency_ms=max(0, run.total_latency_ms + round(result.total_latency_ms)),
        finished_at=(None if result.status is RunStatus.WAITING_SHOPPER else datetime.now(UTC)),
    )
    # The harness numbers from the state's own counter, which a message turn resets.
    offset = max(0, run.steps_count - state.steps_taken)
    _persist_steps(session, run_id, result.steps, offset=offset)
    updated = get_run(session, run_id)
    if updated is None:  # pragma: no cover - the row cannot vanish inside the request
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _run_response(updated, live_recommendation=recomputed)


@router.post("/agent/runs/{run_id}/message", response_model=AgentRunResponse)
def message_agent_run(
    run_id: UUID,
    body: AgentMessageRequest,
    session: Annotated[Session, Depends(get_session)],
    routing: Annotated[RoutingEngine, Depends(get_routing_engine)],
    today: Annotated[date, Depends(get_today)],
    policy: Annotated[Policy, Depends(get_agent_policy)],
) -> AgentRunResponse:
    """Apply one more free-text request ("Pide un cambio") on top of everything asked before.

    The run keeps its lines, mode, priority, store limit and chain restrictions, so changes
    accumulate. A paused run takes the message as the answer to its question; a finished one
    needs the exact `origin` again, because it is never stored once the run completes (NFR-06).
    The response carries the live route; the table never does.
    """
    run = get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND)
    if run.status == RunStatus.WAITING_SHOPPER.value:
        return _resume_waiting(run, {"message": body.message}, session, routing, today, policy)
    if run.status == RunStatus.RUNNING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El run sigue en curso.")
    if body.origin is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Falta el punto de origen (origin) para recalcular el plan.",
        )
    settings = get_settings()
    stored = run.state_json or {}
    query, state, executors = _continued(
        session,
        routing,
        today,
        settings,
        stored,
        origin=GeoPoint(body.origin.lat, body.origin.lon),
        message=body.message,
    )
    # Claim the run, as `/answer` does: two messages at once would number steps twice.
    claimed = session.execute(
        text(
            "update agent_run set status = 'running', updated_at = now() "
            "where id = :run_id and status = :current"
        ),
        {"run_id": run_id, "current": run.status},
    )
    if claimed.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El run sigue en curso.")
    result = AgentHarness(_harness_config(settings)).run(state, policy, executors)
    recommendation = last_recommendation(executors)
    if recommendation is None and result.status is RunStatus.COMPLETED:
        recommendation = refresh_recommendation(executors, result.state)
    _store_turn(session, run, result, query, executors, recommendation)
    updated = get_run(session, run_id)
    if updated is None:  # pragma: no cover - the row cannot vanish inside the request
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _run_response(updated, live_recommendation=recommendation)


def _store_turn(
    session: Session,
    run: AgentRunRow,
    result: RunResult,
    query: RecommendationQuery,
    executors: Mapping[ActionKind, ActionExecutor],
    recommendation: RecommendationResponse | None,
) -> None:
    """Persist one more turn of a run: its state without origin or route, and its steps."""
    waiting = result.status is RunStatus.WAITING_SHOPPER
    update_run(
        session,
        run.id,
        state_json=_state_payload(
            result.state,
            _query_payload(query) if waiting else None,
            _recommendation_payload(recommendation) if recommendation is not None else None,
            _plan_spec(result.state, query, plan_items(executors)),
        ),
        status=result.status.value,
        steps_count=run.steps_count + len(result.steps),
        total_latency_ms=max(0, run.total_latency_ms + round(result.total_latency_ms)),
        finished_at=None if waiting else datetime.now(UTC),
    )
    _persist_steps(session, run.id, result.steps, offset=run.steps_count)


@router.get("/agent/runs/{run_id}", response_model=AgentRunResponse)
def read_agent_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> AgentRunResponse:
    """Return the persisted run and all its steps in order."""
    run = get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found.")
    return _run_response(run)
