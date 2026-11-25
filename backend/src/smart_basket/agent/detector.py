"""Deterministic detector: turns the recommendation output into typed observations (ADR 0022).

The detector is pure and rule-based. It never calls a model and never guesses what the shopper
wants: it reports what is wrong with the list (vague lines, items missing everywhere), when two
plans are close enough to compare, and what a free-text message seems to ask for. The parsed
hints are evidence for `valid_actions`, not a decision.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.agent.observations import Observation, ObservationKind
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineHabit,
    LineState,
    PlanSnapshot,
)
from smart_basket.optimizer import BasketResult
from smart_basket.recommender.service import RecommendationQuery, RecommendationResponse

#: A plan whose objective is within this many euros of the winner is close enough to show.
DEFAULT_NEAR_TIE_THRESHOLD = Decimal("0.20")

_WORD = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "algo",
        "algun",
        "alguna",
        "de",
        "del",
        "desde",
        "donde",
        "el",
        "ella",
        "en",
        "entre",
        "es",
        "esa",
        "ese",
        "eso",
        "esta",
        "este",
        "esto",
        "gr",
        "gracias",
        "la",
        "las",
        "lo",
        "los",
        "mas",
        "mejor",
        "me",
        "mi",
        "mis",
        "mucho",
        "muy",
        "no",
        "o",
        "os",
        "para",
        "pero",
        "por",
        "que",
        "quiero",
        "se",
        "sea",
        "sean",
        "si",
        "sin",
        "sobre",
        "su",
        "sus",
        "te",
        "tu",
        "un",
        "una",
        "uno",
        "unos",
        "unas",
        "vale",
        "y",
        "ya",
    }
)

_NUMBER_WORDS: dict[str, Decimal] = {
    "un": Decimal(1),
    "una": Decimal(1),
    "uno": Decimal(1),
    "dos": Decimal(2),
    "tres": Decimal(3),
    "cuatro": Decimal(4),
    "cinco": Decimal(5),
    "seis": Decimal(6),
    "siete": Decimal(7),
    "ocho": Decimal(8),
    "nueve": Decimal(9),
    "diez": Decimal(10),
    "once": Decimal(11),
    "doce": Decimal(12),
    "docena": Decimal(12),
    "docenas": Decimal(12),
    "media": Decimal("0.5"),
    "medio": Decimal("0.5"),
}

_UNIT_WORDS = frozenset(
    {
        "kg",
        "g",
        "l",
        "ml",
        "kilo",
        "kilos",
        "gramo",
        "gramos",
        "litro",
        "litros",
        "mililitro",
        "mililitros",
        "docena",
        "docenas",
        "unidad",
        "unidades",
        "ud",
        "uds",
    }
)

_ADD_TRIGGERS = (
    "anade",
    "anadir",
    "agrega",
    "agregar",
    "apunta",
    "apuntar",
    "mete",
    "incluye",
    "incluir",
)
_REMOVE_TRIGGERS = ("quita", "quitar", "quitame", "elimina", "eliminar", "saca", "borra")
_QUANTITY_TRIGGERS = ("pon", "ponme", "ponle", "mejor", "cambia", "sube", "baja", "sean")
_EXCLUDE_CUES = (
    "no quiero",
    "no voy",
    "no ir",
    "no vayas",
    "no al",
    "sin ",
    "evita",
    "evitar",
    "excluye",
    "excluir",
    "nada de",
)


def parse_shopper_request_hints(
    message: str,
    lines: Sequence[LineState],
    *,
    current_mode: str,
    known_chains: Sequence[str] = (),
) -> dict[str, Any]:
    """Extract the hints a free-text request carries, without deciding anything.

    Only hints that are actually present travel in the result. Values are JSON-safe already:
    `quantity` is a positive `Decimal` rendered as `str`, and line references are indexes of
    `lines`. Arbitrary or hostile text must never raise; it simply yields fewer hints.
    """
    folded = _fold(message or "")
    if not folded.strip():
        return {}
    tokens = _WORD.findall(folded)
    token_set = set(tokens)
    hints: dict[str, Any] = {}

    line_indices = _match_lines(tokens, lines)
    if line_indices:
        hints["line_indices"] = line_indices
        if len(line_indices) == 1:
            hints["line_index"] = line_indices[0]

    mode = _mode(tokens, current_mode=current_mode)
    if mode is not None:
        hints["mode"] = mode

    chain = _excluded_chain(folded, token_set, known_chains=known_chains)
    if chain is not None:
        hints["chain"] = chain

    quantity = _quantity(folded, tokens)
    if quantity is not None:
        hints["quantity"] = str(quantity)

    add_text = _add_text(tokens)
    if add_text:
        hints["add_text"] = add_text

    brand_all, accept_any_brand = _brand_hints(folded, token_set)
    if brand_all:
        hints["brand_all"] = True
    if accept_any_brand:
        hints["accept_any_brand"] = True

    if _hypothetical(folded):
        hints["hypothetical"] = True
    return hints


def detect_observations(
    state: AgentState, *, near_tie_threshold: Decimal = DEFAULT_NEAR_TIE_THRESHOLD
) -> tuple[Observation, ...]:
    """Every phenomenon present in `state`, in a fixed order, one observation per finding."""
    observations: list[Observation] = []
    # What the shopper just asked for always goes first: pausing on a near tie must never
    # swallow an explicit request.
    if state.shopper_message and state.shopper_message.strip():
        observations.append(_shopper_request(state))
    for line in state.lines:
        if line.status == "vague":
            observations.append(_vague(line))
        elif line.status == "missing":
            observations.append(_missing(line))
    near_tie = _near_tie_observation(state, near_tie_threshold)
    if near_tie is not None:
        observations.append(near_tie)
    return tuple(observations)


def state_from_recommendation(
    session: Session,
    query: RecommendationQuery,
    response: RecommendationResponse | None,
    *,
    basket_result: BasketResult | None = None,
    vague_lines: Sequence[dict[str, Any]] = (),
    habits: Mapping[str, LineHabit] | None = None,
    dietary_rules: Sequence[str] = (),
    shopper_message: str | None = None,
) -> AgentState:
    """Build the agent state from the recommendation pipeline output and optional habits.

    Lines follow `query.items`, so their `index` is the line id the HTTP response uses. Vague
    lines are reported by the preprocessor (`vague_lines`), missing lines by the optimizer; the
    rest are `ok`. The returned state already carries the detector's observations.
    """
    response_lines = {
        line.line_id: line
        for store in (response.stores if response is not None else ())
        for line in store.lines
    }
    missing_reasons = {
        line.line_id: line.reason for line in (response.missing if response is not None else ())
    }
    vague_by_index = {_line_id(entry): entry for entry in vague_lines}
    habits = habits or {}

    line_states: list[LineState] = []
    for index, item in enumerate(query.items):
        bought = response_lines.get(index)
        vague = vague_by_index.get(index)
        habit = _habit_for(item, vague, habits)
        if vague is not None:
            status = "vague"
        elif missing_reasons.get(index) == "not_available":
            status = "missing"
        else:
            status = "ok"
        line_states.append(
            LineState(
                index=index,
                raw_text=item.text,
                canonical_id=bought.canonical_id if bought is not None else None,
                canonical_name=bought.product_name if bought is not None else None,
                quantity=item.quantity,
                unit=item.unit.value,
                brand=bought.brand if bought is not None else item.brand,
                brand_pinned=item.brand is not None,
                exact_only=bought.exact_only if bought is not None else False,
                status=status,
                habit=habit,
                candidate_options=_options(vague),
                substitute_options=_options(vague, "substitute_options"),
            )
        )

    plan = plan_snapshot_from_result(session, response, basket_result)
    state = AgentState(
        lines=tuple(line_states),
        mode=query.mode.value,
        priority=query.priority_mode.value,
        excluded_chains=(),
        dietary_rules=tuple(dietary_rules),
        plan=plan,
        shopper_message=shopper_message,
        buyer_summary=response.explanation if response is not None else None,
    )
    return _with_observations(state)


# -- observations ---------------------------------------------------------


def _vague(line: LineState) -> Observation:
    summary = f"«{line.raw_text}» es un término vago"
    if line.habit is not None:
        summary += (
            f"; en las últimas {line.habit.total} compras eligió "
            f"{line.habit.canonical_name} {line.habit.count} veces."
        )
    else:
        summary += " y no hay una elección anterior en el perfil."
    return Observation(
        kind=ObservationKind.VAGUE_LINE,
        summary=summary,
        line_index=line.index,
        details={
            "candidate_options": [dict(option) for option in line.candidate_options],
            "habit": line.habit.to_dict() if line.habit is not None else None,
        },
    )


def _missing(line: LineState) -> Observation:
    options = [dict(option) for option in line.substitute_options]
    substitute_allowed = bool(options)
    if substitute_allowed:
        label = options[0].get("label") or options[0].get("name") or "un producto parecido"
        summary = f"«{line.raw_text}» no está en ninguna tienda cercana; existe «{label}»."
    else:
        summary = f"«{line.raw_text}» no está en ninguna tienda cercana y no hay nada parecido."
    details: dict[str, Any] = {
        "substitute_allowed": substitute_allowed,
        "substitute_options": options,
    }
    extra = next((option for option in options if "extra_minutes" in option), None)
    if extra is not None:
        details["extra_stop"] = extra.get("extra_stop") or extra.get("store")
        details["extra_minutes"] = extra["extra_minutes"]
    return Observation(
        kind=ObservationKind.MISSING_EVERYWHERE,
        summary=summary,
        line_index=line.index,
        details=details,
    )


def _near_ties(state: AgentState, threshold: Decimal) -> tuple[AlternativePlanSummary, ...]:
    return tuple(
        alternative
        for alternative in state.plan.alternatives
        if alternative.objective_delta <= threshold
        and not same_chains(state.plan.chain_codes, state.plan.store_names, alternative)
    )


def same_chains(
    current_codes: Sequence[str], current_names: Sequence[str], alternative: AlternativePlanSummary
) -> bool:
    """Whether an alternative visits exactly the same chains as the current plan.

    Other branches of the same chains are not a real choice, so they never form a tie. Chain
    codes are used when both sides have them; otherwise the normalized store names.
    """
    if current_codes and alternative.chain_codes:
        return frozenset(current_codes) == frozenset(alternative.chain_codes)
    return frozenset(_fold(name).strip() for name in current_names) == frozenset(
        _fold(name).strip() for name in alternative.store_names
    )


def _near_tie_observation(state: AgentState, threshold: Decimal) -> Observation | None:
    near = _near_ties(state, threshold)
    if not near:
        return None
    current = " + ".join(state.plan.store_names) if state.plan.store_names else "el plan actual"
    parts = [
        f"{' + '.join(item.store_names)} ({item.total_cost} €, {item.travel_minutes} min)"
        for item in near
    ]
    summary = (
        f"Empate técnico (≤ {threshold} € de objetivo): {current} "
        f"({state.plan.total_cost} €, {state.plan.travel_minutes} min) frente a "
        f"{'; '.join(parts)}."
    )
    return Observation(
        kind=ObservationKind.NEAR_TIE,
        summary=summary,
        details={
            "threshold": str(threshold),
            "alternatives": [item.to_dict() for item in near],
        },
    )


def _shopper_request(state: AgentState) -> Observation:
    message = (state.shopper_message or "").strip()
    hints = parse_shopper_request_hints(
        message,
        state.lines,
        current_mode=state.mode,
    )
    details: dict[str, Any] = dict(hints)
    if "add_text" in hints:
        details["text"] = hints["add_text"]
    if hints.get("brand_all"):
        details["brand"] = None
    return Observation(
        kind=ObservationKind.SHOPPER_REQUEST,
        summary=f"El comprador escribe: «{message}».",
        line_index=hints.get("line_index"),
        details=details,
    )


# -- state construction ---------------------------------------------------


def plan_snapshot_from_result(
    session: Session,
    response: RecommendationResponse | None,
    basket_result: BasketResult | None,
) -> PlanSnapshot:
    """Reduce the pipeline output to the plan the agent remembers (stores, figures, alternatives).

    Shared by the detector and the recommender executors so both see the same snapshot.
    """
    plan_stores = tuple(store.name for store in response.stores) if response is not None else ()
    if basket_result is None:
        if response is None:
            return PlanSnapshot()
        total = _decimal(response.total_cost)
        return PlanSnapshot(
            store_names=plan_stores,
            total_cost=total,
            travel_minutes=_decimal(response.minutes),
            comparable_cost=total,
        )
    current_names, current_codes = _stores_and_chains(session, basket_result.visiting_order)
    current_names = plan_stores or current_names
    alternatives: list[AlternativePlanSummary] = []
    for alternative in basket_result.alternatives:
        names, codes = _stores_and_chains(session, alternative.plan.visiting_order)
        cost_delta = alternative.plan.total_cost - basket_result.total_cost
        minutes_delta = alternative.plan.minutes - basket_result.minutes
        alternatives.append(
            AlternativePlanSummary(
                store_names=names,
                total_cost=alternative.plan.total_cost,
                travel_minutes=alternative.plan.minutes,
                objective_delta=alternative.objective_delta,
                chain_codes=codes,
                cost_delta=cost_delta,
                minutes_delta=minutes_delta,
                reason=alternative_reason(
                    stores=len(names),
                    current_stores=len(current_names),
                    cost_delta=cost_delta,
                    minutes_delta=minutes_delta,
                ),
            )
        )
    return PlanSnapshot(
        store_names=current_names,
        total_cost=basket_result.total_cost,
        travel_minutes=basket_result.minutes,
        comparable_cost=basket_result.comparable_cost,
        alternatives=tuple(alternatives),
        chain_codes=current_codes,
    )


def alternative_reason(
    *, stores: int, current_stores: int, cost_delta: Decimal, minutes_delta: Decimal
) -> str:
    """Short Spanish text saying why an alternative plan is worth a look."""
    cost = f"{_signed(cost_delta, 2)} €"
    if stores == 1 and current_stores >= 2:
        return f"Solo 1 tienda ({cost})"
    if cost_delta < 0:
        return f"Ahorra {_signed(-cost_delta, 2, plus=False)} € ({_signed(minutes_delta, 0)} min)"
    if minutes_delta < 0:
        return f"{_signed(-minutes_delta, 0, plus=False)} min más rápido ({cost})"
    return f"Opción similar ({cost})"


def _signed(value: Decimal, places: int, *, plus: bool = True) -> str:
    text_value = f"{abs(value):.{places}f}".replace(".", ",")
    if places == 0 and "," in text_value:
        text_value = text_value.rstrip("0").rstrip(",")
    if value < 0:
        return f"-{text_value}"
    return f"+{text_value}" if plus else text_value


def _stores_and_chains(
    session: Session, store_ids: Sequence[int]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Store names and chain codes at `store_ids`, in the given order."""
    if not store_ids:
        return (), ()
    rows = session.execute(
        text(
            "select s.id, s.name, c.code from store s "
            "left join chain c on c.id = s.chain_id where s.id in :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(store_ids)},
    ).mappings()
    by_id = {row["id"]: row for row in rows}
    names = tuple(by_id[sid]["name"] if sid in by_id else f"tienda {sid}" for sid in store_ids)
    codes = tuple(
        sorted(
            {str(by_id[sid]["code"]) for sid in store_ids if sid in by_id and by_id[sid]["code"]}
        )
    )
    return names, codes


def store_names(session: Session, store_ids: Sequence[int]) -> tuple[str, ...]:
    """Names of the stores at `store_ids`, in the given order, for plan snapshots."""
    return _stores_and_chains(session, store_ids)[0]


def _habit_for(
    item: Any,
    vague: Mapping[str, Any] | None,
    habits: Mapping[str, LineHabit],
) -> LineHabit | None:
    if vague is not None and isinstance(vague.get("habit"), Mapping):
        return LineHabit.from_dict(vague["habit"])
    for key in _habit_keys(item):
        habit = habits.get(key)
        if habit is not None:
            return habit
    return None


def _habit_keys(item: Any) -> tuple[str, ...]:
    keys = [item.text, item.text.lower(), _fold(item.text)]
    if item.category_key:
        keys.extend([item.category_key, item.category_key.lower()])
    return tuple(dict.fromkeys(key for key in keys if key))


def _options(entry: Mapping[str, Any] | None, key: str = "candidate_options") -> tuple[dict, ...]:
    if entry is None:
        return ()
    raw = entry.get(key) or entry.get("options") or ()
    return tuple(dict(option) for option in raw if isinstance(option, Mapping))


def _line_id(entry: Mapping[str, Any]) -> int:
    for key in ("index", "line_index", "line_id"):
        if key in entry:
            return int(entry[key])
    return int(entry.get("id", 0))


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return Decimal(0)
    return result


def _with_observations(state: AgentState) -> AgentState:
    return replace(state, observations=detect_observations(state))


# -- parser helpers -------------------------------------------------------


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _match_lines(tokens: Sequence[str], lines: Sequence[LineState]) -> list[int]:
    message = {_stem(token) for token in tokens}
    if not message:
        return []
    scored: list[tuple[int, int]] = []
    for line in lines:
        words = {
            _stem(token)
            for token in _WORD.findall(_fold(f"{line.raw_text} {line.canonical_name or ''}"))
            if len(token) >= 3 and token not in _STOPWORDS
        }
        score = len(words & message)
        if score:
            scored.append((score, line.index))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return sorted(index for score, index in scored if score == best)


def _mode(tokens: Sequence[str], *, current_mode: str) -> str | None:
    car = {"coche", "carro", "conducir", "conduciendo"}
    walk = {"andando", "caminando", "caminar"}
    found = [(position, "car") for position, word in enumerate(tokens) if word in car]
    found += [(position, "walk") for position, word in enumerate(tokens) if word in walk]
    if not found:
        return None
    target = max(found)[1]
    return None if target == current_mode else target


def _excluded_chain(folded: str, tokens: set[str], *, known_chains: Sequence[str]) -> str | None:
    if not any(cue in folded for cue in _EXCLUDE_CUES):
        return None
    folded_chains = {_fold(chain) for chain in known_chains}
    for chain in known_chains:
        if _fold(chain) in tokens:
            return chain
    for chain in folded_chains:
        if re.search(rf"\b{re.escape(chain)}\b", folded):
            return chain
    match = re.search(r"\b(?:al|a|de|del|sin)\s+([a-z]{3,})\b", folded)
    if match is None:
        return None
    candidate = match.group(1)
    return None if candidate in _STOPWORDS else candidate


def _quantity(folded: str, tokens: Sequence[str]) -> Decimal | None:
    numbers = [
        (match.start(), _parse_number(match.group(0)))
        for match in re.finditer(r"\d+(?:[.,]\d+)?", folded)
    ]
    numbers = [(position, value) for position, value in numbers if value is not None]
    has_trigger = any(trigger in tokens for trigger in _QUANTITY_TRIGGERS) or "en vez de" in folded
    has_unit = any(token in _UNIT_WORDS for token in tokens)
    if numbers and (has_trigger or has_unit):
        value = numbers[-1][1]
        return value if value is not None and value > 0 else None
    for position, token in enumerate(tokens):
        if token in _NUMBER_WORDS:
            near_unit = any(
                tokens[index] in _UNIT_WORDS
                for index in range(position + 1, min(position + 3, len(tokens)))
            )
            if near_unit or has_trigger:
                value = _NUMBER_WORDS[token]
                return value if value > 0 else None
    return None


def _parse_number(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _add_text(tokens: Sequence[str]) -> str | None:
    for position, token in enumerate(tokens):
        if token in _ADD_TRIGGERS:
            rest = list(tokens[position + 1 :])
            start = 0
            while start < len(rest) and (
                rest[start] in _STOPWORDS
                or rest[start] in _NUMBER_WORDS
                or rest[start] in _UNIT_WORDS
                or rest[start].isdigit()
            ):
                start += 1
            text = " ".join(rest[start:])
            return text or None
    return None


def _brand_hints(folded: str, tokens: set[str]) -> tuple[bool, bool]:
    if re.search(r"marca(?:s)? blanca|marcas? del? super|cualquier marca|sin marca", folded):
        return True, True
    if "marca" in tokens and (
        "igual" in tokens or "acepta" in tokens or "aceptar" in tokens or "da igual" in folded
    ):
        return False, True
    return False, False


def _hypothetical(folded: str) -> bool:
    return "?" in folded or "¿" in folded or "cuanto" in folded or "que pasaria" in folded
