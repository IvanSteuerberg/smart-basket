"""Persistence of the agent trace against a real PostgreSQL, per the criteria of task E1.

Skipped unless TEST_DATABASE_URL points at a disposable database (CI sets it). Every test runs
inside a transaction that is rolled back, so the trace rows never survive the test.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from smart_basket.agent import trace
from smart_basket.db.migrate import alembic_config

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]

FINISHED = datetime(2026, 11, 19, 12, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine():
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """A session whose work is always rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as db:
            yield db
        transaction.rollback()


def test_create_run_returns_a_uuidv7_and_get_run_round_trips_it(session):
    run_id = trace.create_run(
        session,
        agent_name="recommender",
        policy_name="rules-first",
        model_name="kev-4b",
        state_json={"phase": "perceive", "exceptions": [2]},
    )

    assert str(run_id)[14] == "7"
    run = trace.get_run(session, run_id)
    assert run is not None
    assert run.id == run_id
    assert run.agent_name == "recommender"
    assert run.policy_name == "rules-first"
    assert run.model_name == "kev-4b"
    assert run.recommendation_id is None
    assert run.state_json == {"phase": "perceive", "exceptions": [2]}
    assert run.status == "running"
    assert run.steps_count == 0
    assert run.total_latency_ms == 0
    assert run.finished_at is None
    assert run.steps == ()


def test_get_run_returns_none_for_an_unknown_id(session):
    assert trace.get_run(session, uuid4()) is None


def test_append_step_round_trips_and_get_run_orders_steps(session):
    run_id = trace.create_run(session, agent_name="recommender", policy_name="rules-first")
    second = trace.append_step(
        session,
        run_id=run_id,
        step_number=2,
        observation_json={"kind": "near_tie", "gap": 0.03},
        candidates_json=[{"action": "ask_shopper", "score": 0.8}],
        chosen_action="ask_shopper",
        confidence=0.42,
        probabilities_json={"ask_shopper": 0.42, "try_other_scenario": 0.58},
        retries=2,
        used_default=True,
        error="schema mismatch on the first two attempts",
        latency_ms=310,
    )
    first = trace.append_step(
        session,
        run_id=run_id,
        step_number=1,
        observation_json={"kind": "unresolved_line", "line": 3},
        candidates_json=[{"action": "search_substitute"}],
        chosen_action="search_substitute",
        action_args_json={"line": 3, "category": "leche"},
        result_json={"found": 2},
        latency_ms=190,
    )

    assert first != second
    run = trace.get_run(session, run_id)
    assert run is not None
    assert [step.step_number for step in run.steps] == [1, 2]
    assert [step.id for step in run.steps] == [first, second]

    first_step, second_step = run.steps
    assert first_step.run_id == run_id
    assert first_step.observation_json == {"kind": "unresolved_line", "line": 3}
    assert first_step.candidates_json == [{"action": "search_substitute"}]
    assert first_step.chosen_action == "search_substitute"
    assert first_step.action_args_json == {"line": 3, "category": "leche"}
    assert first_step.confidence is None
    assert first_step.probabilities_json is None
    assert first_step.retries == 0
    assert first_step.used_default is False
    assert first_step.result_json == {"found": 2}
    assert first_step.latency_ms == 190
    assert first_step.error is None

    assert second_step.observation_json == {"kind": "near_tie", "gap": 0.03}
    assert second_step.candidates_json == [{"action": "ask_shopper", "score": 0.8}]
    assert second_step.confidence == 0.42
    assert second_step.probabilities_json == {"ask_shopper": 0.42, "try_other_scenario": 0.58}
    assert second_step.retries == 2
    assert second_step.used_default is True
    assert second_step.result_json == {}
    assert second_step.latency_ms == 310
    assert second_step.error == "schema mismatch on the first two attempts"


def test_update_run_changes_the_final_state_and_keeps_the_rest(session):
    run_id = trace.create_run(session, agent_name="recommender", policy_name="rules-first")

    trace.update_run(session, run_id, status="waiting_shopper", state_json={"question": "coche?"})
    paused = trace.get_run(session, run_id)
    assert paused is not None
    assert paused.status == "waiting_shopper"
    assert paused.state_json == {"question": "coche?"}
    assert paused.steps_count == 0

    trace.update_run(
        session,
        run_id,
        state_json={"question": None},
        status="completed",
        steps_count=3,
        total_latency_ms=1250,
        finished_at=FINISHED,
    )
    run = trace.get_run(session, run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.state_json == {"question": None}
    assert run.steps_count == 3
    assert run.total_latency_ms == 1250
    assert run.finished_at == FINISHED
    assert run.updated_at >= run.created_at


def test_recommendation_id_is_nullable_and_references_a_real_recommendation(session):
    anonymous = trace.create_run(session, agent_name="recommender", policy_name="rules-first")
    assert trace.get_run(session, anonymous).recommendation_id is None

    recommendation_id = session.execute(
        text(
            "insert into recommendation (data_as_of, engine_version, travel_mode, max_stores, "
            "lambda, request, result, total_cost, minutes) values "
            "(now(), 'basket-engine/1.0.0', 'walk', 2, 0.15, '{}', '{}', 10, 12) returning id"
        )
    ).scalar_one()
    linked = trace.create_run(
        session,
        agent_name="recommender",
        policy_name="rules-first",
        recommendation_id=recommendation_id,
    )

    assert trace.get_run(session, linked).recommendation_id == recommendation_id
