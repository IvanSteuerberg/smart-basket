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

    fetched = world.client.get(f"/api/agent/runs/{run['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == run


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

    resumed = world.client.post(
        f"/api/agent/runs/{paused['run_id']}/answer",
        json={"message": "quiero pechuga de pollo"},
    )
    assert resumed.status_code == 200
    final = resumed.json()
    assert final["status"] == "completed"
    assert final["pending_question"] is None
    assert final["steps_count"] >= 2
    assert [step["step_number"] for step in final["steps"]] == list(
        range(1, final["steps_count"] + 1)
    )
    assert final["steps"][-1]["observation"]["kind"] == "shopper_request"

    fetched = world.client.get(f"/api/agent/runs/{paused['run_id']}").json()
    assert fetched["status"] == "completed"
    assert fetched["steps"] == final["steps"]


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
    ("answer", "expected_message"),
    [
        ({"option_index": 1}, "Opción 2"),
        ({"canonical_id": 4242}, "Producto 4242"),
    ],
)
def test_answering_a_paused_run_with_a_structured_choice(world, answer, expected_message):
    paused = world.client.post(
        "/api/agent/runs",
        json=run_body([item("pollo preparado", "vague", "1", "kg")], policy="default"),
    ).json()
    assert paused["status"] == "waiting_shopper"

    resumed = world.client.post(f"/api/agent/runs/{paused['run_id']}/answer", json=answer)
    assert resumed.status_code == 200
    final = resumed.json()
    assert final["status"] == "completed"
    assert final["steps"][-1]["observation"]["kind"] == "shopper_request"
    assert final["steps"][-1]["observation"]["details"]["message"] == expected_message


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
