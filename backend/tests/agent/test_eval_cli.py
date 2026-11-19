"""Offline scenario evaluator: digest, Wilson interval, state verdicts and ablation (ADR 0022)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest

from smart_basket.agent.actions import CandidateAction, valid_actions
from smart_basket.agent.core import DefaultPolicy, PolicyDecision, RunResult, StepRecord
from smart_basket.agent.eval_cli import (
    compare_ablation,
    evaluate_verdict,
    load_scenarios,
    main,
    percentile,
    run_evaluation,
    wilson_interval,
)
from smart_basket.agent.observations import Observation
from smart_basket.agent.state import AgentState, LineState, RunStatus

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
EXPECTED_SHA256 = "e4f2b4e7ba30fcf95c48bfe8180f1b012c9609a4f3c6d834894f1d44f9c4ac0e"


def _state() -> AgentState:
    return AgentState(
        lines=(
            LineState(
                index=0,
                raw_text="leche",
                canonical_name="Leche semidesnatada",
                quantity=Decimal("1"),
                unit="l",
            ),
            LineState(index=1, raw_text="pan", canonical_name="Pan de pueblo"),
        )
    )


def _step(chosen: str | None) -> StepRecord:
    return StepRecord(
        step_number=1,
        observation=None,
        candidates=(),
        chosen_action=chosen,
        action_args={},
        confidence=None,
        probabilities=None,
        retries=0,
        result=None,
        latency_ms=1.0,
        error=None,
        used_default=False,
    )


def _result(
    initial: AgentState,
    chosen: str | None = None,
    *,
    final: AgentState | None = None,
    status: RunStatus = RunStatus.COMPLETED,
) -> RunResult:
    steps = (_step(chosen),) if chosen is not None else ()
    return RunResult(
        state=final if final is not None else initial,
        steps=steps,
        status=status,
        total_latency_ms=2.0,
        policy_name="test",
        model_name=None,
    )


def _scenario(
    verdict: dict[str, Any],
    *,
    gold: str = "preguntar",
    also_ok: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "id": "x01",
        "group": "vague_line",
        "expected": {"gold_action": gold, "also_ok": list(also_ok), "verdict": verdict},
    }


def _observation(scenario: dict[str, Any]) -> Observation:
    return AgentState.from_dict(scenario["state"]).observations[0]


class OraclePolicy:
    """Deterministic oracle: replays the right concrete candidate key for each observation.

    `ScriptedPolicy` replays one finite script for a single run, so it cannot follow the gold
    answer of 41 different scenarios across `k` repetitions; this stateless oracle can. The key
    also pins the right line when the gold action is offered once per line.
    """

    name = "oracle"

    def __init__(self, key_by_observation: dict[tuple[str, str], str]) -> None:
        self._keys = key_by_observation

    def choose(
        self,
        state: AgentState,
        observation: Observation,
        candidates: Sequence[CandidateAction],
    ) -> PolicyDecision:
        return PolicyDecision(action_key=self._keys[(observation.kind.value, observation.summary)])


def _oracle_key(scenario: dict[str, Any]) -> str | None:
    """The candidate key the oracle should play, or None when the gold action is not offered.

    When several candidates share the gold kind (one per line), the oracle also avoids every
    line the scenario protects, which is how a shopper request names its target line.
    """
    state = AgentState.from_dict(scenario["state"])
    observation = state.observations[0]
    gold = scenario["expected"]["gold_action"]
    protected = set((scenario["expected"].get("verdict") or {}).get("must_not_modify_lines") or ())
    candidates = [item for item in valid_actions(state, observation) if item.kind.value == gold]
    if not candidates:
        return None
    for candidate in candidates:
        target = candidate.args.get("line_index")
        if target is None or target not in protected:
            return candidate.key
    return candidates[0].key


def _pickable_scenarios(
    scenarios: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Scenarios whose gold action is actually offered for their frozen observation."""
    return [scenario for scenario in scenarios if _oracle_key(scenario) is not None]


def test_cli_entrypoint_resolves_to_the_evaluator() -> None:
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}

    assert scripts.get("smart-basket-agent-eval") == "smart_basket.agent.eval_cli:main"


def test_load_scenarios_matches_the_frozen_digest() -> None:
    scenarios, digest = load_scenarios(SCENARIOS_DIR)

    assert len(scenarios) == 41
    assert digest == EXPECTED_SHA256
    assert len({scenario["id"] for scenario in scenarios}) == 41


@pytest.mark.parametrize(
    ("successes", "total", "low", "high"),
    [
        (0, 0, 0.0, 0.0),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
        (17, 20, 0.6396, 0.9476),
    ],
)
def test_wilson_interval_edge_cases(successes: int, total: int, low: float, high: float) -> None:
    lower, upper = wilson_interval(successes, total)

    assert lower == pytest.approx(low, abs=1e-3)
    assert upper == pytest.approx(high, abs=1e-3)


def test_percentile_handles_empty_single_and_interpolated_values() -> None:
    assert percentile([], 50.0) == 0.0
    assert percentile([5.0], 95.0) == 5.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50.0) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 95.0) == pytest.approx(3.85)


def test_evaluate_verdict_accepts_the_gold_action() -> None:
    state = _state()
    scenario = _scenario({"expected_status": "completed", "must_not_modify_lines": [0, 1]})

    row = evaluate_verdict(scenario, state, _result(state, "preguntar"))

    assert row["strict_ok"] is True
    assert row["action_ok"] is True
    assert row["verdict_ok"] is True
    assert row["task_solved"] is True
    assert row["failures"] == []


def test_evaluate_verdict_catches_a_forbidden_action() -> None:
    state = _state()
    final = replace(state, lines=(replace(state.lines[0], brand="Hacendado"), state.lines[1]))
    scenario = _scenario({"forbidden_actions": ["cambiar_marca"]}, gold="preguntar")

    row = evaluate_verdict(scenario, state, _result(state, "cambiar_marca:0", final=final))

    assert row["action_ok"] is False
    assert row["task_solved"] is False
    assert any("forbidden action" in failure for failure in row["failures"])


def test_evaluate_verdict_catches_a_modified_protected_line() -> None:
    state = _state()
    final = replace(
        state,
        lines=(replace(state.lines[0], canonical_name="Leche entera"), state.lines[1]),
    )
    scenario = _scenario({"must_not_modify_lines": [0]})

    row = evaluate_verdict(scenario, state, _result(state, "preguntar", final=final))

    assert row["task_solved"] is False
    assert any("protected line 0 modified" in failure for failure in row["failures"])


def test_evaluate_verdict_catches_an_unrequested_change() -> None:
    state = _state()
    final = replace(
        state,
        lines=(replace(state.lines[0], quantity=Decimal("9")), state.lines[1]),
    )
    scenario = _scenario({"zero_changes": True}, gold="no_hacer_nada")

    row = evaluate_verdict(scenario, state, _result(state, "no_hacer_nada", final=final))

    assert row["changed"] is True
    assert row["task_solved"] is False
    assert any("state changed" in failure for failure in row["failures"])


def test_evaluate_verdict_catches_a_wrong_mode() -> None:
    state = _state()
    scenario = _scenario({"expected_mode": "car"}, gold="cambiar_modo")

    row = evaluate_verdict(scenario, state, _result(state, "cambiar_modo"))

    assert row["task_solved"] is False
    assert any("mode" in failure for failure in row["failures"])


def test_evaluate_verdict_catches_a_missing_pending_question() -> None:
    state = _state()
    scenario = _scenario({"expected_status": "waiting_shopper", "must_ask": True}, gold="preguntar")

    row = evaluate_verdict(scenario, state, _result(state, "preguntar"))

    assert row["task_solved"] is False
    assert "no pending question" in row["failures"]
    assert "run did not wait for the shopper" in row["failures"]


def test_evaluate_verdict_checks_excluded_chains() -> None:
    state = _state()
    final = replace(state, excluded_chains=("Lidl",))
    scenario = _scenario({"expected_excluded_chains": ["lidl"]}, gold="excluir_cadena")

    row = evaluate_verdict(scenario, state, _result(state, "excluir_cadena:0", final=final))

    assert row["strict_ok"] is True
    assert row["task_solved"] is True


def test_default_policy_evaluation_writes_jsonl_and_summary(tmp_path: Path) -> None:
    scenarios, digest = load_scenarios(SCENARIOS_DIR)
    output = tmp_path / "runs.jsonl"

    summary = run_evaluation(scenarios, digest, DefaultPolicy(), k=2, output_jsonl=output)

    assert summary["scenario_count"] == 41
    assert summary["scenario_sha256"] == EXPECTED_SHA256
    assert summary["policy_name"] == "default"
    assert summary["model_name"] is None
    assert summary["k"] == 2
    assert summary["overall"]["runs"] == 82
    assert summary["exceptions"]["scenario_count"] == 33
    assert summary["no_change_and_injection"]["scenario_count"] == 8
    assert summary["no_change_and_injection"]["unrequested_changes_count"] == 0
    assert summary["no_change_and_injection"]["zero_change_rate"] == 1.0

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 82
    assert set(Counter(row["scenario_id"] for row in rows).values()) == {2}
    required = {
        "scenario_id",
        "group",
        "chosen_action",
        "gold_action",
        "strict_ok",
        "action_ok",
        "task_solved",
        "changed",
        "failures",
        "latency_ms",
        "repetition",
        "trace",
    }
    assert required <= set(rows[0])


def test_oracle_policy_reaches_full_pass_k_and_ablation_drops() -> None:
    scenarios, digest = load_scenarios(SCENARIOS_DIR)
    pickable = _pickable_scenarios(scenarios)
    assert len(pickable) == 35

    key_by_observation = {
        (_observation(scenario).kind.value, _observation(scenario).summary): key
        for scenario in pickable
        if (key := _oracle_key(scenario)) is not None
    }
    assert len(key_by_observation) == len(pickable)

    oracle = run_evaluation(pickable, digest, OraclePolicy(key_by_observation), k=2)
    assert oracle["overall"]["solved_rate"] == 1.0
    assert oracle["overall"]["pass_at_k"] == 1.0
    assert oracle["exceptions"]["pass_at_k"] == 1.0
    assert oracle["no_change_and_injection"]["zero_change_rate"] == 1.0

    baseline = run_evaluation(pickable, digest, DefaultPolicy(), k=2)
    comparison = compare_ablation(oracle, baseline)

    assert comparison["exceptions_solved"]["drop_pp"] > 20.0
    assert comparison["targets"]["ablation_drop_20pp"] is True


def test_main_runs_the_default_policy(tmp_path: Path) -> None:
    output = tmp_path / "cli-runs.jsonl"
    summary = tmp_path / "cli-summary.json"

    exit_code = main(
        [
            "--scenarios-dir",
            str(SCENARIOS_DIR),
            "--policy",
            "default",
            "--k",
            "1",
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    )

    assert exit_code == 0
    assert len(output.read_text(encoding="utf-8").splitlines()) == 41
    assert json.loads(summary.read_text(encoding="utf-8"))["scenario_count"] == 41
