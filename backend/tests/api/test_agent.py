"""The agent HTTP API against the synthetic world (database tests).

The fixtures come from `tests/recommender/conftest.py`: the seed, the fake routing and a
`TestClient` whose session is rolled back after each test, so no trace row survives the run.
The imported fixtures share their names with the test parameters on purpose; ruff's F811 is
silenced for the module because pytest registers them by their original names.
"""

# ruff: noqa: F811

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from smart_basket.agent.core import PolicyDecision, ScriptedPolicy
from smart_basket.api.agent import get_agent_policy
from tests.recommender.conftest import engine, world  # noqa: F401

pytestmark = pytest.mark.db


def item(
    text: str,
    category_key: str | None = None,
    quantity: str = "1",
    unit: str = "ud",
    *,
    product_id: int | None = None,
    accept: str = "equivalent",
    variants: list[str] | None = None,
    **extra,
) -> dict:
    body: dict = {
        "text": text,
        "quantity": quantity,
        "unit": unit,
        "brand": None,
        "private_label_ok": True,
        **extra,
    }
    if category_key is not None:
        body["category_key"] = category_key
    if product_id is not None:
        body["product_id"] = product_id
    if accept != "equivalent":
        body["accept"] = accept
    if variants is not None:
        body["variants"] = variants
    return body


FIVE_ITEMS = [
    item("leche semidesnatada", "leche", "2", "l"),
    item("yogur natural", "yogur", "4", "ud"),
    item("plátano", "platano", "1", "kg"),
    item("queso curado", "queso", "0.5", "kg"),
    item("huevos", "huevos", "12", "ud"),
]


def payload(items: list[dict], **overrides) -> dict:
    body = {
        "items": items,
        "origin": {"lat": 42.5987, "lon": -5.5671},
        "mode": "walk",
        "max_stores": 2,
        "priority_mode": "balanced",
        "return_to_origin": True,
        "degraded": False,
    }
    body.update(overrides)
    return body


def run_body(items: list[dict], **overrides) -> dict:
    return {"request": payload(items), **overrides}


def test_agent_run_completes_and_persists_the_trace(world):
    response = world.client.post("/api/agent/runs", json=run_body(FIVE_ITEMS, policy="default"))
    assert response.status_code == 200
    run = response.json()

    assert run["status"] == "completed"
    assert run["policy_name"] == "default"
    assert run["pending_question"] is None
    assert run["mode"] == "walk"
    assert run["steps_count"] == len(run["steps"])
    assert run["steps_count"] <= 1
    assert run["recommendation"] is not None
    assert run["recommendation"]["total_cost"] == "11.70"

    stored = (
        world.connection.execute(
            text(
                "select id::text as id, status, policy_name, steps_count from agent_run "
                "where id = cast(:id as uuid)"
            ),
            {"id": run["run_id"]},
        )
        .mappings()
        .one()
    )
    assert stored["id"] == run["run_id"]
    assert stored["status"] == "completed"
    assert stored["policy_name"] == "default"
    assert stored["steps_count"] == run["steps_count"]

    # The route is only served live (NFR-06): the stored run has none, so a later read is empty.
    assert run["recommendation"]["route"]
    assert "route" not in json.dumps(_stored_state(world, run["run_id"]))

    fetched = world.client.get(f"/api/agent/runs/{run['run_id']}")
    assert fetched.status_code == 200
    reread = fetched.json()
    assert reread["recommendation"]["route"] == []
    assert _without_route(reread) == _without_route(run)


def _without_route(run: dict) -> dict:
    recommendation = {k: v for k, v in run["recommendation"].items() if k != "route"}
    return {**run, "recommendation": recommendation}


def _canonical_id(world, name: str) -> int:
    return world.connection.execute(
        text("select id from canonical_product where name = :name"), {"name": name}
    ).scalar_one()


def _bought(run: dict) -> list[str]:
    stores = run["recommendation"]["stores"]
    return [line["product_name"] for store in stores for line in store["lines"]]


# One line the plan can buy plus one vague line: the plan exists (so it has zones and a route)
# while the agent pauses to ask about the vague one.
MILK_AND_VAGUE = [
    item("leche semidesnatada", "leche", "2", "l"),
    item("pollo preparado", "vague", "1", "kg"),
]


def _pause_on_the_vague_line(world, items: list[dict] = MILK_AND_VAGUE) -> dict:
    paused = world.client.post("/api/agent/runs", json=run_body(items, policy="default")).json()
    assert paused["status"] == "waiting_shopper"
    assert paused["recommendation"] is None
    assert paused["pending_question"]["line_index"] == len(items) - 1
    return paused


def test_vague_line_pauses_then_resumes_and_keeps_steps_in_order(world):
    response = world.client.post(
        "/api/agent/runs",
        json=run_body([item("pollo preparado", "vague", "1", "kg")], policy="default"),
    )
    assert response.status_code == 200
    paused = response.json()
    assert paused["status"] == "waiting_shopper"
    assert paused["recommendation"] is None
    assert paused["pending_question"]["line_index"] == 0
    assert paused["steps_count"] == 1
    assert paused["steps"][0]["chosen_action"] == "preguntar"
    assert paused["steps"][0]["observation"]["kind"] == "vague_line"

    # A free text that names a category settles the line itself: no further step is needed.
    resumed = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer",
        json={"message": "quiero pechuga de pollo"},
    )
    assert resumed.status_code == 200
    final = resumed.json()
    assert final["status"] == "completed"
    assert final["pending_question"] is None
    assert final["steps_count"] == 1
    assert [step["step_number"] for step in final["steps"]] == [1]
    assert final["steps"][0] == paused["steps"][0]
    assert any("pollo" in name.lower() for name in _bought(final))

    fetched = world.client.get(f"/api/agent/runs/{paused['run_id']}").json()
    assert fetched["status"] == "completed"
    assert fetched["steps"] == final["steps"]


def test_unresolved_text_keeps_asking_and_appends_the_steps_in_order(world):
    paused = _pause_on_the_vague_line(world)

    resumed = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer", json={"message": "lo que sea, algo rico"}
    )
    assert resumed.status_code == 200
    again = resumed.json()

    # The text matches no category, so it is handled as a request and the vague line is asked
    # again: the new steps follow the old one with no gap or repeated number.
    assert again["status"] == "waiting_shopper"
    assert again["pending_question"]["line_index"] == 1
    assert again["steps_count"] == len(again["steps"]) >= 2
    assert [step["step_number"] for step in again["steps"]] == list(
        range(1, again["steps_count"] + 1)
    )
    assert again["steps"][0] == paused["steps"][0]
    assert again["steps"][1]["observation"]["kind"] == "shopper_request"


def test_shopper_message_can_change_the_mode_with_the_injected_policy(world):
    scripted = ScriptedPolicy(
        [
            PolicyDecision(
                action_key="cambiar_modo",
                confidence=0.91,
                probabilities={"cambiar_modo": 0.91, "no_hacer_nada": 0.09},
                model_name="scripted-model",
            )
        ]
    )
    world.client.app.dependency_overrides[get_agent_policy] = lambda: scripted

    response = world.client.post(
        "/api/agent/runs",
        json=run_body(FIVE_ITEMS, shopper_message="mejor voy en coche"),
    )
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "completed"
    assert run["mode"] == "car"
    assert run["policy_name"] == "scripted"
    assert run["model_name"] == "scripted-model"
    assert run["steps_count"] == 1

    step = run["steps"][0]
    assert step["observation"]["kind"] == "shopper_request"
    assert step["chosen_action"] == "cambiar_modo"
    assert step["confidence"] == 0.91
    assert step["probabilities"] == {"cambiar_modo": 0.91, "no_hacer_nada": 0.09}
    assert step["result"]["overridden"] is False


def test_unknown_run_returns_404_on_read_and_answer(world):
    unknown = str(uuid4())
    assert world.client.get(f"/api/agent/runs/{unknown}").status_code == 404
    answered = world.client.post(f"/api/agent/runs/{unknown}/answer", json={"message": "hola"})
    assert answered.status_code == 404


def _stored_state(world, run_id: str) -> dict:
    return world.connection.execute(
        text("select state_json from agent_run where id = cast(:id as uuid)"),
        {"id": run_id},
    ).scalar_one()


def _assert_origin_not_persisted(state: dict) -> None:
    assert "_query" not in state
    dumped = json.dumps(state, ensure_ascii=False)
    assert "latitude" not in dumped
    assert "longitude" not in dumped


def test_completed_run_never_persists_the_exact_origin(world):
    response = world.client.post("/api/agent/runs", json=run_body(FIVE_ITEMS, policy="default"))
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "completed"

    _assert_origin_not_persisted(_stored_state(world, run["run_id"]))


def test_resumed_run_strips_the_query_once_it_completes(world):
    paused = world.client.post(
        "/api/agent/runs",
        json=run_body([item("pollo preparado", "vague", "1", "kg")], policy="default"),
    ).json()
    assert paused["status"] == "waiting_shopper"

    # While paused the exact origin is kept so `/answer` can re-optimize, but the payload
    # nested in `_query` never carries it.
    paused_state = _stored_state(world, paused["run_id"])
    assert paused_state["_query"]["origin"]["lat"] == pytest.approx(42.5987)
    assert paused_state["_query"]["origin"]["lon"] == pytest.approx(-5.5671)
    assert "origin" not in paused_state["_query"]["payload"]

    resumed = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer",
        json={"message": "quiero pechuga de pollo"},
    ).json()
    assert resumed["status"] == "completed"

    _assert_origin_not_persisted(_stored_state(world, paused["run_id"]))


@pytest.mark.parametrize(
    ("kind", "bought_after"),
    [
        ("option_index", []),  # the only option is "Dejar sin comprar": the line is skipped
        ("canonical_id", ["Pollo entero"]),
        ("choice_label", ["Pollo entero + Pechugas enteras de pollo"]),
    ],
)
def test_answering_a_paused_run_with_a_structured_choice(world, kind, bought_after):
    paused = _pause_on_the_vague_line(world)
    skip = {"label": "Dejar sin comprar", "action": "skip"}
    assert paused["pending_question"]["options"] == [skip]
    answer = {
        "option_index": {"option_index": 0},
        "canonical_id": {"canonical_id": _canonical_id(world, "Pollo entero")},
        "choice_label": {"choice_label": "Pollo"},
    }[kind]

    resumed = world.client.post(f"/api/agent/runs/{paused['run_id']}/answer", json=answer)
    assert resumed.status_code == 200
    final = resumed.json()

    assert final["status"] == "completed"
    assert final["pending_question"] is None
    assert final["steps_count"] == 1
    # The plan was re-optimized with the answer and still carries the live route.
    recommendation = final["recommendation"]
    assert recommendation is not None
    assert recommendation["route"]
    assert _bought(final) == ["Leche semidesnatada Hacendado", *bought_after]
    assert recommendation["total_cost"] != "0"

    stored = _stored_state(world, paused["run_id"])
    assert "route" not in json.dumps(stored)
    _assert_origin_not_persisted(stored)
    reread = world.client.get(f"/api/agent/runs/{paused['run_id']}").json()
    assert reread["recommendation"]["route"] == []
    assert _without_route(reread) == _without_route(final)


def test_option_index_out_of_range_is_rejected_and_the_run_keeps_waiting(world):
    paused = _pause_on_the_vague_line(world)
    options = paused["pending_question"]["options"]

    for index in (len(options), 5):
        rejected = world.client.post(
            f"/api/agent/runs/{paused['run_id']}/answer", json={"option_index": index}
        )
        assert rejected.status_code == 422

    still = world.client.get(f"/api/agent/runs/{paused['run_id']}").json()
    assert still["status"] == "waiting_shopper"
    assert still["steps"] == paused["steps"]


def test_unknown_canonical_is_asked_again_while_a_real_one_is_accepted(world):
    paused = _pause_on_the_vague_line(world)
    unknown = _canonical_id(world, "Pollo entero") + 10_000

    asked_again = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer", json={"canonical_id": unknown}
    )
    assert asked_again.status_code == 200
    again = asked_again.json()
    assert again["status"] == "waiting_shopper"
    assert again["pending_question"]["line_index"] == 1
    assert again["recommendation"] is None
    assert [step["step_number"] for step in again["steps"]] == list(
        range(1, again["steps_count"] + 1)
    )

    accepted = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer",
        json={"canonical_id": _canonical_id(world, "Pollo entero")},
    )
    assert accepted.status_code == 200
    final = accepted.json()
    assert final["status"] == "completed"
    assert _bought(final) == ["Leche semidesnatada Hacendado", "Pollo entero"]


def test_run_response_carries_the_route_but_the_stored_state_never_does(world):
    response = world.client.post("/api/agent/runs", json=run_body(FIVE_ITEMS, policy="default"))
    assert response.status_code == 200
    run = response.json()

    route = run["recommendation"]["route"]
    assert route
    stored = _stored_state(world, run["run_id"])
    # The recommendation is kept for later reads, but without its route (NFR-06).
    assert stored["_recommendation"]["total_cost"] == run["recommendation"]["total_cost"]
    assert "route" not in stored["_recommendation"]
    assert "route" not in json.dumps(stored)
    _assert_origin_not_persisted(stored)


def test_unknown_policy_is_rejected_with_422(world):
    response = world.client.post("/api/agent/runs", json=run_body(FIVE_ITEMS, policy="unknown"))
    assert response.status_code == 422


def test_answering_a_completed_run_returns_409(world):
    completed = world.client.post(
        "/api/agent/runs", json=run_body(FIVE_ITEMS, policy="default")
    ).json()
    assert completed["status"] == "completed"

    response = world.client.post(
        f"/api/agent/runs/{completed['run_id']}/answer", json={"message": "hola"}
    )
    assert response.status_code == 409


# -- cumulative conversation (E5) -----------------------------------------

ORIGIN = {"lat": 42.5987, "lon": -5.5671}
# Milk is only sold by Mercadona and rice only by Carrefour: the first plan uses both chains.
MILK_AND_RICE_ITEMS = [
    item("leche semidesnatada", "leche", "2", "l"),
    item("arroz redondo", "arroz", "1", "kg"),
]


def _say(world, run_id: str, message: str, key: str, *, origin: dict | None = ORIGIN):
    """One more message on a run, with the policy choosing `key`."""
    scripted = ScriptedPolicy([key])
    world.client.app.dependency_overrides[get_agent_policy] = lambda: scripted
    body: dict = {"message": message}
    if origin is not None:
        body["origin"] = origin
    return world.client.post(f"/api/agent/runs/{run_id}/message", json=body)


def _first_turn(world) -> dict:
    response = world.client.post(
        "/api/agent/runs", json=run_body(MILK_AND_RICE_ITEMS, policy="default")
    )
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "completed"
    assert set(_bought(run)) == {"Leche semidesnatada Hacendado", "Arroz redondo Carrefour"}
    return run


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for inner in value.values() for key in _keys(inner)}
    if isinstance(value, list):
        return {key for inner in value for key in _keys(inner)}
    return set()


def _assert_no_origin_or_route(state: dict) -> None:
    assert not _keys(state) & {"origin", "route", "latitude", "longitude", "_query"}
    dumped = json.dumps(state, ensure_ascii=False)
    assert "42.5987" not in dumped
    assert "-5.5671" not in dumped


def test_messages_accumulate_changes_and_never_store_the_origin(world):
    first = _first_turn(world)
    run_id = first["run_id"]

    second = _say(world, run_id, "sin Mercadona", "excluir_cadena:0")
    assert second.status_code == 200
    turn2 = second.json()
    assert turn2["run_id"] == run_id
    assert turn2["status"] == "completed"
    assert turn2["excluded_chains"] == ["mercadona"]
    assert turn2["buyer_summary"].startswith("He excluido Mercadona del plan.")
    assert turn2["recommendation"]["route"]
    assert _bought(turn2) == ["Arroz redondo Carrefour"]

    third = _say(world, run_id, "en 1 tienda", "cambiar_max_tiendas:1")
    assert third.status_code == 200
    turn3 = third.json()
    # Mercadona stays excluded and the store limit is added on top of it.
    assert turn3["excluded_chains"] == ["mercadona"]
    assert turn3["max_stores"] == 1
    assert turn3["buyer_summary"].startswith("He limitado la compra a 1 tienda.")
    assert turn3["recommendation"]["route"]
    assert _bought(turn3) == ["Arroz redondo Carrefour"]
    assert [step["step_number"] for step in turn3["steps"]] == [1, 2]
    assert turn3["steps_count"] == 2

    _assert_no_origin_or_route(_stored_state(world, run_id))
    assert _stored_state(world, run_id)["_plan_spec"]["max_stores"] == 1

    # A later read serves the stored plan, without a route.
    reread = world.client.get(f"/api/agent/runs/{run_id}").json()
    assert reread["recommendation"]["route"] == []
    assert reread["excluded_chains"] == ["mercadona"]


def test_a_message_can_change_the_mode_and_the_list_after_other_changes(world):
    run_id = _first_turn(world)["run_id"]

    _say(world, run_id, "sin Mercadona", "excluir_cadena:0")
    car = _say(world, run_id, "mejor voy en coche", "cambiar_modo")
    assert car.status_code == 200
    assert car.json()["mode"] == "car"
    assert car.json()["excluded_chains"] == ["mercadona"]
    assert car.json()["buyer_summary"].startswith("He cambiado el desplazamiento a coche.")

    # The line removed earlier left a gap in the indexes: later turns must still find the rest.
    removed = _say(world, run_id, "quita el arroz", "quitar_linea:1")
    assert removed.status_code == 200
    assert removed.json()["mode"] == "car"
    _assert_no_origin_or_route(_stored_state(world, run_id))


def test_explaining_in_a_message_serves_the_current_plan_with_its_route(world):
    run_id = _first_turn(world)["run_id"]

    explained = _say(world, run_id, "¿por qué este plan?", "explicar")

    assert explained.status_code == 200
    run = explained.json()
    assert "El plan actual compra en" in run["buyer_summary"]
    assert run["recommendation"]["route"]


def test_previous_run_id_inherits_the_accumulated_state(world):
    first = _first_turn(world)
    scripted = ScriptedPolicy(["excluir_cadena:0", "cambiar_max_tiendas:1"])
    world.client.app.dependency_overrides[get_agent_policy] = lambda: scripted

    second = world.client.post(
        "/api/agent/runs",
        json=run_body(
            MILK_AND_RICE_ITEMS, previous_run_id=first["run_id"], shopper_message="sin Mercadona"
        ),
    )
    assert second.status_code == 200
    turn2 = second.json()
    assert turn2["run_id"] != first["run_id"]
    assert turn2["excluded_chains"] == ["mercadona"]
    assert turn2["recommendation"]["route"]
    assert turn2["buyer_summary"].startswith("He excluido Mercadona del plan.")

    third = world.client.post(
        "/api/agent/runs",
        json=run_body(
            MILK_AND_RICE_ITEMS, previous_run_id=turn2["run_id"], shopper_message="en 1 tienda"
        ),
    )
    assert third.status_code == 200
    turn3 = third.json()
    assert turn3["excluded_chains"] == ["mercadona"]
    assert turn3["max_stores"] == 1
    assert turn3["recommendation"]["route"]
    assert turn3["steps_count"] == 1
    _assert_no_origin_or_route(_stored_state(world, turn3["run_id"]))


def test_previous_run_id_without_a_message_serves_the_same_plan_live(world):
    first = _first_turn(world)

    again = world.client.post(
        "/api/agent/runs", json=run_body(MILK_AND_RICE_ITEMS, previous_run_id=first["run_id"])
    )

    assert again.status_code == 200
    run = again.json()
    assert run["steps_count"] == 0
    assert run["recommendation"]["route"]
    assert _bought(run) == _bought(first)


def test_previous_run_id_that_does_not_exist_returns_404(world):
    response = world.client.post(
        "/api/agent/runs", json=run_body(MILK_AND_RICE_ITEMS, previous_run_id=str(uuid4()))
    )
    assert response.status_code == 404


def test_a_message_without_origin_on_a_completed_run_returns_a_spanish_422(world):
    run_id = _first_turn(world)["run_id"]

    response = _say(world, run_id, "sin Mercadona", "excluir_cadena:0", origin=None)

    assert response.status_code == 422
    assert "origen" in response.json()["detail"]
    # Nothing happened: the run is still completed and untouched.
    assert world.client.get(f"/api/agent/runs/{run_id}").json()["status"] == "completed"


def test_a_message_on_an_unknown_run_returns_404(world):
    response = _say(world, str(uuid4()), "hola", "no_hacer_nada")

    assert response.status_code == 404


def test_a_message_is_bounded(world):
    run_id = _first_turn(world)["run_id"]

    too_long = world.client.post(
        f"/api/agent/runs/{run_id}/message", json={"message": "x" * 1001, "origin": ORIGIN}
    )
    empty = world.client.post(
        f"/api/agent/runs/{run_id}/message", json={"message": "", "origin": ORIGIN}
    )

    assert too_long.status_code == 422
    assert empty.status_code == 422


def test_a_message_on_a_paused_run_answers_its_question_with_the_stored_origin(world):
    paused = _pause_on_the_vague_line(world)

    # No origin travels with the message: the paused run still keeps its own.
    resumed = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/message", json={"message": "quiero pechuga de pollo"}
    )

    assert resumed.status_code == 200
    final = resumed.json()
    assert final["status"] == "completed"
    assert any("pollo" in name.lower() for name in _bought(final))
    _assert_origin_not_persisted(_stored_state(world, paused["run_id"]))


def test_a_message_that_cannot_be_applied_keeps_the_accumulated_plan(world):
    run_id = _first_turn(world)["run_id"]
    _say(world, run_id, "sin Mercadona", "excluir_cadena:0")

    # Excluding the last chain left is refused by validation; the earlier exclusion stays.
    refused = _say(world, run_id, "sin Carrefour", "excluir_cadena:0")

    assert refused.status_code == 200
    run = refused.json()
    assert run["status"] == "completed"
    assert run["excluded_chains"] == ["mercadona"]
    assert run["steps"][-1]["error"]
    assert run["recommendation"]["route"]
