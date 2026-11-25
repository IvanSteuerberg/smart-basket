"""Concrete executors for the seventeen agent actions (ADR 0022).

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

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.agent.actions import ActionKind, CandidateAction
from smart_basket.agent.core import ActionExecutor, Proposal
from smart_basket.agent.detector import (
    KnownChains,
    alternative_reason,
    build_known_chains,
    detect_observations,
    load_known_chains,
    plan_snapshot_from_result,
    same_chains,
)
from smart_basket.agent.observations import ObservationKind
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineHabit,
    LineState,
    PendingQuestion,
    RunStatus,
)
from smart_basket.config import Settings, get_settings
from smart_basket.optimizer import BasketResult, PriorityMode, Unit
from smart_basket.recommender.candidates import candidate_stores
from smart_basket.recommender.catalog import Item
from smart_basket.recommender.service import (
    BasketCalculationError,
    ChoiceRequired,
    MissingResponse,
    NoCandidateStores,
    RecommendationQuery,
    RecommendationResponse,
    recommend_with_basket,
)
from smart_basket.routing import RoutingError
from smart_basket.routing.base import RoutingEngine, TravelMode

#: Dietary rule → (token expected in `variant_key`, phrase a label must declare instead).
#: The token is matched exactly against the `|`-separated variant keys; the phrase is only a
#: fallback for simulated substitutes that carry no `variant_key` at all (frozen scenarios).
_DIETARY_TAGS: dict[str, tuple[str, str]] = {
    "sin_gluten": ("sin_gluten", "sin gluten"),
    "sin_lactosa": ("sin_lactosa", "sin lactosa"),
}

#: Words that turn a declarative label into a warning or a negation: never a safe substitute.
_DIETARY_NEGATIONS = ("con gluten", "con lactosa", "puede contener", "trazas", "no sin")

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

    def habit_problem(self, state: AgentState, habit: LineHabit) -> str | None: ...

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]: ...

    def find_substitute(self, state: AgentState, index: int) -> dict[str, Any] | None: ...

    def active_chains(self) -> tuple[str, ...]: ...

    def line_options(
        self, state: AgentState, line: LineState, kind: str, limit: int
    ) -> list[dict[str, Any]]: ...

    def product_for_canonical(
        self, canonical_id: int | None, state: AgentState
    ) -> dict[str, Any] | None: ...

    def restrict_chains(self, state: AgentState, keep: Sequence[str]) -> AgentState: ...

    def set_category(self, state: AgentState, index: int, category_key: str) -> AgentState: ...

    def category_for_text(self, value: str) -> str | None: ...

    def canonical_for_text(self, value: str) -> dict[str, Any] | None: ...

    def filter_chains(self, state: AgentState, chains: Sequence[str]) -> AgentState: ...

    def set_max_stores(self, state: AgentState, max_stores: int) -> AgentState: ...

    def set_priority(self, state: AgentState, priority: str) -> AgentState: ...

    def replacement_problem(self, state: AgentState, index: int, text: str) -> str | None: ...

    def replace_product(self, state: AgentState, index: int, text: str) -> AgentState: ...

    def known_chains(self) -> KnownChains: ...

    def chain_label(self, code: str) -> str: ...


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
        mode = str(proposal.payload["mode"])
        updated = self.engine.set_mode(state, mode)
        where = "coche" if mode == "car" else "pie"
        return _confirmed(updated, f"He cambiado el desplazamiento a {where}.")


class _CompararEscenarios(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        mode = action.args.get("mode")
        if mode is None and "line_index" not in action.args and _real_alternatives(state):
            # A near tie: show the real plans on the table instead of repeating the mode.
            return {"plans": True}, None
        if mode is None:
            mode = "car" if state.mode == "walk" else "walk"
        if mode not in _MODES:
            return {}, "mode must be 'walk' or 'car'"
        return {"mode": mode}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        if proposal.payload.get("plans"):
            shown = tuple(
                {
                    "mode": state.mode,
                    "store_names": list(alt.store_names),
                    "chain_codes": list(alt.chain_codes),
                    "total_cost": str(alt.total_cost),
                    "travel_minutes": str(alt.travel_minutes),
                    "cost_delta": str(alt.cost_delta if alt.cost_delta is not None else 0),
                    "minutes_delta": str(alt.minutes_delta if alt.minutes_delta is not None else 0),
                    "reason": alt.reason,
                }
                for alt in _real_alternatives(state)
            )
            return replace(state, alternatives_shown=(*state.alternatives_shown, *shown))
        mode = str(proposal.payload["mode"])
        updated, shown = self.engine.compare(state, mode)
        return replace(updated, alternatives_shown=(*updated.alternatives_shown, shown))


class _QuitarLinea(_ExecutorBase):
    """Removes one line (`line_index`) or several at once (`line_indices`)."""

    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        raw = action.args.get("line_indices")
        if isinstance(raw, Sequence) and not isinstance(raw, str) and raw:
            indices = [_as_int(value) for value in raw]
        else:
            indices = [_int_arg(action, "line_index")]
        wanted = list(dict.fromkeys(indices))
        lines = [_line_at(state, index) for index in wanted]
        if any(line is None for line in lines):
            return {}, "quitar_linea needs an existing line"
        return {
            "line_indices": wanted,
            "line_index": wanted[0],
            "names": [line.raw_text for line in lines if line is not None],
        }, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        for index in proposal.payload["line_indices"]:
            state = self.engine.remove_line(state, int(index))
        names = " y ".join(f"«{name}»" for name in proposal.payload["names"])
        return _confirmed(state, f"He quitado {names} de la lista.")


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
        updated = self.engine.add_line(
            state,
            str(proposal.payload["text"]),
            Decimal(proposal.payload["quantity"]),
            str(proposal.payload["unit"]),
        )
        return _confirmed(updated, f"He añadido «{proposal.payload['text']}» a la lista.")


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
        index = int(proposal.payload["line_index"])
        quantity = Decimal(proposal.payload["quantity"])
        name = _line_name(state, index)
        updated = self.engine.set_quantity(state, index, quantity)
        return _confirmed(
            updated, f"He cambiado la cantidad de «{name}» a {quantity.normalize():f}."
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
        index = int(proposal.payload["line_index"])
        brand = proposal.payload.get("brand")
        name = _line_name(state, index)
        updated = self.engine.set_brand(state, index, brand)
        sentence = (
            f"He fijado la marca «{brand}» para «{name}»."
            if brand
            else f"He dejado «{name}» sin marca fija."
        )
        return _confirmed(updated, sentence)


class _ExcluirCadena(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        chain = str(action.args.get("chain") or "").strip().lower()
        if not chain:
            return {}, "excluir_cadena needs a chain"
        active = self.engine.active_chains()
        if chain not in {code.lower() for code in active}:
            return {"chain": chain}, f"unknown chain {chain!r}"
        already = {code.lower() for code in state.excluded_chains}
        if chain in already:
            return {"chain": chain}, f"la cadena {chain!r} ya está excluida"
        allowed = {code.lower() for code in state.allowed_chains}
        remaining = [
            code
            for code in active
            if code.lower() not in (already | {chain}) and (not allowed or code.lower() in allowed)
        ]
        if not remaining:
            return {"chain": chain}, "no quedaría ninguna cadena activa si se excluye esa cadena"
        return {"chain": chain}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        chain = str(proposal.payload["chain"])
        updated = self.engine.exclude_chain(state, chain)
        return _confirmed(updated, f"He excluido {self.engine.chain_label(chain)} del plan.")


class _FiltrarCadena(_ExecutorBase):
    """Restricts the plan to the chains the shopper names ("solo en Dia")."""

    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        raw = action.args.get("chains")
        if raw is None and action.args.get("chain"):
            raw = [action.args["chain"]]
        wanted = [str(code).strip().lower() for code in raw or () if str(code).strip()]
        if not wanted:
            return {}, "filtrar_cadena needs at least one chain"
        active = {code.lower(): code for code in self.engine.active_chains()}
        unknown = [code for code in wanted if code not in active]
        if unknown:
            return {"chains": wanted}, f"unknown chain {unknown[0]!r}"
        chains = list(dict.fromkeys(wanted))
        if tuple(chains) == tuple(code.lower() for code in state.allowed_chains):
            return {"chains": chains}, "el plan ya está limitado a esas cadenas"
        return {"chains": chains}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        chains = [str(code) for code in proposal.payload["chains"]]
        updated = self.engine.filter_chains(state, chains)
        shown = " y ".join(self.engine.chain_label(code) for code in chains)
        return _confirmed(updated, f"He limitado el plan a solo en {shown}.")


class _CambiarMaxTiendas(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        value = _as_int(action.args.get("max_stores"))
        if value is None or not 1 <= value <= 3:
            return {"max_stores": value}, "max_stores must be an integer between 1 and 3"
        if value == state.max_stores:
            return {"max_stores": value}, f"el plan ya admite como máximo {value} tienda(s)"
        return {"max_stores": value}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        value = int(proposal.payload["max_stores"])
        updated = self.engine.set_max_stores(state, value)
        shown = "1 tienda" if value == 1 else f"{value} tiendas"
        return _confirmed(updated, f"He limitado la compra a {shown}.")


_PRIORITY_SENTENCE = {
    "savings": "ahorrar",
    "balanced": "un plan equilibrado",
    "time": "ahorrar tiempo",
}


class _CambiarPrioridad(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        priority = str(action.args.get("priority") or "").strip().lower()
        if priority not in _PRIORITY_SENTENCE:
            return {"priority": priority}, "priority must be 'savings', 'balanced' or 'time'"
        if priority == state.priority:
            return {"priority": priority}, f"la prioridad ya es {priority!r}"
        return {"priority": priority}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        priority = str(proposal.payload["priority"])
        updated = self.engine.set_priority(state, priority)
        return _confirmed(updated, f"He cambiado la prioridad a {_PRIORITY_SENTENCE[priority]}.")


class _CambiarProducto(_ExecutorBase):
    """Replaces what a line asks for by another product, never against dietary rules (FR-42)."""

    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        line = _line_at(state, index)
        if line is None:
            return {}, "cambiar_producto needs an existing line"
        new_text = " ".join(str(action.args.get("text") or "").split())
        if not new_text:
            return {"line_index": index}, "cambiar_producto needs the text of the new product"
        payload = {"line_index": line.index, "text": new_text, "previous": line.raw_text}
        problem = self.engine.replacement_problem(state, line.index, new_text)
        return payload, problem

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        index = int(proposal.payload["line_index"])
        new_text = str(proposal.payload["text"])
        updated = self.engine.replace_product(state, index, new_text)
        return _confirmed(
            updated, f"He cambiado «{proposal.payload['previous']}» por «{new_text}»."
        )


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
        payload = {"line_index": line.index, "habit": line.habit}
        problem = self.engine.habit_problem(state, line.habit)
        if problem is not None:
            return payload, problem
        return payload, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        habit: LineHabit = proposal.payload["habit"]
        updated = self.engine.apply_habit(state, int(proposal.payload["line_index"]), habit)
        # Validation already proved the canonical product is on offer; keep the state intact
        # instead of raising if the catalog changed under us.
        return state if updated is None else updated


_SKIP_OPTION: dict[str, Any] = {"label": "Dejar sin comprar", "action": "skip"}


class _Preguntar(_ExecutorBase):
    """Leaves the shopper a concrete question: what is wrong and which options solve it."""

    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        line = _line_at(state, index)
        given = action.args.get("options")
        options = [dict(option) for option in given or ()]
        prompt: str | None = None
        if line is not None and line.status == "vague":
            options = options or [dict(o) for o in line.candidate_options]
            options = options or self.engine.line_options(state, line, "vague", 6)
            prompt = f"¿Qué tipo de «{line.raw_text}» prefieres?"
            options = _with_skip(options)
        elif line is not None and line.status == "missing":
            options = options or [dict(o) for o in line.substitute_options]
            options = options or self.engine.line_options(state, line, "missing", 4)
            prompt = (
                f"«{line.raw_text}» no está disponible en tiendas cercanas. ¿Qué prefieres hacer?"
            )
            options = _with_skip(options)
        elif line is not None:
            options = options or [dict(o) for o in line.candidate_options]
            prompt = f"¿Cuál prefieres para «{line.raw_text}»?" if options else None
        else:
            tie = _tie_question(state)
            if tie is not None:
                prompt, options = tie
            elif state.shopper_message and state.shopper_message.strip():
                prompt = (
                    f"No estoy seguro de cómo aplicar «{state.shopper_message.strip()}». "
                    "¿Puedes concretarlo?"
                )
        return {
            "line_index": line.index if line is not None else None,
            "options": tuple(options),
            "prompt": prompt,
        }, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        # A paused run always carries a question: without a specific prompt, a generic one.
        prompt = proposal.payload.get("prompt") or _FALLBACK_PROMPT
        question = PendingQuestion(
            line_index=proposal.payload["line_index"],
            prompt=str(prompt),
            options=tuple(proposal.payload.get("options") or ()),
        )
        return replace(state, pending_question=question, status=RunStatus.WAITING_SHOPPER)


_FALLBACK_PROMPT = (
    "Necesito que me concretes qué quieres hacer. ¿Puedes explicarlo con otras palabras?"
)


def _with_skip(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(option.get("action") == "skip" for option in options):
        return options
    return [*options, dict(_SKIP_OPTION)]


def _real_alternatives(state: AgentState) -> tuple[AlternativePlanSummary, ...]:
    """Alternatives that visit other chains than the current plan (the only real choices)."""
    return tuple(
        alt
        for alt in state.plan.alternatives
        if not same_chains(state.plan.chain_codes, state.plan.store_names, alt)
    )


def _tie_question(state: AgentState) -> tuple[str, list[dict[str, Any]]] | None:
    alternatives = _real_alternatives(state)
    if not alternatives:
        return None
    plan = state.plan
    current = " + ".join(plan.store_names) if plan.store_names else "el plan actual"
    prompt = (
        f"Hay opciones muy parecidas a {current} "
        f"({plan.total_cost} €, {plan.travel_minutes} min). ¿Cuál prefieres?"
    )
    options: list[dict[str, Any]] = [
        {"label": f"Mantener {current} ({plan.total_cost} €)", "action": "keep_plan"}
    ]
    for alt in alternatives:
        names = " + ".join(alt.store_names)
        label = f"{names} ({alt.total_cost} €, {alt.travel_minutes} min)"
        if alt.reason:
            label += f" · {alt.reason}"
        options.append(
            {
                "label": label,
                "action": "select_alternative",
                "chain_codes": list(alt.chain_codes),
                "store_names": list(alt.store_names),
            }
        )
    return prompt, options


class _DejarSinComprar(_ExecutorBase):
    def _prepare(
        self, state: AgentState, action: CandidateAction
    ) -> tuple[dict[str, Any], str | None]:
        index = _int_arg(action, "line_index")
        if _line_at(state, index) is None:
            return {}, "dejar_sin_comprar needs an existing line"
        return {"line_index": index}, None

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        index = int(proposal.payload["line_index"])
        line = _line_at(state, index)
        updated = self.engine.skip_line(state, index)
        if line is None:
            return updated
        notice = (
            f"No he encontrado «{line.raw_text}» en las tiendas cercanas, "
            "así que queda fuera del plan."
        )
        return _confirmed(updated, notice)


class _Explicar(_ExecutorBase):
    """Writes a grounded Spanish explanation of the current plan into `buyer_summary`."""

    def _apply(self, state: AgentState, proposal: Proposal) -> AgentState:
        return replace(state, buyer_summary=explain_plan(state, self.engine.chain_label))


def _money(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _count(value: Decimal) -> str:
    return f"{value.to_integral_value(rounding=ROUND_HALF_UP)}"


def explain_plan(state: AgentState, chain_label: Callable[[str], str] = str.title) -> str:
    """Spanish explanation built only from `state.plan` and `state.lines` (no model, no I/O)."""
    plan = state.plan
    way = "en coche" if state.mode == "car" else "andando"
    sentences: list[str] = []
    if plan.store_names:
        stores = " + ".join(dict.fromkeys(plan.store_names))
        sentences.append(
            f"El plan actual compra en {stores} por {_money(plan.total_cost)} € "
            f"con {_count(plan.travel_minutes)} min de desplazamiento {way}."
        )
    else:
        sentences.append("Ahora mismo no hay ninguna tienda en el plan.")
    bought = [line for line in state.lines if line.status == "ok"]
    pending = [line for line in state.lines if line.status != "ok"]
    sentences.append(f"Cubre {len(bought)} de {len(state.lines)} líneas de tu lista.")
    if pending:
        names = ", ".join(f"«{line.raw_text}»" for line in pending)
        sentences.append(f"Quedan sin comprar: {names}.")
    constraints: list[str] = []
    if state.excluded_chains:
        constraints.append("sin " + ", ".join(chain_label(code) for code in state.excluded_chains))
    if state.allowed_chains:
        constraints.append("solo en " + " y ".join(chain_label(c) for c in state.allowed_chains))
    stores_word = "tienda" if state.max_stores == 1 else "tiendas"
    constraints.append(f"máximo {state.max_stores} {stores_word}")
    sentences.append("Restricciones activas: " + "; ".join(constraints) + ".")
    alternative = next(iter(_real_alternatives(state)), None)
    if alternative is not None:
        sentences.append(
            f"La alternativa principal es {' + '.join(alternative.store_names)} "
            f"({_money(alternative.total_cost)} €, {_count(alternative.travel_minutes)} min)"
            + (f": {alternative.reason.rstrip('.')}." if alternative.reason else ".")
        )
    return " ".join(sentences)


def _confirmed(state: AgentState, sentence: str) -> AgentState:
    """Put the confirmation of what just changed before the summary of the new plan."""
    summary = (state.buyer_summary or "").strip()
    return replace(state, buyer_summary=f"{sentence} {summary}".strip())


def _line_name(state: AgentState, index: int) -> str:
    line = _line_at(state, index)
    return line.raw_text if line is not None else str(index)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


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
    ActionKind.FILTRAR_CADENA: _FiltrarCadena,
    ActionKind.CAMBIAR_MAX_TIENDAS: _CambiarMaxTiendas,
    ActionKind.CAMBIAR_PRIORIDAD: _CambiarPrioridad,
    ActionKind.CAMBIAR_PRODUCTO: _CambiarProducto,
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
    items: Mapping[int, Item] | None = None,
    next_index: int | None = None,
) -> dict[ActionKind, ActionExecutor]:
    """DB-backed executors that re-run the real pipeline after every mutation.

    `items` and `next_index` continue a conversation: the catalog lines keep the indexes the
    agent state uses (a removed line leaves a gap) instead of being numbered from zero.
    """
    engine = _RecommenderEngine(
        session,
        routing,
        base_query,
        today=today,
        settings=settings or get_settings(),
        items=items,
        next_index=next_index,
    )
    return {kind: executor_type(engine) for kind, executor_type in _EXECUTOR_TYPES.items()}


def _recommender_engine(
    executors: Mapping[ActionKind, ActionExecutor],
) -> _RecommenderEngine | None:
    for executor in executors.values():
        engine = getattr(executor, "engine", None)
        if isinstance(engine, _RecommenderEngine):
            return engine
    return None


def plan_items(executors: Mapping[ActionKind, ActionExecutor]) -> dict[int, Item]:
    """The catalog lines of the plan as they stand now, by line index (empty if simulated)."""
    engine = _recommender_engine(executors)
    return dict(engine._items) if engine is not None else {}


def refresh_recommendation(
    executors: Mapping[ActionKind, ActionExecutor], state: AgentState
) -> RecommendationResponse | None:
    """Recompute the plan of `state` without touching it, to serve it live with its route."""
    engine = _recommender_engine(executors)
    if engine is None:
        return None
    before = engine.last_recommendation
    try:
        engine.reoptimize(state)
    except ValueError, ChoiceRequired, NoCandidateStores, BasketCalculationError, RoutingError:
        engine.last_recommendation = before
        return None
    return engine.last_recommendation


# -- simulated backend ----------------------------------------------------


class _SimulatedEngine:
    """In-memory transitions: lines and mode change, figures stay as the scenario wrote them."""

    def __init__(self, *, chains: Sequence[str]) -> None:
        self._chains = tuple(chains)

    def reoptimize(self, state: AgentState) -> AgentState:
        # The figures stay as written, but a summary of the plan before the change is stale.
        return replace(state, status=RunStatus.RUNNING, buyer_summary=None)

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
        code = chain.lower()
        chains = state.excluded_chains
        if code not in chains:
            chains = (*chains, code)
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

    def habit_problem(self, state: AgentState, habit: LineHabit) -> str | None:
        # The simulated catalog is not consulted: a habit without a canonical product cannot be
        # bought, and its label is the only dietary evidence the scenario data can express.
        if habit.canonical_id is None:
            return "la elección habitual no tiene ningún producto disponible"
        if not _dietary_ok(None, habit.canonical_name, state.dietary_rules, strict_variant=False):
            return "la elección habitual no cumple las reglas dietéticas"
        return None

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]:
        shown = {
            "mode": mode,
            "store_names": list(state.plan.store_names),
            "total_cost": str(state.plan.total_cost),
            "travel_minutes": str(state.plan.travel_minutes),
            "cost_delta": "0",
            "minutes_delta": "0",
            "reason": _mode_reason(mode, len(state.plan.store_names), Decimal(0), Decimal(0)),
        }
        return state, shown

    def line_options(
        self, state: AgentState, line: LineState, kind: str, limit: int
    ) -> list[dict[str, Any]]:
        source = line.candidate_options if kind == "vague" else line.substitute_options
        return [dict(option) for option in source[:limit]]

    def product_for_canonical(
        self, canonical_id: int | None, state: AgentState
    ) -> dict[str, Any] | None:
        if canonical_id is None:
            return None
        return {"product_id": None, "canonical_id": canonical_id}

    def restrict_chains(self, state: AgentState, keep: Sequence[str]) -> AgentState:
        wanted = {code.lower() for code in keep}
        excluded = tuple(code for code in self._chains if code.lower() not in wanted)
        merged = (*state.excluded_chains, *(c for c in excluded if c not in state.excluded_chains))
        return self.reoptimize(replace(state, excluded_chains=merged))

    def set_category(self, state: AgentState, index: int, category_key: str) -> AgentState:
        return self.reoptimize(_update(state, index, status="ok"))

    def category_for_text(self, value: str) -> str | None:
        return None

    def canonical_for_text(self, value: str) -> dict[str, Any] | None:
        return None

    def filter_chains(self, state: AgentState, chains: Sequence[str]) -> AgentState:
        allowed = tuple(dict.fromkeys(code.lower() for code in chains))
        excluded = tuple(code for code in state.excluded_chains if code.lower() not in allowed)
        return self.reoptimize(replace(state, allowed_chains=allowed, excluded_chains=excluded))

    def set_max_stores(self, state: AgentState, max_stores: int) -> AgentState:
        return self.reoptimize(replace(state, max_stores=max_stores))

    def set_priority(self, state: AgentState, priority: str) -> AgentState:
        return self.reoptimize(replace(state, priority=priority))

    def replacement_problem(self, state: AgentState, index: int, text_value: str) -> str | None:
        # The only evidence a simulated product has is its label.
        if not _dietary_ok(None, text_value, state.dietary_rules, strict_variant=False):
            return f"«{text_value}» no cumple las reglas dietéticas"
        return None

    def replace_product(self, state: AgentState, index: int, text_value: str) -> AgentState:
        problem = self.replacement_problem(state, index, text_value)
        if problem is not None:
            raise ValueError(problem)
        return self.reoptimize(_replaced_line(state, index, text_value))

    def known_chains(self) -> KnownChains:
        return build_known_chains((code, None) for code in self._chains)

    def chain_label(self, code: str) -> str:
        return code.replace("_", " ").title()

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
        items: Mapping[int, Item] | None = None,
        next_index: int | None = None,
    ) -> None:
        self.session = session
        self.routing = routing
        self.base_query = base_query
        self.today = today
        self.settings = settings
        self._items: dict[int, Item] = (
            dict(items) if items is not None else dict(enumerate(base_query.items))
        )
        default_next = (max(self._items) + 1) if self._items else 0
        self._next = max(default_next, next_index or 0)
        self._excluded: list[str] = []
        self._known: KnownChains | None = None
        self.last_recommendation: RecommendationResponse | None = None

    def reoptimize(self, state: AgentState) -> AgentState:
        return self._reoptimize(state)

    def remove_line(self, state: AgentState, index: int) -> AgentState:
        items = dict(self._items)
        items.pop(index, None)
        return self._commit(_drop(state, index), items=items)

    def skip_line(self, state: AgentState, index: int) -> AgentState:
        items = dict(self._items)
        items.pop(index, None)
        return self._commit(_update(state, index, status="skipped"), items=items)

    def add_line(
        self, state: AgentState, text_value: str, quantity: Decimal, unit: str
    ) -> AgentState:
        index = self._next
        items = dict(self._items)
        items[index] = Item(
            text=text_value,
            category_key=self._category_for_text(text_value),
            quantity=quantity,
            unit=_unit(unit),
        )
        line = LineState(index=index, raw_text=text_value, quantity=quantity, unit=unit)
        return self._commit(
            replace(state, lines=(*state.lines, line)), items=items, next_index=index + 1
        )

    def set_quantity(self, state: AgentState, index: int, quantity: Decimal) -> AgentState:
        items = dict(self._items)
        item = items.get(index)
        if item is not None:
            items[index] = replace(item, quantity=quantity)
        return self._commit(_update(state, index, quantity=quantity), items=items)

    def set_brand(self, state: AgentState, index: int, brand: str | None) -> AgentState:
        items = dict(self._items)
        item = items.get(index)
        if item is not None:
            items[index] = replace(item, brand=brand)
        return self._commit(
            _update(state, index, brand=brand, brand_pinned=brand is not None), items=items
        )

    def set_mode(self, state: AgentState, mode: str) -> AgentState:
        return self._reoptimize(state, mode=mode)

    def exclude_chain(self, state: AgentState, chain: str) -> AgentState:
        code = chain.lower()
        excluded = list(self._excluded)
        if code not in excluded:
            excluded.append(code)
        chains = state.excluded_chains
        if code not in {value.lower() for value in chains}:
            chains = (*chains, code)
        return self._commit(replace(state, excluded_chains=chains), excluded=excluded)

    def use_product(
        self,
        state: AgentState,
        index: int,
        product_id: int | None,
        *,
        label: str | None = None,
        canonical_id: int | None = None,
    ) -> AgentState:
        items = dict(self._items)
        if product_id is not None:
            item = items.get(index)
            if item is not None:
                line = _line_at(state, index)
                quantity = _pack_count(line.quantity if line is not None else item.quantity)
                items[index] = replace(
                    item,
                    category_key=None,
                    product_id=product_id,
                    accept="equivalent",
                    quantity=quantity,
                    unit=Unit.UD,
                )
                state = _update(state, index, status="ok", quantity=quantity, unit=Unit.UD.value)
            else:
                state = _update(state, index, status="ok")
        return self._commit(state, items=items)

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

    def habit_problem(self, state: AgentState, habit: LineHabit) -> str | None:
        product = self._product_for_canonical(habit.canonical_id, state)
        if product is None:
            return "la elección habitual no tiene ningún producto disponible"
        if not _dietary_ok(
            product.get("variant_key"),
            product.get("name"),
            state.dietary_rules,
            strict_variant=True,
        ):
            return "la elección habitual no cumple las reglas dietéticas"
        return None

    def compare(self, state: AgentState, mode: str) -> tuple[AgentState, dict[str, Any]]:
        query, _ = self._query_for(state, mode=mode, max_alternatives=0)
        response, basket = recommend_with_basket(
            self.session, query, self.routing, self.today, self.settings, persist=False
        )
        shown = {
            "mode": mode,
            "store_names": [store.name for store in response.stores],
            "total_cost": str(basket.total_cost),
            "travel_minutes": str(basket.minutes),
            "cost_delta": str(basket.total_cost - state.plan.total_cost),
            "minutes_delta": str(basket.minutes - state.plan.travel_minutes),
            "reason": _mode_reason(
                mode,
                len(response.stores),
                basket.total_cost - state.plan.total_cost,
                basket.minutes - state.plan.travel_minutes,
                current_stores=len(state.plan.store_names),
            ),
        }
        return state, shown

    def line_options(
        self, state: AgentState, line: LineState, kind: str, limit: int
    ) -> list[dict[str, Any]]:
        if kind == "vague":
            item = self._items.get(line.index)
            key = item.category_key if item is not None else None
            if key is None:
                key = self.category_for_text(line.raw_text)
            return self.category_options(key, self._planned_zones(state), limit) if key else []
        return self._substitutes(state, line.index, limit)

    def category_options(
        self, category_key: str, zones: Sequence[int], limit: int = 6
    ) -> list[dict[str, Any]]:
        return category_candidate_options(self.session, category_key, zones, limit)

    def product_for_canonical(
        self, canonical_id: int | None, state: AgentState
    ) -> dict[str, Any] | None:
        return self._product_for_canonical(canonical_id, state)

    def restrict_chains(self, state: AgentState, keep: Sequence[str]) -> AgentState:
        wanted = {code.lower() for code in keep}
        active = self.active_chains()
        if not wanted & {code.lower() for code in active}:
            return state
        excluded = [code.lower() for code in active if code.lower() not in wanted]
        chains = tuple(dict.fromkeys((*state.excluded_chains, *excluded)))
        return self._commit(replace(state, excluded_chains=chains), excluded=excluded)

    def set_category(self, state: AgentState, index: int, category_key: str) -> AgentState:
        items = dict(self._items)
        item = items.get(index)
        if item is not None:
            items[index] = replace(item, category_key=category_key, product_id=None)
        cleared = _update(state, index, status="ok", candidate_options=(), substitute_options=())
        return self._commit(cleared, items=items)

    def category_for_text(self, value: str) -> str | None:
        return self._category_for_text(value)

    def canonical_for_text(self, value: str) -> dict[str, Any] | None:
        wanted = value.strip()
        if not wanted:
            return None
        row = (
            self.session.execute(
                text(
                    "select id, name from canonical_product "
                    "where lower(name) = lower(:text) "
                    "or lower(name) like '%' || lower(:text) || '%' "
                    "order by (lower(name) = lower(:text)) desc, length(name), id limit 1"
                ),
                {"text": wanted},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return {"label": row["name"], "canonical_id": row["id"], "canonical_name": row["name"]}

    def filter_chains(self, state: AgentState, chains: Sequence[str]) -> AgentState:
        active = {code.lower() for code in self.active_chains()}
        allowed = tuple(dict.fromkeys(c.lower() for c in chains if c.lower() in active))
        excluded = [code for code in self._excluded if code.lower() not in allowed]
        kept = tuple(code for code in state.excluded_chains if code.lower() not in allowed)
        return self._commit(
            replace(state, allowed_chains=allowed, excluded_chains=kept), excluded=excluded
        )

    def set_max_stores(self, state: AgentState, max_stores: int) -> AgentState:
        return self._reoptimize(replace(state, max_stores=max_stores))

    def set_priority(self, state: AgentState, priority: str) -> AgentState:
        return self._reoptimize(replace(state, priority=priority))

    def replacement_problem(self, state: AgentState, index: int, text_value: str) -> str | None:
        item = self._items.get(index)
        if self._category_for_text(text_value) is None and (item is None or not item.category_key):
            return f"no reconozco «{text_value}» en el catálogo"
        return None

    def replace_product(self, state: AgentState, index: int, text_value: str) -> AgentState:
        previous = self._items.get(index)
        named = self._category_for_text(text_value)
        # A bare variety ("basmati") has no category of its own: it stays in the line's.
        category = named or (previous.category_key if previous is not None else None)
        line = _line_at(state, index)
        if category is None or line is None:
            raise ValueError(f"no reconozco «{text_value}» en el catálogo")
        quantity, unit = line.quantity, _unit(line.unit)
        base = self._base_unit(category)
        if base is not None and _dimension(base) != _dimension(unit.value):
            quantity, unit = Decimal(1), _unit(base)
        items = dict(self._items)
        items[index] = Item(
            text=text_value,
            category_key=category,
            quantity=quantity,
            unit=unit,
            private_label_ok=previous.private_label_ok if previous is not None else True,
        )
        before = self.last_recommendation
        try:
            replaced = _replaced_line(state, index, text_value, quantity, unit)
            updated = self._reoptimize(replaced, items=items)
            self._check_replacement(updated, index, text_value, named is None)
        except Exception:
            # A rejected replacement must not leak its recommendation to the HTTP response.
            self.last_recommendation = before
            raise
        self._items = items
        return updated

    def _base_unit(self, category_key: str) -> str | None:
        value = self.session.execute(
            text("select base_unit from category where key = :key"), {"key": category_key}
        ).scalar_one_or_none()
        return str(value) if value else None

    def _check_replacement(
        self, state: AgentState, index: int, text_value: str, kept_category: bool
    ) -> None:
        line = _line_at(state, index)
        if line is None or line.status != "ok" or line.canonical_name is None:
            raise ValueError(f"«{text_value}» no está disponible en las tiendas cercanas")
        if kept_category:
            # The words were not a category: the product bought must carry them, or the
            # replacement would silently turn into something else ("xyzzy" into cheese).
            bought = _fold(line.canonical_name)
            words = [w for w in _fold(text_value).split() if len(w) >= 3]
            if not all(word in bought for word in words):
                raise ValueError(f"no encuentro «{text_value}» entre los productos de esa línea")
        if not state.dietary_rules:
            return
        variant = None
        if line.canonical_id is not None:
            variant = self.session.execute(
                text("select variant_key from canonical_product where id = :id"),
                {"id": line.canonical_id},
            ).scalar_one_or_none()
        if variant is None or not _dietary_ok(
            variant, line.canonical_name, state.dietary_rules, strict_variant=True
        ):
            raise ValueError(f"«{text_value}» no cumple las reglas dietéticas")

    def known_chains(self) -> KnownChains:
        if self._known is None:
            self._known = load_known_chains(self.session)
        return self._known

    def chain_label(self, code: str) -> str:
        return self.known_chains().names.get(code) or code.replace("_", " ").title()

    def find_substitute(self, state: AgentState, index: int) -> dict[str, Any] | None:
        found = self._substitutes(state, index, 1)
        return found[0] if found else None

    def _substitutes(self, state: AgentState, index: int, limit: int) -> list[dict[str, Any]]:
        category = self._line_category(index)
        if category is None:
            return []
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
            return []
        zones = self._planned_zones(state)
        if not zones:
            return []
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
        found: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in products:
            if row["canonical_id"] in seen:
                continue
            if _dietary_ok(
                row["variant_key"], row["name"], state.dietary_rules, strict_variant=True
            ):
                seen.add(row["canonical_id"])
                found.append(
                    {
                        "label": row["canonical_name"],
                        "product_id": row["product_id"],
                        "canonical_id": row["canonical_id"],
                        "canonical_name": row["canonical_name"],
                        "name": row["name"],
                        "variant_key": row["variant_key"],
                        "price": str(row["price"]),
                    }
                )
                if len(found) >= limit:
                    break
        return found

    def active_chains(self) -> tuple[str, ...]:
        rows = self.session.execute(text("select code from chain order by code")).scalars()
        return tuple(rows)

    # -- pipeline -------------------------------------------------------

    def _commit(
        self,
        state: AgentState,
        *,
        items: dict[int, Item] | None = None,
        excluded: list[str] | None = None,
        next_index: int | None = None,
    ) -> AgentState:
        """Re-optimize against the candidate catalog, then publish it only if that succeeded.

        The engine never keeps a half-applied mutation: if the pipeline raises, `self._items`,
        `self._excluded` and `self._next` stay exactly as they were.
        """
        updated = self._reoptimize(state, items=items, excluded=excluded)
        if items is not None:
            self._items = items
        if excluded is not None:
            self._excluded = excluded
        if next_index is not None:
            self._next = next_index
        return updated

    def _reoptimize(
        self,
        state: AgentState,
        *,
        mode: str | None = None,
        items: dict[int, Item] | None = None,
        excluded: list[str] | None = None,
    ) -> AgentState:
        query, positions = self._query_for(state, mode=mode, items=items, excluded=excluded)
        try:
            response, basket = recommend_with_basket(
                self.session, query, self.routing, self.today, self.settings, persist=False
            )
        except ChoiceRequired as exc:
            index = positions.get(exc.line_id)
            if index is None:
                raise
            line = _line_at(state, index)
            options = (
                tuple(self.category_options(exc.category_key, self._planned_zones(state)))
                if line is not None and not line.candidate_options
                else ()
            )
            vague = _update(
                state,
                index,
                status="vague",
                **({"candidate_options": options} if options else {}),
            )
            return self._reoptimize(vague, mode=mode, items=items, excluded=excluded)
        skipped_missing = [
            MissingResponse(
                line_id=line.index,
                text=line.raw_text,
                reason="not_available",
                stop=None,
            )
            for line in state.lines
            if line.status == "skipped"
        ]
        if skipped_missing:
            existing_ids = {item.line_id for item in response.missing}
            extra = [item for item in skipped_missing if item.line_id not in existing_ids]
            if extra:
                response = response.model_copy(update={"missing": [*response.missing, *extra]})
        self.last_recommendation = response
        return self._state_from_result(state, query, response, basket, positions)

    def _query_for(
        self,
        state: AgentState,
        *,
        mode: str | None = None,
        max_alternatives: int = 3,
        items: dict[int, Item] | None = None,
        excluded: list[str] | None = None,
    ) -> tuple[RecommendationQuery, dict[int, int]]:
        catalog = self._items if items is None else items
        excluded_codes = self._excluded if excluded is None else excluded
        items_list: list[Item] = []
        positions: dict[int, int] = {}
        for line in state.lines:
            if line.status in {"vague", "skipped"} or line.index not in catalog:
                continue
            base = catalog[line.index]
            items_list.append(replace(base, quantity=line.quantity, unit=_unit(line.unit)))
            positions[len(items_list) - 1] = line.index
        active = self.active_chains()
        excluded_set = {code.lower() for code in excluded_codes} | {
            code.lower() for code in state.excluded_chains
        }
        allowed_set = {code.lower() for code in (state.allowed_chains or self.base_query.chains)}
        remaining = tuple(
            code
            for code in active
            if code.lower() not in excluded_set and (not allowed_set or code.lower() in allowed_set)
        )
        restricted = bool(excluded_set or allowed_set)
        if restricted and not remaining:
            # `chains=()` means "every chain" downstream, so an empty remainder must never
            # reach the query: that would silently undo the restriction.
            raise ValueError("no quedaría ninguna cadena activa tras las restricciones")
        chains = remaining if restricted else ()
        query = RecommendationQuery(
            items=tuple(items_list),
            origin=self.base_query.origin,
            mode=TravelMode(mode or state.mode),
            max_stores=state.max_stores,
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
        response: RecommendationResponse,
        basket: BasketResult,
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
        plan = plan_snapshot_from_result(self.session, response, basket)
        return replace(
            state,
            lines=tuple(lines),
            mode=query.mode.value,
            priority=query.priority_mode.value,
            max_stores=query.max_stores,
            plan=plan,
            buyer_summary=response.explanation,
            status=RunStatus.RUNNING,
            # A re-optimization means the shopper's request was handled: it must not fire again.
            shopper_message=None,
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
                    "select p.id as product_id, p.name, canon.name as canonical_name, "
                    "canon.variant_key "
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


def category_candidate_options(
    session: Session, category_key: str, zones: Sequence[int], limit: int = 6
) -> list[dict[str, Any]]:
    """Cheapest available canonical products under a category, as clickable options."""
    if not zones:
        return []
    rows = session.execute(
        text(
            "select cp.id as canonical_id, cp.name, min(pc.price) as price "
            "from canonical_product cp "
            "join category_closure cc on cc.descendant_id = cp.category_id "
            "join category c on c.id = cc.ancestor_id and c.key = :key "
            "join chain_product p on p.canonical_id = cp.id and p.is_active "
            "join chain_product_zone pz on pz.chain_product_id = p.id and pz.is_available "
            "join price_current pc on pc.chain_product_id = p.id and pc.zone_id = pz.zone_id "
            "where pz.zone_id in :zones "
            "group by cp.id, cp.name order by min(pc.price), cp.id limit :limit"
        ).bindparams(bindparam("zones", expanding=True)),
        {"key": category_key, "zones": sorted(zones), "limit": limit},
    ).mappings()
    return [
        {
            "label": row["name"],
            "canonical_id": row["canonical_id"],
            "category_key": category_key,
            "price": str(row["price"]),
        }
        for row in rows
    ]


def _mode_reason(
    mode: str,
    stores: int,
    cost_delta: Decimal,
    minutes_delta: Decimal,
    *,
    current_stores: int | None = None,
) -> str:
    label = "En coche" if mode == "car" else "Andando"
    reason = alternative_reason(
        stores=stores,
        current_stores=current_stores if current_stores is not None else stores,
        cost_delta=cost_delta,
        minutes_delta=minutes_delta,
    )
    return f"{label}: {reason[0].lower()}{reason[1:]}"


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _chosen_option(
    question: PendingQuestion | None, answer: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The option an answer picks: by index, by canonical id or by label (accent-insensitive)."""
    options = question.options if question is not None else ()
    index = answer.get("option_index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(options):
        return dict(options[index])
    if answer.get("product_id") is not None:
        return {"product_id": answer["product_id"], "canonical_id": answer.get("canonical_id")}
    canonical_id = answer.get("canonical_id")
    if canonical_id is not None:
        match = next((o for o in options if o.get("canonical_id") == canonical_id), None)
        return dict(match) if match is not None else {"canonical_id": canonical_id}
    for key in ("choice_label", "message"):
        value = answer.get(key)
        if isinstance(value, str) and value.strip():
            wanted = _fold(value)
            match = next((o for o in options if _fold(str(o.get("label") or "")) == wanted), None)
            if match is not None:
                return dict(match)
    return None


def apply_shopper_answer(
    engine: _Engine, state: AgentState, answer: Mapping[str, Any]
) -> AgentState:
    """Turn the shopper's answer to the pending question into a real change of the plan.

    The chosen option (by index, canonical id or label) is applied through the engine: skip the
    line, keep or switch the plan, use a product or narrow a vague category. A free text that
    matches nothing is looked up in the catalog for the pending line and otherwise queued as a
    `shopper_request`. Observations are then recomputed, so what was solved is not asked again.
    """
    question = state.pending_question
    line_index = question.line_index if question is not None else None
    line = _line_at(state, line_index)
    option = _chosen_option(question, answer)
    message = answer.get("message")
    message = message.strip() if isinstance(message, str) and message.strip() else None
    state = replace(state, shopper_message=None, pending_question=None)
    decided_plan = False
    request: str | None = None

    if option is not None:
        action = option.get("action")
        if action == "skip":
            if line is not None:
                state = engine.skip_line(state, line.index)
        elif action in {"keep_plan", "select_alternative"}:
            decided_plan = True
            codes = [str(code) for code in option.get("chain_codes") or ()]
            if action == "select_alternative" and codes:
                state = engine.restrict_chains(state, codes)
        elif line is not None:
            state = _apply_product_choice(engine, state, line, option)
    elif message is not None:
        category = (
            engine.category_for_text(message)
            if line is not None and line.status in {"vague", "missing"}
            else None
        )
        canonical = (
            engine.canonical_for_text(message)
            if category is None and line is not None and line.status in {"vague", "missing"}
            else None
        )
        if category is not None and line is not None:
            state = engine.set_category(state, line.index, category)
        else:
            chosen = (
                _apply_product_choice(engine, state, line, canonical)
                if canonical is not None and line is not None
                else state
            )
            if chosen is state:  # nothing in the catalog settled it: the shopper is asking
                request = message
            else:
                state = chosen

    state = replace(state, shopper_message=request)
    observations = detect_observations(state, known_chains=engine.known_chains())
    if decided_plan:
        observations = tuple(o for o in observations if o.kind is not ObservationKind.NEAR_TIE)
    return replace(state, observations=observations)


def _apply_product_choice(
    engine: _Engine, state: AgentState, line: LineState, option: Mapping[str, Any]
) -> AgentState:
    label = option.get("canonical_name") or option.get("name") or option.get("label")
    canonical_id = option.get("canonical_id")
    product_id = option.get("product_id")
    if product_id is None and canonical_id is not None:
        product = engine.product_for_canonical(canonical_id, state)
        if product is None or not _dietary_ok(
            product.get("variant_key"),
            product.get("name"),
            state.dietary_rules,
            strict_variant="variant_key" in product,
        ):
            return state
        product_id = product.get("product_id")
        label = label or product.get("canonical_name")
    if product_id is not None or canonical_id is not None:
        return engine.use_product(
            state, line.index, product_id, label=label, canonical_id=canonical_id
        )
    category_key = option.get("category_key")
    if category_key:
        return engine.set_category(state, line.index, str(category_key))
    return state


def answer_applier(
    executors: Mapping[ActionKind, ActionExecutor],
) -> Callable[[AgentState, Mapping[str, Any]], AgentState]:
    """`apply_answer` for `AgentHarness.resume`, bound to the engine behind `executors`."""
    engine = next(
        (e for e in (getattr(ex, "engine", None) for ex in executors.values()) if e is not None),
        None,
    )
    if engine is None:
        raise ValueError("the executors have no engine to apply an answer with")
    return lambda state, answer: apply_shopper_answer(engine, state, answer)


def last_recommendation(
    executors: Mapping[ActionKind, ActionExecutor],
) -> RecommendationResponse | None:
    """Return the latest `RecommendationResponse` produced by any re-optimization, if any."""
    for executor in executors.values():
        engine = getattr(executor, "engine", None)
        response = getattr(engine, "last_recommendation", None)
        if isinstance(response, RecommendationResponse):
            return response
    return None


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


def _pack_count(value: Any) -> Decimal:
    """A concrete product is bought in whole packs: round up and never go below one."""
    quantity = _positive(value)
    if quantity is None:
        return Decimal(1)
    return quantity.to_integral_value(rounding=ROUND_CEILING)


def _next_index(state: AgentState) -> int:
    return max((line.index for line in state.lines), default=-1) + 1


def _update(state: AgentState, index: int, **changes: Any) -> AgentState:
    lines = tuple(replace(line, **changes) if line.index == index else line for line in state.lines)
    return replace(state, lines=lines)


_DIMENSIONS = {"kg": "mass", "g": "mass", "l": "volume", "ml": "volume", "ud": "count"}


def _dimension(unit: str) -> str:
    return _DIMENSIONS.get(unit, unit)


def _replaced_line(
    state: AgentState,
    index: int,
    text_value: str,
    quantity: Decimal | None = None,
    unit: Unit | None = None,
) -> AgentState:
    """The line `index` asking for `text_value`, with nothing left of the previous product."""
    keep: dict[str, Any] = {}
    if quantity is not None and unit is not None:
        keep = {"quantity": quantity, "unit": unit.value}
    return _update(
        state,
        index,
        **keep,
        raw_text=text_value,
        status="ok",
        canonical_id=None,
        canonical_name=None,
        brand=None,
        brand_pinned=False,
        exact_only=False,
        habit=None,
        candidate_options=(),
        substitute_options=(),
    )


def _drop(state: AgentState, index: int) -> AgentState:
    lines = tuple(line for line in state.lines if line.index != index)
    return replace(state, lines=lines)


def _option_is_safe(option: Mapping[str, Any], dietary_rules: Sequence[str]) -> bool:
    return _dietary_ok(
        option.get("variant_key"),
        option.get("name") or option.get("label"),
        dietary_rules,
        strict_variant="variant_key" in option,
    )


def _dietary_ok(
    variant_key: str | None,
    name: str | None,
    dietary_rules: Sequence[str],
    *,
    strict_variant: bool,
) -> bool:
    """Whether a product declares every dietary rule (FR-42).

    The real catalog is strict: a rule is satisfied only by its exact token inside
    `variant_key`, so a product name that merely mentions the phrase (often to warn about
    traces) can never pass. Simulated substitutes without a `variant_key` fall back to their
    label, and that label must carry the required phrase and no negation or warning. Unknown
    rules fail closed: buying blindly is worse than leaving the line unbought.
    """
    if not dietary_rules:
        return True
    tokens = _variant_tokens(variant_key)
    for rule in dietary_rules:
        tags = _DIETARY_TAGS.get(str(rule).strip().lower())
        if tags is None:
            return False
        tag, phrase = tags
        if tag in tokens:
            continue
        if strict_variant:
            return False
        label = (name or "").lower()
        if phrase not in label or any(negation in label for negation in _DIETARY_NEGATIONS):
            return False
    return True


def _variant_tokens(variant_key: str | None) -> frozenset[str]:
    tokens = (token.strip().lower() for token in str(variant_key or "").split("|"))
    return frozenset(token for token in tokens if token)
