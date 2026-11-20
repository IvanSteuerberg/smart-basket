"""Variant-key guard and LLM-verified catalog policy (iteration 15 E1, ADR 0024)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from smart_basket.agent.catalog_agent import (
    CatalogActionKind,
    CatalogCandidate,
    CatalogObservation,
    CatalogObservationKind,
    CatalogState,
    build_catalog_harness,
    build_pure_catalog_executors,
)
from smart_basket.agent.catalog_policies import (
    LLMVerifiedCatalogPolicy,
    variants_compatible,
)
from smart_basket.agent.core import HarnessConfig
from smart_basket.llm.base import LLMError


class FakeVerifier:
    """Deterministic `LLMProvider`: replays failures, then one fixed `action_key`."""

    name = "fake"
    model = "fake-verifier"

    def __init__(
        self, answer: str = "asignar_canonico:0", *, errors: Sequence[Exception] = ()
    ) -> None:
        self.answer = answer
        self.errors = list(errors)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, user, schema))
        if self.errors:
            raise self.errors.pop(0)
        return {"action_key": self.answer}

    def generate_text(self, prompt: str) -> str:  # pragma: no cover - unused by the policy
        return ""


def _candidates() -> tuple[CatalogCandidate, ...]:
    return (
        CatalogCandidate(
            key="asignar_canonico:0",
            kind=CatalogActionKind.ASIGNAR_CANONICO,
            args={
                "product_id": 1,
                "canonical_id": 10,
                "canonical_name": "Leche semidesnatada sin lactosa",
                "confidence": 0.81,
            },
            label="Asignar al canónico candidato 0",
        ),
        CatalogCandidate(
            key="asignar_canonico:1",
            kind=CatalogActionKind.ASIGNAR_CANONICO,
            args={
                "product_id": 1,
                "canonical_id": 11,
                "canonical_name": "Leche semidesnatada",
                "confidence": 0.79,
            },
            label="Asignar al canónico candidato 1",
        ),
        CatalogCandidate(
            key="enviar_a_revision",
            kind=CatalogActionKind.ENVIAR_A_REVISION,
            args={"product_id": 1, "reason": "Leche semidesnatada sin lactosa sin canónico"},
            label="Enviar a revisión",
        ),
        CatalogCandidate(
            key="no_hacer_nada",
            kind=CatalogActionKind.NO_HACER_NADA,
            args={},
            label="No hacer nada",
        ),
    )


def _observation() -> CatalogObservation:
    return CatalogObservation(
        kind=CatalogObservationKind.UNMATCHED_PRODUCT,
        summary="Leche semidesnatada sin lactosa Dia 1 l sin canónico asignado",
        product_id=1,
        details={
            "product_name": "Leche semidesnatada sin lactosa Dia 1 l",
            "category_name": "Lácteos",
            "candidate_canonicals": [
                {
                    "canonical_id": 10,
                    "canonical_name": "Leche semidesnatada sin lactosa",
                    "category_key": "leche",
                    "variant_key": "sin_lactosa",
                    "confidence": 0.81,
                },
                {
                    "canonical_id": 11,
                    "canonical_name": "Leche semidesnatada",
                    "category_key": "leche",
                    "variant_key": "",
                    "confidence": 0.79,
                },
            ],
        },
    )


@pytest.mark.parametrize(
    ("product_name", "canonical_key", "expected"),
    [
        ("Leche semidesnatada sin lactosa Dia 1 l", "", False),
        ("Leche semidesnatada sin lactosa Dia 1 l", "sin_lactosa", True),
        ("Leche semidesnatada Dia 1 l", "sin_lactosa", False),
        ("Yogur fresa Dia 4x125g", "", False),
        ("Yogur sabor fresa Dia 4x125g", "sabor:fresa", True),
        ("Pan integral Dia", "integral", True),
        ("Pan integral Dia", "sin_gluten", False),
        ("Cerveza sin alcohol Dia 0,0", "sin_alcohol", True),
        ("Leche semidesnatada Dia 1 l", "", True),
        ("Leche desnatada Dia 1 l", "semidesnatada", False),
        ("Leche desnatada Dia 1 l", "desnatada", True),
        ("Atún en aceite de oliva", "en_aceite_girasol", False),
    ],
)
def test_variants_compatible_guards_sibling_variants(
    product_name: str, canonical_key: str, expected: bool
):
    assert variants_compatible(product_name, canonical_key) is expected


def test_the_policy_sends_a_spanish_prompt_with_a_closed_enum():
    provider = FakeVerifier("asignar_canonico:0")
    policy = LLMVerifiedCatalogPolicy(provider, model_name="gemini-3.5-flash-lite")

    decision = policy.choose(CatalogState(), _observation(), _candidates())

    assert decision.action_key == "asignar_canonico:0"
    assert decision.confidence == 0.95
    assert decision.model_name == "gemini-3.5-flash-lite"
    system, user, schema = provider.calls[0]
    assert "intercambiable" in system
    assert "Leche semidesnatada sin lactosa Dia 1 l" in user
    assert "Lácteos" in user
    assert "asignar_canonico:0" in user
    assert "Leche semidesnatada sin lactosa" in user
    assert "categoría" in user
    assert schema["properties"]["action_key"]["enum"] == [item.key for item in _candidates()]


def test_the_policy_routes_to_review_when_the_model_cannot_verify():
    provider = FakeVerifier("enviar_a_revision")
    policy = LLMVerifiedCatalogPolicy(provider)

    decision = policy.choose(CatalogState(), _observation(), _candidates())

    assert decision.action_key == "enviar_a_revision"
    assert decision.confidence == 1.0
    assert decision.model_name == "fake-verifier"


def test_a_failed_verification_degrades_to_review_through_the_harness():
    provider = FakeVerifier(errors=[LLMError("gemini request failed: 500")] * 3)
    policy = LLMVerifiedCatalogPolicy(provider, retry_delays=())
    harness = build_catalog_harness(HarnessConfig(max_steps=4))

    result = harness.run(
        CatalogState(observations=(_observation(),)),
        policy,
        build_pure_catalog_executors(),
    )

    assert len(provider.calls) == 3
    assert result.steps[0].used_default is True
    assert [item["product_id"] for item in result.state.review_items] == [1]


def test_a_rate_limit_is_retried_with_the_configured_backoff(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr(
        "smart_basket.agent.catalog_policies.time.sleep", lambda delay: sleeps.append(delay)
    )
    provider = FakeVerifier(
        errors=[
            LLMError("gemini request failed: 429 Too Many Requests"),
            LLMError("gemini request failed: 429 Too Many Requests"),
        ]
    )
    policy = LLMVerifiedCatalogPolicy(provider, retry_delays=(5.0, 15.0))

    decision = policy.choose(CatalogState(), _observation(), _candidates())

    assert decision.action_key == "asignar_canonico:0"
    assert len(provider.calls) == 3
    assert sleeps == [5.0, 15.0]


def test_clusters_keep_the_deterministic_leaf_path():
    leaf = CatalogCandidate(
        key="proponer_hoja_nueva:0",
        kind=CatalogActionKind.PROPONER_HOJA_NUEVA,
        args={"label": "Tahini", "signals": ["embedding", "category"], "product_ids": [1, 2, 3]},
        label="Proponer una hoja nueva para el grupo 0",
    )
    review = CatalogCandidate(
        key="enviar_a_revision",
        kind=CatalogActionKind.ENVIAR_A_REVISION,
        args={"product_id": None, "reason": "grupo sin canónico"},
        label="Enviar a revisión",
    )
    observation = CatalogObservation(
        kind=CatalogObservationKind.CLUSTER_CANDIDATE,
        summary="3 productos sin canónico forman un grupo",
        details={"clusters": []},
    )
    provider = FakeVerifier()

    decision = LLMVerifiedCatalogPolicy(provider).choose(
        CatalogState(), observation, (leaf, review)
    )

    assert decision.action_key == "proponer_hoja_nueva:0"
    assert decision.model_name is None
    assert provider.calls == []
