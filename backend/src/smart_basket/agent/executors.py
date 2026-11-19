"""Concrete executors for the thirteen agent actions (ADR 0022).

Two backends share the same action logic:

* `build_simulated_executors()` is pure and in-memory. It updates the agent state realistically
  and is used by unit tests and by the offline scenario evaluation (E7).
* `build_recommender_executors(...)` talks to the canonical catalog and the real recommendation
  pipeline: every mutation rebuilds the query and re-runs `recommend_with_basket`, so the plan,
  the lines and the buyer summary always reflect the new request.

Each executor implements the harness contract `propose → validate → apply`: `propose` resolves
the action arguments into a concrete payload, `validate` returns a human-readable problem or
`None`, and `apply` mutates the state only when validation passed. Dietary safety (FR-42) is
enforced in both backends: a substitute that does not declare the required dietary tag is never
proposed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.agent.actions import ActionKind, CandidateAction
from smart_basket.agent.core import ActionExecutor, Proposal
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineHabit,
    LineState,
    PendingQuestion,
    PlanSnapshot,
    RunStatus,
)
from smart_basket.config import Settings, get_settings
from smart_basket.optimizer import PriorityMode, Unit
from smart_basket.recommender.candidates import candidate_stores
from smart_basket.recommender.catalog import Item
from smart_basket.recommender.service import (
    ChoiceRequired,
    RecommendationQuery,
    recommend_with_basket,
)
from smart_basket.routing.base import RoutingEngine, TravelMode

#: Dietary rule → (tag inside `variant_key`, words allowed in the product name).
_DIETARY_TAGS: dict[str, tuple[str, str]] = {
    "sin_gluten": ("sin_gluten", "sin gluten"),
    "sin_lactosa": ("sin_lactosa", "sin lactosa"),
}

_MODES = frozenset({"walk", "car"})


class _Engine(Protocol):
    """What the shared executors need from a backend: state transitions, not presentation."""

    def reoptimize(self, state: AgentState) -> AgentState: ...

    def remove_line(self, state: AgentState, index: int) -> AgentState: ...

    def skip_line(self, state: AgentState, index: int) -> AgentState: ...

    def add_line(
        self, state: AgentState, text: str, quantity: Decimal, unit: str
    ) -> AgentState: ...

    def set_quantity(self, state: AgentState, index: int, quantity: Decimal) -> AgentState: ...

    def set_brand(self, state: AgentState, index: int, brand: str | None) -> AgentState: ...

    def set_mode(self, state: AgentState, mode: str) -> AgentState: ...

    def exclude_chain(self, state: AgentState, chain: str) -> AgentState: ...

    def use_product(
        self,
        state: AgentState,
        index: int,
        product_id: int | None,
        *,
        label: str | None = None,
        canonical_id: int | None = None,
    ) -> AgentState: ...

    def apply_habit(self, state: AgentState, index: int, habit: LineHabit) -> AgentState | None: ...

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]: ...

    def find_substitute(self, state: AgentState, index: int) -> dict[str, Any] | None: ...

    def active_chains(self) -> tuple[str, ...]: ...


class _ExecutorBase:
    """Template for `propose → validate → apply`; subclasses fill the three hooks."""

    def __init__(self, engine: _Engine) -> None:
        self.engine = engine

    def propose(self, state: AgentState, action: CandidateAction) -> Proposal:
        payload, error = self._prepare(state, action)
        if error is not None:
            payload = {**payload, "error": error}
        return Proposal(action=action, summary=action.label, payload=payload)

    def validate(self, state: AgentState, proposal: Proposal) -> str | None:
        error = proposal.payload.get("error")
        return str(error) if error else None

    def apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self._apply(state, proposal)

    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        return {}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return state


class _BuscarSustituto(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        line = _line_at(state, index)
        if line is None:
            return {}, "buscar_sustituto needs an existing line"
        option = self.engine.find_substitute(state, line.index)
        if option is None:
            return {"line_index": line.index}, "no safe substitute for this line"
        return {"line_index": line.index, "option": option}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        option = proposal.payload["option"]
        return self.engine.use_product(
            state,
            int(proposal.payload["line_index"]),
            option.get("product_id"),
            label=option.get("canonical_name") or option.get("name") or option.get("label"),
            canonical_id=option.get("canonical_id"),
        )


class _CambiarModo(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        mode = action.args.get("mode")
        if mode not in _MODES:
            return {"mode": mode}, "mode must be 'walk' or 'car'"
        return {"mode": mode}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.set_mode(state, str(proposal.payload["mode"]))


class _CompararEscenarios(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        mode = action.args.get("mode")
        if mode is None:
            mode = "car" if state.mode == "walk" else "walk"
        if mode not in _MODES:
            return {}, "mode must be 'walk' or 'car'"
        return {"mode": mode}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        mode = str(proposal.payload["mode"])
        updated, shown = self.engine.compare(state, mode)
        return replace(updated, alternatives_shown=(*updated.alternatives_shown, shown))


class _QuitarLinea(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        if _line_at(state, index) is None:
            return {}, "quitar_linea needs an existing line"
        return {"line_index": index}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.remove_line(state, int(proposal.payload["line_index"]))


class _AnadirLinea(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        text_value = str(action.args.get("text") or "").strip()
        if not text_value:
            return {}, "anadir_linea needs the text of the new item"
        quantity = _positive(action.args.get("quantity")) or Decimal(1)
        unit = str(action.args.get("unit") or "ud")
        return {"text": text_value, "quantity": quantity, "unit": unit}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.add_line(
            state,
            str(proposal.payload["text"]),
            Decimal(proposal.payload["quantity"]),
            str(proposal.payload["unit"]),
        )


class _ModificarCantidad(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        if _line_at(state, index) is None:
            return {}, "modificar_cantidad needs an existing line"
        quantity = _positive(action.args.get("quantity"))
        if quantity is None:
            return {"line_index": index}, "quantity must be a positive number"
        return {"line_index": index, "quantity": quantity}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.set_quantity(
            state,
            int(proposal.payload["line_index"]),
            Decimal(proposal.payload["quantity"]),
        )


class _CambiarMarca(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        if _line_at(state, index) is None:
            return {}, "cambiar_marca needs an existing line"
        brand = action.args.get("brand")
        if brand is not None:
            brand = str(brand).strip() or None
        return {"line_index": index, "brand": brand}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.set_brand(
            state, int(proposal.payload["line_index"]), proposal.payload.get("brand")
        )


class _ExcluirCadena(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        chain = str(action.args.get("chain") or "").strip()
        if not chain:
            return {}, "excluir_cadena needs a chain"
        active = self.engine.active_chains()
        if chain not in active:
            return {"chain": chain}, f"unknown chain {chain!r}"
        remaining = [code for code in active if code != chain]
        if not remaining:
            return {"chain": chain}, "every chain would be excluded"
        return {"chain": chain}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.exclude_chain(state, str(proposal.payload["chain"]))


class _AplicarHabitual(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        line = _line_at(state, index)
        if line is None:
            return {}, "aplicar_habitual needs an existing line"
        if line.habit is None:
            return {"line_index": line.index}, "the line has no known habit"
        return {"line_index": line.index, "habit": line.habit}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        habit: LineHabit = proposal.payload["habit"]
        updated = self.engine.apply_habit(state, int(proposal.payload["line_index"]), habit)
        if updated is None:
            raise ValueError("no available product for the habitual choice")
        return updated


class _Preguntar(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        line = _line_at(state, index)
        options = action.args.get("options")
        if options is None and line is not None:
            options = list(line.candidate_options)
        return {
            "line_index": line.index if line is not None else None,
            "options": tuple(dict(option) for option in options or ()),
        }, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return replace(
            state,
            pending_question=PendingQuestion(
                line_index=proposal.payload["line_index"],
                prompt="El agente necesita tu ayuda para elegir esta línea.",
                options=tuple(proposal.payload.get("options") or ()),
            ),
            status=RunStatus.WAITING_SHOPPER,
        )


class _DejarSinComprar(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        if _line_at(state, index) is None:
            return {}, "dejar_sin_comprar needs an existing line"
        return {"line_index": index}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return self.engine.skip_line(state, int(proposal.payload["line_index"]))


class _Explicar(_ExecutorBase):
    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return state


class _NoHacerNada(_ExecutorBase):
    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return state


_EXECUTOR_TYPES: dict[ActionKind, type[_ExecutorBase]] = {
    ActionKind.BUSCAR_SUSTITUTO: _BuscarSustituto,
    ActionKind.CAMBIAR_MODO: _CambiarModo,
    ActionKind.COMPARAR_ESCENARIOS: _CompararEscenarios,
    ActionKind.QUITAR_LINEA: _QuitarLinea,
    ActionKind.ANADIR_LINEA: _AnadirLinea,
    ActionKind.MODIFICAR_CANTIDAD: _ModificarCantidad,
    ActionKind.CAMBIAR_MARCA: _CambiarMarca,
    ActionKind.EXCLUIR_CADENA: _ExcluirCadena,
    ActionKind.APLICAR_HABITUAL: _AplicarHabitual,
    ActionKind.PREGUNTAR: _Preguntar,
    ActionKind.DEJAR_SIN_COMPRAR: _DejarSinComprar,
    ActionKind.EXPLICAR: _Explicar,
    ActionKind.NO_HACER_NADA: _NoHacerNada,
}


def build_simulated_executors(
    *, chains: Sequence[str] = ("mercadona", "carrefour", "dia", "lidl")
) -> dict[ActionKind, ActionExecutor]:
    """Pure in-memory executors: no database, no network, used by tests and offline evaluation."""
    engine = _SimulatedEngine(chains=chains)
    return {kind: executor_type(engine) for kind, executor_type in _EXECUTOR_TYPES.items()}


def build_recommender_executors(
    session: Session,
    routing: RoutingEngine,
    base_query: RecommendationQuery,
    *,
    today: date,
    settings: Settings | None = None,
) -> dict[ActionKind, ActionExecutor]:
    """DB-backed executors that re-run the real pipeline after every mutation."""
    engine = _RecommenderEngine(
        session, routing, base_query, today=today, settings=settings or get_settings()
    )
    return {kind: executor_type(engine) for kind, executor_type in _EXECUTOR_TYPES.items()}


# -- simulated backend ----------------------------------------------------


class _SimulatedEngine:
    """In-memory transitions: lines and mode change, figures stay as the scenario wrote them."""

    def __init__(self, *, chains: Sequence[str]) -> None:
        self._chains = tuple(chains)

    def reoptimize(self, state: AgentState) -> AgentState:
        return replace(state, status=RunStatus.RUNNING)

    def remove_line(self, state: AgentState, index: int) -> AgentState:
        return self.reoptimize(_drop(state, index))

    def skip_line(self, state: AgentState, index: int) -> AgentState:
        return self.reoptimize(_update(state, index, status="skipped"))

    def add_line(
        self, state: AgentState, text_value: str, quantity: Decimal, unit: str
    ) -> AgentState:
        index = _next_index(state)
        line = LineState(index=index, raw_text=text_value, quantity=quantity, unit=unit)
        return self.reoptimize(replace(state, lines=(*state.lines, line)))

    def set_quantity(self, state: AgentState, index: int, quantity: Decimal) -> AgentState:
        return self.reoptimize(_update(state, index, quantity=quantity))

    def set_brand(self, state: AgentState, index: int, brand: str | None) -> AgentState:
        return self.reoptimize(_update(state, index, brand=brand, brand_pinned=brand is not None))

    def set_mode(self, state: AgentState, mode: str) -> AgentState:
        return self.reoptimize(replace(state, mode=mode))

    def exclude_chain(self, state: AgentState, chain: str) -> AgentState:
        chains = state.excluded_chains
        if chain not in chains:
            chains = (*chains, chain)
        return self.reoptimize(replace(state, excluded_chains=chains))

    def use_product(
        self,
        state: AgentState,
        index: int,
        product_id: int | None,
        *,
        label: str | None = None,
        canonical_id: int | None = None,
    ) -> AgentState:
        return self.reoptimize(
            _update(
                state,
                index,
                status="ok",
                canonical_id=canonical_id,
                canonical_name=label,
            )
        )

    def apply_habit(self, state: AgentState, index: int, habit: LineHabit) -> AgentState:
        return self.reoptimize(
            _update(
                state,
                index,
                status="ok",
                canonical_id=habit.canonical_id,
                canonical_name=habit.canonical_name,
            )
        )

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]:
        shown = {
            "mode": mode,
            "store_names": list(state.plan.store_names),
            "total_cost": str(state.plan.total_cost),
            "travel_minutes": str(state.plan.travel_minutes),
            "cost_delta": "0",
            "minutes_delta": "0",
        }
        return state, shown

    def find_substitute(self, state: AgentState, index: int) -> dict[str, Any] | None:
        line = _line_at(state, index)
        if line is None:
            return None
        for option in line.substitute_options:
            if _option_is_safe(option, state.dietary_rules):
                return dict(option)
        return None

    def active_chains(self) -> tuple[str, ...]:
        return self._chains


# -- recommender backend --------------------------------------------------


class _RecommenderEngine:
    """Catalog + optimizer backend: every mutation rebuilds the query and re-optimizes."""

    def __init__(
        self,
        session: Session,
        routing: RoutingEngine,
        base_query: RecommendationQuery,
        *,
        today: date,
        settings: Settings,
    ) -> None:
        self.session = session
        self.routing = routing
        self.base_query = base_query
        self.today = today
        self.settings = settings
        self._items: dict[int, Item] = dict(enumerate(base_query.items))
        self._next = (max(self._items) + 1) if self._items else 0
        self._excluded: list[str] = []

    def reoptimize(self, state: AgentState) -> AgentState:
        return self._reoptimize(state)

    def remove_line(self, state: AgentState, index: int) -> AgentState:
        self._items.pop(index, None)
        return self._reoptimize(_drop(state, index))

    def skip_line(self, state: AgentState, index: int) -> AgentState:
        self._items.pop(index, None)
        return self._reoptimize(_update(state, index, status="skipped"))

    def add_line(
        self, state: AgentState, text_value: str, quantity: Decimal, unit: str
    ) -> AgentState:
        index = self._next
        self._next += 1
        category_key = self._category_for_text(text_value)
        self._items[index] = Item(
            text=text_value,
            category_key=category_key,
            quantity=quantity,
            unit=_unit(unit),
        )
        line = LineState(index=index, raw_text=text_value, quantity=quantity, unit=unit)
        return self._reoptimize(replace(state, lines=(*state.lines, line)))

    def set_quantity(self, state: AgentState, index: int, quantity: Decimal) -> AgentState:
        item = self._items.get(index)
        if item is not None:
            self._items[index] = replace(item, quantity=quantity)
        return self._reoptimize(_update(state, index, quantity=quantity))

    def set_brand(self, state: AgentState, index: int, brand: str | None) -> AgentState:
        item = self._items.get(index)
        if item is not None:
            self._items[index] = replace(item, brand=brand)
        return self._reoptimize(_update(state, index, brand=brand, brand_pinned=brand is not None))

    def set_mode(self, state: AgentState, mode: str) -> AgentState:
        return self._reoptimize(state, mode=mode)

    def exclude_chain(self, state: AgentState, chain: str) -> AgentState:
        if chain not in self._excluded:
            self._excluded.append(chain)
        chains = state.excluded_chains
        if chain not in chains:
            chains = (*chains, chain)
        return self._reoptimize(replace(state, excluded_chains=chains))

    def use_product(
        self,
        state: AgentState,
        index: int,
        product_id: int | None,
        *,
        label: str | None = None,
        canonical_id: int | None = None,
    ) -> AgentState:
        if product_id is not None:
            item = self._items.get(index)
            if item is not None:
                self._items[index] = replace(
                    item, category_key=None, product_id=product_id, accept="equivalent"
                )
            state = _update(state, index, status="ok")
        return self._reoptimize(state)

    def apply_habit(self, state: AgentState, index: int, habit: LineHabit) -> AgentState | None:
        product = self._product_for_canonical(habit.canonical_id, state)
        if product is None:
            return None
        return self.use_product(
            state,
            index,
            product["product_id"],
            label=habit.canonical_name,
            canonical_id=habit.canonical_id,
        )

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]:
        query, _ = self._query_for(state, mode=mode, max_alternatives=0)
        response, basket = recommend_with_basket(
            self.session, query, self.routing, self.today, self.settings
        )
        shown = {
            "mode": mode,
            "store_names": [store.name for store in response.stores],
            "total_cost": str(basket.total_cost),
            "travel_minutes": str(basket.minutes),
            "cost_delta": str(basket.total_cost - state.plan.total_cost),
            "minutes_delta": str(basket.minutes - state.plan.travel_minutes),
        }
        return state, shown

    def find_substitute(self, state: AgentState, index: int) -> dict[str, Any] | None:
        category = self._line_category(index)
        if category is None:
            return None
        category_id, parent_id = category
        ancestor = parent_id if parent_id is not None else category_id
        own = self._own_canonical(index)
        siblings = self.session.execute(
            text(
                "select cp.id as canonical_id, cp.name, cp.variant_key "
                "from canonical_product cp "
                "join category_closure cc on cc.descendant_id = cp.category_id "
                "where cc.ancestor_id = :ancestor and cp.id <> :own "
                "order by cp.id"
            ),
            {"ancestor": ancestor, "own": own if own is not None else -1},
        ).mappings()
        canonical_ids = [row["canonical_id"] for row in siblings]
        if not canonical_ids:
            return None
        zones = self._planned_zones(state)
        if not zones:
            return None
        products = self.session.execute(
            text(
                "select p.id as product_id, p.name, canon.id as canonical_id, "
                "canon.name as canonical_name, canon.variant_key, pc.price "
                "from chain_product p "
                "join canonical_product canon on canon.id = p.canonical_id "
                "join chain_product_zone pz "
                "  on pz.chain_product_id = p.id and pz.is_available "
                "join price_current pc "
                "  on pc.chain_product_id = p.id and pc.zone_id = pz.zone_id "
                "where p.canonical_id in :canonicals and p.is_active "
                "  and pz.zone_id in :zones "
                "order by canon.id, pc.price, p.id"
            ).bindparams(
                bindparam("canonicals", expanding=True), bindparam("zones", expanding=True)
            ),
            {"canonicals": sorted(canonical_ids), "zones": sorted(zones)},
        ).mappings()
        for row in products:
            if _dietary_ok(row["variant_key"], row["name"], state.dietary_rules):
                return {
                    "product_id": row["product_id"],
                    "canonical_id": row["canonical_id"],
                    "canonical_name": row["canonical_name"],
                    "name": row["name"],
                    "variant_key": row["variant_key"],
                    "price": str(row["price"]),
                }
        return None

    def active_chains(self) -> tuple[str, ...]:
        rows = self.session.execute(text("select code from chain order by code")).scalars()
        return tuple(rows)

    # -- pipeline -------------------------------------------------------

    def _reoptimize(self, state: AgentState, *, mode: str | None = None) -> AgentState:
        query, positions = self._query_for(state, mode=mode)
        try:
            response, basket = recommend_with_basket(
                self.session, query, self.routing, self.today, self.settings
            )
        except ChoiceRequired as exc:
            index = positions.get(exc.line_id)
            if index is None:
                raise
            vague = _update(state, index, status="vague")
            return self._reoptimize(vague, mode=mode)
        return self._state_from_result(state, query, response, basket, positions)

    def _query_for(
        self,
        state: AgentState,
        *,
        mode: str | None = None,
        max_alternatives: int = 2,
    ) -> tuple[RecommendationQuery, dict[int, int]]:
        items: list[Item] = []
        positions: dict[int, int] = {}
        for line in state.lines:
            if line.status in {"vague", "skipped"} or line.index not in self._items:
                continue
            base = self._items[line.index]
            items.append(replace(base, quantity=line.quantity, unit=_unit(line.unit)))
            positions[len(items) - 1] = line.index
        active = self.active_chains()
        excluded = set(self._excluded) | set(state.excluded_chains)
        remaining = tuple(code for code in active if code not in excluded)
        chains = remaining if excluded else ()
        query = RecommendationQuery(
            items=tuple(items),
            origin=self.base_query.origin,
            mode=TravelMode(mode or state.mode),
            max_stores=self.base_query.max_stores,
            priority_mode=PriorityMode(state.priority),
            return_to_origin=self.base_query.return_to_origin,
            degraded=self.base_query.degraded,
            payload=dict(self.base_query.payload),
            chains=chains,
            max_alternatives=max_alternatives,
        )
        return query, positions

    def _state_from_result(
        self,
        state: AgentState,
        query: RecommendationQuery,
        response: Any,
        basket: Any,
        positions: Mapping[int, int],
    ) -> AgentState:
        by_index = {line_index: position for position, line_index in positions.items()}
        bought = {line.line_id: line for store in response.stores for line in store.lines}
        reasons = {line.line_id: line.reason for line in response.missing}
        lines: list[LineState] = []
        for line in state.lines:
            position = by_index.get(line.index)
            if position is None:
                lines.append(line)
                continue
            product = bought.get(position)
            if product is not None:
                lines.append(
                    replace(
                        line,
                        status="ok",
                        canonical_id=product.canonical_id,
                        canonical_name=product.product_name,
                        brand=product.brand,
                        exact_only=product.exact_only,
                    )
                )
                continue
            if reasons.get(position) == "not_available":
                lines.append(replace(line, status="missing"))
            else:
                lines.append(replace(line, status=line.status))
        plan = PlanSnapshot(
            store_names=tuple(store.name for store in response.stores),
            total_cost=basket.total_cost,
            travel_minutes=basket.minutes,
            comparable_cost=basket.comparable_cost,
            alternatives=tuple(
                _alternative(session=self.session, item=item) for item in basket.alternatives
            ),
        )
        return replace(
            state,
            lines=tuple(lines),
            mode=query.mode.value,
            priority=query.priority_mode.value,
            plan=plan,
            buyer_summary=response.explanation,
            status=RunStatus.RUNNING,
        )

    # -- catalog helpers -------------------------------------------------

    def _category_for_text(self, value: str) -> str | None:
        row = (
            self.session.execute(
                text(
                    "select key from category "
                    "where lower(name) = lower(:text) or lower(key) = lower(:text) "
                    "order by level desc, id limit 1"
                ),
                {"text": value.strip()},
            )
            .scalars()
            .first()
        )
        if row is not None:
            return str(row)
        row = (
            self.session.execute(
                text(
                    "select key from category where lower(:text) like '%' || lower(name) || '%' "
                    "order by level desc, length(name) desc, id limit 1"
                ),
                {"text": value.strip()},
            )
            .scalars()
            .first()
        )
        return str(row) if row is not None else None

    def _line_category(self, index: int) -> tuple[int, int | None] | None:
        item = self._items.get(index)
        if item is not None and item.category_key:
            row = (
                self.session.execute(
                    text("select id, parent_id from category where key = :key"),
                    {"key": item.category_key},
                )
                .mappings()
                .first()
            )
            if row is not None:
                return int(row["id"]), row["parent_id"]
        canonical = self._own_canonical(index)
        if canonical is None:
            return None
        row = (
            self.session.execute(
                text(
                    "select c.id, c.parent_id from canonical_product cp "
                    "join category c on c.id = cp.category_id where cp.id = :id"
                ),
                {"id": canonical},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return int(row["id"]), row["parent_id"]

    def _own_canonical(self, index: int) -> int | None:
        item = self._items.get(index)
        if item is not None and item.product_id is not None:
            value = self.session.execute(
                text("select canonical_id from chain_product where id = :id"),
                {"id": item.product_id},
            ).scalar_one_or_none()
            if value is not None:
                return int(value)
        return None

    def _planned_zones(self, state: AgentState) -> tuple[int, ...]:
        names = [name for name in state.plan.store_names if name]
        if names:
            rows = self.session.execute(
                text(
                    "select distinct zone_id from store "
                    "where name in :names and zone_id is not null"
                ).bindparams(bindparam("names", expanding=True)),
                {"names": sorted(set(names))},
            ).scalars()
            zones = tuple(sorted({int(zone) for zone in rows}))
            if zones:
                return zones
        stores = candidate_stores(
            self.session, self.base_query.origin, TravelMode(state.mode), self.settings
        )
        return tuple(sorted({store.zone_id for store in stores}))

    def _product_for_canonical(
        self, canonical_id: int | None, state: AgentState
    ) -> dict[str, Any] | None:
        if canonical_id is None:
            return None
        zones = self._planned_zones(state)
        if not zones:
            return None
        row = (
            self.session.execute(
                text(
                    "select p.id as product_id, canon.name as canonical_name "
                    "from chain_product p "
                    "join canonical_product canon on canon.id = p.canonical_id "
                    "join chain_product_zone pz "
                    "  on pz.chain_product_id = p.id and pz.is_available "
                    "join price_current pc "
                    "  on pc.chain_product_id = p.id and pc.zone_id = pz.zone_id "
                    "where p.canonical_id = :canonical and p.is_active "
                    "  and pz.zone_id in :zones "
                    "order by pc.price, p.id limit 1"
                ).bindparams(bindparam("zones", expanding=True)),
                {"canonical": canonical_id, "zones": sorted(zones)},
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None


# -- shared helpers -------------------------------------------------------


def _line_at(state: AgentState, index: int | None) -> LineState | None:
    if index is None:
        return None
    return next((line for line in state.lines if line.index == index), None)


def _int_arg(action: CandidateAction, key: str) -> int | None:
    value = action.args.get(key)
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _positive(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        quantity = Decimal(str(value))
    except InvalidOperation, ValueError:
        return None
    if not quantity.is_finite() or quantity <= 0:
        return None
    return quantity


def _unit(value: Any) -> Unit:
    try:
        return Unit(str(value))
    except ValueError:
        return Unit.UD


def _next_index(state: AgentState) -> int:
    return max((line.index for line in state.lines), default=-1) + 1


def _update(state: AgentState, index: int, **changes: Any) -> AgentState:
    lines = tuple(replace(line, **changes) if line.index == index else line for line in state.lines)
    return replace(state, lines=lines)


def _drop(state: AgentState, index: int) -> AgentState:
    lines = tuple(line for line in state.lines if line.index != index)
    return replace(state, lines=lines)


def _option_is_safe(option: Mapping[str, Any], dietary_rules: Sequence[str]) -> bool:
    variant = str(option.get("variant_key") or "")
    name = str(option.get("name") or option.get("label") or "")
    return _dietary_ok(variant, name, dietary_rules)


def _dietary_ok(variant_key: str | None, name: str | None, dietary_rules: Sequence[str]) -> bool:
    if not dietary_rules:
        return True
    haystack = f"{variant_key or ''} {name or ''}".lower()
    for rule in dietary_rules:
        tags = _DIETARY_TAGS.get(rule.lower())
        if tags is None:
            continue
        tag, words = tags
        if tag not in haystack and words not in haystack:
            return False
    return True


def _alternative(*, session: Session, item: Any) -> AlternativePlanSummary:
    names = _store_names(session, item.plan.visiting_order)
    return AlternativePlanSummary(
        store_names=names,
        total_cost=item.plan.total_cost,
        travel_minutes=item.plan.minutes,
        objective_delta=item.objective_delta,
    )


def _store_names(session: Session, store_ids: Sequence[int]) -> tuple[str, ...]:
    if not store_ids:
        return ()
    rows = session.execute(
        text("select id, name from store where id in :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": list(store_ids)},
    ).mappings()
    by_id = {row["id"]: row["name"] for row in rows}
    return tuple(by_id.get(store_id, f"tienda {store_id}") for store_id in store_ids)
