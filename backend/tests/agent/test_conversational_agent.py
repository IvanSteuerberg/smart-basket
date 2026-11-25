"""Conversational requests of the agent (E5): chains from the database, four new actions,
multi-line removal, real explanations and explicit confirmations.

Pure tests cover the parser, `valid_actions` and the simulated executors; `db` tests run the same
actions through the real pipeline over the synthetic world of `tests/recommender/conftest.py`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.agent.actions import ActionKind, CandidateAction, valid_actions
from smart_basket.agent.core import AgentHarness, ScriptedPolicy
from smart_basket.agent.detector import (
    KnownChains,
    build_known_chains,
    detect_observations,
    load_known_chains,
    parse_shopper_request_hints,
    state_from_recommendation,
)
from smart_basket.agent.executors import (
    answer_applier,
    build_recommender_executors,
    build_simulated_executors,
    explain_plan,
)
from smart_basket.agent.observations import Observation, ObservationKind
from smart_basket.agent.state import (
    AgentState,
    AlternativePlanSummary,
    LineState,
    PendingQuestion,
    PlanSnapshot,
    RunStatus,
)
from smart_basket.config import get_settings
from smart_basket.optimizer import PriorityMode, Unit
from smart_basket.recommender.catalog import Item
from smart_basket.recommender.service import RecommendationQuery, recommend_with_basket
from smart_basket.routing import TravelMode
from tests.recommender import conftest as recommender

ORIGIN = recommender.ORIGIN
FakeRouting = recommender.FakeRouting
engine = recommender.engine
world = recommender.world
TODAY = date(2026, 11, 13)

REAL_CHAINS: KnownChains = build_known_chains(
    [
        ("mercadona", "Mercadona"),
        ("carrefour", "Carrefour"),
        ("dia", "Dia"),
        ("lidl", "Lidl"),
        ("alimerka", "Alimerka"),
        ("el_corte_ingles", "El Corte Inglés"),
        ("eleclerc", "E.Leclerc"),
    ]
)


def _lines(*texts: str) -> tuple[LineState, ...]:
    return tuple(LineState(index=i, raw_text=value) for i, value in enumerate(texts))


def _hints(message: str, lines: tuple[LineState, ...] = (), mode: str = "walk") -> dict[str, Any]:
    return parse_shopper_request_hints(message, lines, current_mode=mode, known_chains=REAL_CHAINS)


# -- parser ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "chain"),
    [
        ("sin Alimerka", "alimerka"),
        ("no quiero ir a Lidl", "lidl"),
        ("evita el Mercadona", "mercadona"),
        ("sin El Corte Inglés", "el_corte_ingles"),
        ("no voy al corte ingles", "el_corte_ingles"),
        ("sin E.Leclerc", "eleclerc"),
        ("no quiero ir a Leclerc", "eleclerc"),
        ("nada de Dia", "dia"),
    ],
)
def test_exclusion_names_the_real_chain_code(message: str, chain: str) -> None:
    hints = _hints(message)

    assert hints["chain"] == chain
    assert "allowed_chains" not in hints
    assert hints["chain_names"][chain]


@pytest.mark.parametrize(
    "message",
    [
        "sin gluten",
        "quiero leche sin lactosa",
        "no quiero ir el día de mañana",
        "no quiero nada de eso",
        "sin prisa, que hoy es domingo",
    ],
)
def test_common_words_are_never_taken_for_a_chain(message: str) -> None:
    hints = _hints(message)

    assert "chain" not in hints
    assert "allowed_chains" not in hints


def test_without_real_chains_the_legacy_guess_is_kept() -> None:
    hints = parse_shopper_request_hints("no quiero ir al Lidl", (), current_mode="walk")

    assert hints["chain"] == "lidl"


def test_two_excluded_chains_are_both_reported() -> None:
    hints = _hints("sin Alimerka ni Lidl")

    assert hints["chain"] == "alimerka"
    assert hints["excluded_chains"] == ["alimerka", "lidl"]


@pytest.mark.parametrize(
    ("message", "allowed"),
    [
        ("solo en Dia", ["dia"]),
        ("comprar solo en Mercadona y Carrefour", ["mercadona", "carrefour"]),
        ("únicamente en Lidl", ["lidl"]),
        ("quiero ir solo a E.Leclerc", ["eleclerc"]),
    ],
)
def test_inclusion_filter_lists_the_chains_after_the_cue(message: str, allowed: list[str]) -> None:
    hints = _hints(message)

    assert hints["allowed_chains"] == allowed
    assert "chain" not in hints


def test_exclusion_and_filter_in_one_message_do_not_mix() -> None:
    hints = _hints("solo en Dia, sin Lidl")

    assert hints["allowed_chains"] == ["dia"]
    assert hints["chain"] == "lidl"


@pytest.mark.parametrize(
    ("message", "stores"),
    [
        ("en una sola tienda", 1),
        ("en 1 tienda", 1),
        ("máximo 1 tienda", 1),
        ("hasta 2 tiendas", 2),
        ("máximo 3 tiendas", 3),
        ("como mucho 3 tiendas", 3),
        ("no más de 2 tiendas", 2),
    ],
)
def test_store_limit(message: str, stores: int) -> None:
    hints = _hints(message)

    assert hints["max_stores"] == stores
    assert "quantity" not in hints


@pytest.mark.parametrize("message", ["más de 2 tiendas", "máximo 7 tiendas", "ve a la tienda"])
def test_no_store_limit_is_invented(message: str) -> None:
    assert "max_stores" not in _hints(message)


@pytest.mark.parametrize(
    ("message", "priority"),
    [
        ("prioriza ahorrar", "savings"),
        ("lo más barato posible", "savings"),
        ("lo más rápido posible", "time"),
        ("quiero perder menos tiempo", "time"),
        ("ahorrar tiempo", "time"),
        ("prefiero un plan equilibrado", "balanced"),
    ],
)
def test_priority(message: str, priority: str) -> None:
    assert _hints(message)["priority"] == priority


@pytest.mark.parametrize(
    ("message", "index", "new_text"),
    [
        ("cambia la leche por leche desnatada", 0, "leche desnatada"),
        ("pon pan integral en vez de pan", 1, "pan integral"),
        ("cambia el arroz por basmati", 2, "basmati"),
        ("mejor pechuga de pollo en vez de pollo", 3, "pechuga de pollo"),
        ("cambia el plátano por manzanas", 4, "manzanas"),
    ],
)
def test_product_replacement(message: str, index: int, new_text: str) -> None:
    lines = _lines("leche", "pan", "arroz", "pollo", "plátano")

    hints = _hints(message, lines)

    assert hints["replace_text"] == new_text
    assert hints["line_index"] == index
    assert hints["line_indices"] == [index]


def test_a_replacement_with_a_number_is_a_quantity_change_instead() -> None:
    hints = _hints("en vez de 1 litro de leche pon 6 litros", _lines("leche"))

    assert "replace_text" not in hints
    assert hints["quantity"] == "6"


def test_a_replacement_of_something_not_in_the_list_is_ignored() -> None:
    hints = _hints("cambia el vino por cerveza", _lines("leche", "pan"))

    assert "replace_text" not in hints


def test_several_lines_to_remove_are_all_reported() -> None:
    lines = _lines("leche entera", "pan", "huevos", "yogur natural")

    hints = _hints("quita leche y pan", lines)
    assert hints["line_indices"] == [0, 1]
    assert "line_index" not in hints

    hints = _hints("quita los huevos, el pan y el yogur", lines)
    assert hints["line_indices"] == [1, 2, 3]


def test_removing_one_line_still_reports_a_single_line() -> None:
    hints = _hints("quita los huevos", _lines("leche entera", "huevos"))

    assert hints["line_index"] == 1


# -- valid_actions --------------------------------------------------------


def _observation(message: str, lines: tuple[LineState, ...] = ()) -> tuple[AgentState, Observation]:
    state = AgentState(lines=lines, shopper_message=message)
    observation = detect_observations(state, known_chains=REAL_CHAINS)[0]
    assert observation.kind is ObservationKind.SHOPPER_REQUEST
    return state, observation


def _offered(message: str, lines: tuple[LineState, ...] = ()) -> dict[str, Any]:
    state, observation = _observation(message, lines)
    return {item.key: item for item in valid_actions(state, observation)}


def test_exclusion_candidate_names_the_chain() -> None:
    offered = _offered("sin Alimerka")

    candidate = offered["excluir_cadena:0"]
    assert candidate.kind is ActionKind.EXCLUIR_CADENA
    assert candidate.args == {"chain": "alimerka"}
    assert candidate.label == "Excluir la cadena Alimerka"


def test_chain_filter_candidate_names_the_chains() -> None:
    assert _offered("solo en Dia")["filtrar_cadena:0"].label == "Comprar solo en Dia"

    both = _offered("comprar solo en Mercadona y Alimerka")["filtrar_cadena:0"]
    assert both.kind is ActionKind.FILTRAR_CADENA
    assert both.args == {"chains": ["mercadona", "alimerka"]}
    assert both.label == "Comprar solo en Mercadona y Alimerka"


@pytest.mark.parametrize(
    ("message", "key", "label"),
    [
        ("en una sola tienda", "cambiar_max_tiendas:1", "Cambiar a máximo 1 tienda"),
        ("hasta 2 tiendas", "cambiar_max_tiendas:2", "Cambiar a máximo 2 tiendas"),
        ("prioriza ahorrar", "cambiar_prioridad:savings", "Cambiar prioridad a ahorro"),
        ("lo más rápido", "cambiar_prioridad:time", "Cambiar prioridad a tiempo"),
        ("equilibrado", "cambiar_prioridad:balanced", "Cambiar prioridad a equilibrio"),
    ],
)
def test_store_limit_and_priority_candidates(message: str, key: str, label: str) -> None:
    candidate = _offered(message)[key]

    assert candidate.label == label


def test_product_replacement_candidate_names_both_products() -> None:
    lines = _lines("leche entera", "pan")

    candidate = _offered("cambia la leche por leche desnatada", lines)["cambiar_producto:0"]

    assert candidate.kind is ActionKind.CAMBIAR_PRODUCTO
    assert candidate.args == {"line_index": 0, "text": "leche desnatada"}
    assert candidate.label == "Cambiar «leche entera» por «leche desnatada»"


def test_removal_candidates_name_the_lines() -> None:
    lines = _lines("huevos", "pan", "leche")

    single = _offered("quita los huevos", lines)
    assert single["quitar_linea:0"].label == "Quitar «huevos»"

    several = _offered("quita los huevos y el pan", lines)
    multi = several["quitar_linea:multi"]
    assert multi.args == {"line_indices": [0, 1]}
    assert multi.label == "Quitar «huevos» y «pan»"


def test_keys_are_opaque_and_the_shoppers_words_stay_in_args() -> None:
    offered = _offered("cambia la leche por leche desnatada", _lines("leche"))

    assert all("desnatada" not in key for key in offered)
    assert ActionKind.NO_HACER_NADA.value in offered


def test_nothing_conversational_is_offered_without_a_hint() -> None:
    offered = _offered("¿y si voy en coche?", _lines("leche"))

    kinds = {item.kind for item in offered.values()}
    assert not kinds & {
        ActionKind.FILTRAR_CADENA,
        ActionKind.CAMBIAR_MAX_TIENDAS,
        ActionKind.CAMBIAR_PRIORIDAD,
        ActionKind.CAMBIAR_PRODUCTO,
    }


def test_the_catalog_has_seventeen_actions() -> None:
    assert len(ActionKind) == 17


# -- simulated executors --------------------------------------------------


def _plan() -> PlanSnapshot:
    return PlanSnapshot(
        store_names=("Mercadona Centro", "Carrefour Sur"),
        total_cost=Decimal("11.7"),
        travel_minutes=Decimal("18.4"),
        chain_codes=("carrefour", "mercadona"),
        alternatives=(
            AlternativePlanSummary(
                store_names=("Mercadona Centro",),
                total_cost=Decimal("12.9"),
                travel_minutes=Decimal("9"),
                objective_delta=Decimal("0.1"),
                chain_codes=("mercadona",),
                reason="Solo 1 tienda (+1,20 €)",
            ),
        ),
    )


def _base() -> AgentState:
    return AgentState(
        lines=(
            LineState(index=0, raw_text="leche entera", canonical_name="Leche entera"),
            LineState(index=1, raw_text="pan", canonical_name="Pan de pueblo"),
            LineState(index=2, raw_text="huevos", canonical_name="Huevos frescos"),
        ),
        plan=_plan(),
    )


def _run_simulated(state: AgentState, message: str, key: str):
    state = replace(state, shopper_message=message)
    observation = detect_observations(state, known_chains=REAL_CHAINS)[0]
    state = replace(state, observations=(observation,))
    assert key in {item.key for item in valid_actions(state, observation)}
    return AgentHarness().run(state, ScriptedPolicy([key]), build_simulated_executors())


def test_simulated_exclusion_confirms_it() -> None:
    result = _run_simulated(_base(), "sin Dia", "excluir_cadena:0")

    assert result.steps[0].error is None
    assert result.state.excluded_chains == ("dia",)
    assert result.state.buyer_summary == "He excluido Dia del plan."


def test_simulated_chain_filter_limits_the_plan_and_confirms_it() -> None:
    result = _run_simulated(_base(), "solo en Mercadona y Dia", "filtrar_cadena:0")

    assert result.steps[0].error is None
    assert result.state.allowed_chains == ("mercadona", "dia")
    assert result.state.buyer_summary.startswith("He limitado el plan a solo en Mercadona y Dia.")


def test_a_filter_replaces_the_exclusion_of_the_same_chain() -> None:
    state = replace(_base(), excluded_chains=("dia",))

    result = _run_simulated(state, "solo en Dia", "filtrar_cadena:0")

    assert result.state.allowed_chains == ("dia",)
    assert result.state.excluded_chains == ()


def test_a_filter_to_a_chain_that_does_not_exist_is_rejected() -> None:
    result = AgentHarness().run(
        replace(_base(), observations=(Observation(ObservationKind.SHOPPER_REQUEST, "pide"),)),
        ScriptedPolicy(["filtrar_cadena:0"]),
        build_simulated_executors(),
    )

    assert result.steps[0].error is not None
    assert result.state.allowed_chains == ()


def test_simulated_store_limit() -> None:
    result = _run_simulated(_base(), "en una sola tienda", "cambiar_max_tiendas:1")

    assert result.steps[0].error is None
    assert result.state.max_stores == 1
    assert result.state.buyer_summary == "He limitado la compra a 1 tienda."

    again = _run_simulated(result.state, "hasta 3 tiendas", "cambiar_max_tiendas:3")
    assert again.state.max_stores == 3
    assert again.state.buyer_summary == "He limitado la compra a 3 tiendas."


def test_a_store_limit_that_is_already_set_is_rejected() -> None:
    result = _run_simulated(_base(), "hasta 2 tiendas", "cambiar_max_tiendas:2")

    assert result.steps[0].error is not None
    assert "ya admite" in result.steps[0].error


@pytest.mark.parametrize(
    ("message", "key", "priority", "sentence"),
    [
        ("prioriza ahorrar", "cambiar_prioridad:savings", "savings", "ahorrar"),
        ("lo más rápido", "cambiar_prioridad:time", "time", "ahorrar tiempo"),
    ],
)
def test_simulated_priority(message: str, key: str, priority: str, sentence: str) -> None:
    result = _run_simulated(_base(), message, key)

    assert result.steps[0].error is None
    assert result.state.priority == priority
    assert result.state.buyer_summary == f"He cambiado la prioridad a {sentence}."


def test_simulated_product_replacement() -> None:
    result = _run_simulated(_base(), "cambia la leche por leche desnatada", "cambiar_producto:0")

    assert result.steps[0].error is None
    line = result.state.lines[0]
    assert line.raw_text == "leche desnatada"
    assert line.canonical_name is None
    assert result.state.buyer_summary == "He cambiado «leche entera» por «leche desnatada»."


def test_simulated_replacement_never_breaks_a_dietary_rule() -> None:
    state = replace(_base(), dietary_rules=("sin_lactosa",))

    rejected = _run_simulated(state, "cambia la leche por leche desnatada", "cambiar_producto:0")
    assert rejected.steps[0].error is not None
    assert "reglas dietéticas" in rejected.steps[0].error
    assert rejected.state.lines[0].raw_text == "leche entera"

    accepted = _run_simulated(state, "cambia la leche por leche sin lactosa", "cambiar_producto:0")
    assert accepted.steps[0].error is None
    assert accepted.state.lines[0].raw_text == "leche sin lactosa"


def test_simulated_removal_of_several_lines_at_once() -> None:
    result = _run_simulated(_base(), "quita los huevos y el pan", "quitar_linea:multi")

    assert result.steps[0].error is None
    assert [line.raw_text for line in result.state.lines] == ["leche entera"]
    assert result.state.buyer_summary == "He quitado «pan» y «huevos» de la lista."


def test_simulated_removal_of_one_line_confirms_it() -> None:
    result = _run_simulated(_base(), "quita los huevos", "quitar_linea:2")

    assert [line.index for line in result.state.lines] == [0, 1]
    assert result.state.buyer_summary == "He quitado «huevos» de la lista."


def test_a_removal_naming_a_missing_line_is_rejected() -> None:
    state = replace(_base(), observations=(Observation(ObservationKind.SHOPPER_REQUEST, "x"),))
    executors = build_simulated_executors()
    action = CandidateAction(
        "quitar_linea:multi", ActionKind.QUITAR_LINEA, {"line_indices": [0, 9]}, "Quitar"
    )
    executor = executors[ActionKind.QUITAR_LINEA]

    problem = executor.validate(state, executor.propose(state, action))

    assert problem is not None


def test_simulated_mode_quantity_brand_and_add_confirm_what_changed() -> None:
    def run(details: dict[str, Any], key: str) -> AgentState:
        observation = Observation(ObservationKind.SHOPPER_REQUEST, "pide", 0, details)
        state = replace(_base(), observations=(observation,))
        return AgentHarness().run(state, ScriptedPolicy([key]), build_simulated_executors()).state

    assert run({}, "cambiar_modo").buyer_summary == "He cambiado el desplazamiento a coche."
    assert (
        run({"quantity": "3"}, "modificar_cantidad:0").buyer_summary
        == "He cambiado la cantidad de «leche entera» a 3."
    )
    assert (
        run({"brand": "Hacendado"}, "cambiar_marca:0").buyer_summary
        == "He fijado la marca «Hacendado» para «leche entera»."
    )
    assert (
        run({"text": "yogur"}, "anadir_linea:0").buyer_summary == "He añadido «yogur» a la lista."
    )


def test_explain_writes_a_real_summary_from_the_plan_and_the_lines() -> None:
    state = replace(
        _base(),
        mode="car",
        excluded_chains=("dia",),
        allowed_chains=("mercadona", "carrefour"),
        max_stores=2,
        lines=(*_base().lines[:2], replace(_base().lines[2], status="missing")),
        observations=(Observation(ObservationKind.SHOPPER_REQUEST, "explica"),),
    )

    result = AgentHarness().run(state, ScriptedPolicy(["explicar"]), build_simulated_executors())

    summary = result.state.buyer_summary
    assert summary is not None
    assert result.steps[0].error is None
    assert "Mercadona Centro + Carrefour Sur" in summary
    assert "11,70 €" in summary
    assert "18 min" in summary
    assert "en coche" in summary
    assert "Cubre 2 de 3 líneas" in summary
    assert "«huevos»" in summary
    assert "sin Dia" in summary
    assert "solo en Mercadona y Carrefour" in summary
    assert "máximo 2 tiendas" in summary
    assert "alternativa principal es Mercadona Centro" in summary
    assert "Solo 1 tienda" in summary


def test_explain_without_a_plan_still_says_something() -> None:
    summary = explain_plan(AgentState(lines=()))

    assert "no hay ninguna tienda" in summary
    assert summary == explain_plan(AgentState(lines=()))


def test_asking_always_leaves_a_question() -> None:
    state = AgentState(
        lines=(LineState(index=0, raw_text="pan", canonical_name="Pan de pueblo"),),
        observations=(Observation(ObservationKind.SHOPPER_REQUEST, "x"),),
    )

    result = AgentHarness().run(state, ScriptedPolicy(["preguntar"]), build_simulated_executors())

    assert result.status is RunStatus.WAITING_SHOPPER
    assert result.state.pending_question is not None
    assert result.state.pending_question.prompt


# -- real pipeline (database) ---------------------------------------------


@pytest.fixture
def session(world):
    with Session(bind=world.connection) as db:
        yield db


ITEMS = (
    Item(text="leche semidesnatada", category_key="leche", quantity=Decimal(2), unit=Unit.L),
    Item(text="yogur natural", category_key="yogur", quantity=Decimal(4), unit=Unit.UD),
    Item(text="queso curado", category_key="queso", quantity=Decimal("0.5"), unit=Unit.KG),
)
MILK_AND_RICE = (
    ITEMS[0],
    Item(text="arroz redondo", category_key="arroz", quantity=Decimal(1), unit=Unit.KG),
)


def _query(items: tuple[Item, ...] = ITEMS) -> RecommendationQuery:
    return RecommendationQuery(
        items=items,
        origin=ORIGIN,
        mode=TravelMode.WALK,
        max_stores=2,
        priority_mode=PriorityMode.BALANCED,
        return_to_origin=True,
        degraded=False,
        payload={},
        max_alternatives=2,
    )


def _setup(session: Session, items: tuple[Item, ...] = ITEMS, **state_changes: Any):
    query = _query(items)
    routing = FakeRouting()
    response, basket = recommend_with_basket(session, query, routing, TODAY, get_settings())
    state = state_from_recommendation(session, query, response, basket_result=basket)
    executors = build_recommender_executors(session, routing, query, today=TODAY)
    return replace(state, **state_changes), executors


def _say(session: Session, state: AgentState, executors, message: str, key: str):
    state = replace(state, shopper_message=message)
    observation = detect_observations(state, known_chains=load_known_chains(session))[0]
    assert key in {item.key for item in valid_actions(state, observation)}, observation.details
    state = replace(state, observations=(observation,))
    return AgentHarness().run(state, ScriptedPolicy([key]), executors)


@pytest.mark.db
def test_real_chains_come_from_the_chain_table(session: Session) -> None:
    known = load_known_chains(session)

    assert known.aliases["mercadona"] == "mercadona"
    assert known.aliases["carrefour"] == "carrefour"
    assert known.names["mercadona"] == "Mercadona"
    hints = parse_shopper_request_hints(
        "sin Carrefour, que hoy no me apetece", (), current_mode="walk", known_chains=known
    )
    assert hints["chain"] == "carrefour"
    assert hints["chain_names"] == {"carrefour": "Carrefour"}


@pytest.mark.db
def test_real_chain_filter_keeps_only_that_chain(session: Session) -> None:
    state, executors = _setup(session, MILK_AND_RICE)
    assert set(state.plan.chain_codes) == {"mercadona", "carrefour"}

    result = _say(session, state, executors, "solo en Carrefour", "filtrar_cadena:0")

    assert result.steps[0].error is None
    assert result.state.allowed_chains == ("carrefour",)
    assert result.state.plan.chain_codes == ("carrefour",)
    assert result.state.buyer_summary.startswith("He limitado el plan a solo en Carrefour.")


@pytest.mark.db
def test_real_exclusion_then_filter_accumulate_and_the_filter_wins_a_conflict(
    session: Session,
) -> None:
    state, executors = _setup(session, MILK_AND_RICE)

    first = _say(session, state, executors, "sin Mercadona", "excluir_cadena:0")
    assert first.state.excluded_chains == ("mercadona",)
    assert first.state.buyer_summary.startswith("He excluido Mercadona del plan.")

    # Excluding the only chain left would leave nothing: it is refused, the plan stays.
    refused = _say(session, first.state, executors, "sin Carrefour", "excluir_cadena:0")
    assert refused.steps[0].error is not None
    assert "ninguna cadena activa" in refused.steps[0].error
    assert refused.state.excluded_chains == ("mercadona",)

    # "Only Mercadona" later wins over the earlier "without Mercadona".
    last = _say(session, first.state, executors, "solo en Mercadona", "filtrar_cadena:0")
    assert last.steps[0].error is None
    assert last.state.excluded_chains == ()
    assert last.state.allowed_chains == ("mercadona",)


@pytest.mark.db
def test_real_store_limit_and_priority_reoptimize(session: Session) -> None:
    state, executors = _setup(session, MILK_AND_RICE)

    limited = _say(session, state, executors, "en una sola tienda", "cambiar_max_tiendas:1")
    assert limited.steps[0].error is None
    assert limited.state.max_stores == 1
    assert len(set(limited.state.plan.store_names)) == 1
    assert limited.state.buyer_summary.startswith("He limitado la compra a 1 tienda.")

    message = "lo más rápido posible"
    quick = _say(session, limited.state, executors, message, "cambiar_prioridad:time")
    assert quick.steps[0].error is None
    assert quick.state.priority == "time"
    assert quick.state.max_stores == 1  # what was asked before stays
    assert quick.state.buyer_summary.startswith("He cambiado la prioridad a ahorrar tiempo.")


@pytest.mark.db
def test_real_product_replacement_reoptimizes_and_confirms(session: Session) -> None:
    state, executors = _setup(session)

    result = _say(
        session, state, executors, "cambia el queso por yogur griego", "cambiar_producto:2"
    )

    assert result.steps[0].error is None
    line = result.state.lines[2]
    assert line.raw_text == "yogur griego"
    assert line.status == "ok"
    assert "yogur" in (line.canonical_name or "").lower()
    assert result.state.buyer_summary.startswith("He cambiado «queso curado» por «yogur griego».")


@pytest.mark.db
def test_real_replacement_with_an_unknown_product_changes_nothing(session: Session) -> None:
    state, executors = _setup(session)

    result = _say(
        session, state, executors, "cambia el queso por xyzzy plugh", "cambiar_producto:2"
    )

    assert result.steps[0].error is not None
    assert result.state.lines[2].raw_text == "queso curado"


@pytest.mark.db
def test_real_replacement_never_breaks_a_dietary_rule(session: Session) -> None:
    state, executors = _setup(session, dietary_rules=("sin_lactosa",))

    rejected = _say(
        session, state, executors, "cambia la leche por yogur natural", "cambiar_producto:0"
    )
    assert rejected.steps[0].error is not None
    assert "reglas dietéticas" in rejected.steps[0].error
    assert rejected.state.lines[0].raw_text == "leche semidesnatada"
    assert rejected.state.plan == state.plan

    accepted = _say(
        session, state, executors, "cambia la leche por leche sin lactosa", "cambiar_producto:0"
    )
    assert accepted.steps[0].error is None
    variant = session.execute(
        text("select variant_key from canonical_product where id = :id"),
        {"id": accepted.state.lines[0].canonical_id},
    ).scalar_one()
    assert "sin_lactosa" in variant


@pytest.mark.db
def test_real_removal_of_several_lines(session: Session) -> None:
    state, executors = _setup(session)

    result = _say(session, state, executors, "quita el yogur y el queso", "quitar_linea:multi")

    assert result.steps[0].error is None
    assert [line.raw_text for line in result.state.lines] == ["leche semidesnatada"]
    assert result.state.buyer_summary.startswith(
        "He quitado «yogur natural» y «queso curado» de la lista."
    )


@pytest.mark.db
def test_real_explain_describes_the_current_plan(session: Session) -> None:
    state, executors = _setup(session)
    state = replace(state, observations=(Observation(ObservationKind.SHOPPER_REQUEST, "explica"),))

    result = AgentHarness().run(state, ScriptedPolicy(["explicar"]), executors)

    summary = result.state.buyer_summary
    assert result.steps[0].error is None
    assert summary is not None
    assert "El plan actual compra en" in summary
    assert " € con " in summary
    assert "min de desplazamiento andando" in summary
    assert "Cubre 3 de 3 líneas" in summary
    assert "máximo 2 tiendas" in summary


@pytest.mark.db
def test_real_change_of_mode_confirms_it(session: Session) -> None:
    state, executors = _setup(session)

    result = _say(session, state, executors, "mejor voy en coche", "cambiar_modo")

    assert result.state.mode == "car"
    assert result.state.buyer_summary.startswith("He cambiado el desplazamiento a coche.")


@pytest.mark.db
def test_a_free_text_answer_naming_a_canonical_product_settles_the_line(
    session: Session,
) -> None:
    state, executors = _setup(session)
    canonical_id = session.execute(
        text("select id from canonical_product where name = 'Coca-Cola zero'")
    ).scalar_one()
    vague = replace(
        state,
        lines=tuple(
            replace(line, status="vague") if line.index == 1 else line for line in state.lines
        ),
        pending_question=PendingQuestion(line_index=1, prompt="¿Cuál?", options=()),
        status=RunStatus.WAITING_SHOPPER,
    )

    answered = answer_applier(executors)(vague, {"message": "Coca-Cola zero"})

    assert answered.lines[1].canonical_id == canonical_id
    assert answered.lines[1].status == "ok"
    assert answered.shopper_message is None
