"""Pure core of the catalog agent (ADR 0022, iteration 14).

The catalog agent runs offline after every scrape: it assigns each scraped product to an
existing canonical product or, when no canonical fits, proposes a new leaf. It reuses the
shared perceive-act harness (`AgentHarness`) — its limits, retries, two-phase
`propose → validate → apply` and trace — with its own observation and action vocabulary,
candidate generation and conservative fallback policy.

ADR 0022 grades autonomy by risk: an assignment the agent is confident about is applied, but a
new leaf is only created without approval when **two independent signals agree** and **at
least three similar products** group under it. Those invariants are enforced by code in
`validate()`, never by the policy, so a wrong model answer degrades to a review item instead of
a wrong catalog write.

This module is pure: no database, no ORM and no network. Collectors, pgvector lookups and the
DB-backed executors live elsewhere.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from smart_basket.agent.core import (
    ActionExecutor,
    AgentHarness,
    HarnessConfig,
    PolicyDecision,
    Proposal,
)
from smart_basket.agent.observations import jsonable
from smart_basket.agent.state import RunStatus

#: Name the harness and the trace use for this agent.
CATALOG_AGENT_NAME = "catalog"

#: ADR 0022: a new leaf needs two independent signals that agree...
MIN_SIGNALS_FOR_NEW_LEAF = 2
#: ...and at least three similar products grouped under it.
MIN_PRODUCTS_FOR_NEW_LEAF = 3


class CatalogObservationKind(StrEnum):
    """The three catalog phenomena the agent reacts to."""

    UNMATCHED_PRODUCT = "unmatched_product"
    AMBIGUOUS_MATCH = "ambiguous_match"
    CLUSTER_CANDIDATE = "cluster_candidate"


class CatalogActionKind(StrEnum):
    """The four actions of the closed catalog-agent set."""

    ASIGNAR_CANONICO = "asignar_canonico"
    PROPONER_HOJA_NUEVA = "proponer_hoja_nueva"
    ENVIAR_A_REVISION = "enviar_a_revision"
    NO_HACER_NADA = "no_hacer_nada"


@dataclass(frozen=True, slots=True)
class CatalogObservation:
    """One phenomenon observed on a scraped product or on a proposed cluster.

    `details` carries the typed evidence the actions need: the candidate canonicals with their
    confidence, or the cluster's signals and product identifiers. It may hold rich Python
    values in memory; serialization normalizes it to JSON-native primitives (see `jsonable`).
    """

    kind: CatalogObservationKind
    summary: str
    product_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
            "product_id": self.product_id,
            "details": jsonable(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CatalogObservation:
        return cls(
            kind=CatalogObservationKind(data["kind"]),
            summary=str(data["summary"]),
            product_id=_int_value(data.get("product_id")),
            details=dict(data.get("details") or {}),
        )


@dataclass(frozen=True, slots=True)
class CatalogCandidate:
    """One concrete option offered to the policy: a stable `key`, its kind and its arguments.

    Keys are opaque (`asignar_canonico:0`): untrusted product text travels only in `args`, so it
    can never forge a key. `to_dict()` matches the candidate contract of the shared harness.
    """

    key: str
    kind: CatalogActionKind
    args: dict[str, Any]
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "args": jsonable(self.args),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CatalogCandidate:
        return cls(
            key=str(data["key"]),
            kind=CatalogActionKind(data["kind"]),
            args=dict(data.get("args") or {}),
            label=str(data["label"]),
        )


@dataclass(frozen=True, slots=True)
class CatalogState:
    """Everything one catalog-agent run knows: pending observations and the effects so far.

    It exposes the same three fields the shared harness drives (`observations`,
    `steps_taken`, `status`), so `AgentHarness` runs it unchanged. `assignments`,
    `leaf_proposals` and `review_items` are the blackboard rows the run writes; `candidates`
    is the run-level context of canonical matches, used when an observation carries none.
    """

    observations: tuple[CatalogObservation, ...] = ()
    steps_taken: int = 0
    status: RunStatus = RunStatus.RUNNING
    assignments: tuple[dict[str, Any], ...] = ()
    leaf_proposals: tuple[dict[str, Any], ...] = ()
    review_items: tuple[dict[str, Any], ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()

    @property
    def applied_assignments(self) -> tuple[dict[str, Any], ...]:
        """Alias of `assignments`, the rows written to the blackboard."""
        return self.assignments

    @property
    def proposed_leaves(self) -> tuple[dict[str, Any], ...]:
        """Alias of `leaf_proposals`, the new leaves proposed by the run."""
        return self.leaf_proposals

    @property
    def review_queue(self) -> tuple[dict[str, Any], ...]:
        """Alias of `review_items`, the conflicts left for the author."""
        return self.review_items

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "steps_taken": self.steps_taken,
            "status": self.status.value,
            "assignments": jsonable(self.assignments),
            "leaf_proposals": jsonable(self.leaf_proposals),
            "review_items": jsonable(self.review_items),
            "candidates": jsonable(self.candidates),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CatalogState:
        return cls(
            observations=tuple(
                CatalogObservation.from_dict(item) for item in data.get("observations") or ()
            ),
            steps_taken=int(data.get("steps_taken", 0)),
            status=RunStatus(data.get("status", RunStatus.RUNNING.value)),
            assignments=_records(data.get("assignments")),
            leaf_proposals=_records(data.get("leaf_proposals")),
            review_items=_records(data.get("review_items")),
            candidates=_records(data.get("candidates")),
        )


def valid_catalog_actions(
    state: CatalogState, observation: CatalogObservation
) -> tuple[CatalogCandidate, ...]:
    """List the concrete catalog actions valid for `observation` in `state`.

    Keys are deterministic, unique and opaque (`asignar_canonico:0`, `proponer_hoja_nueva:0`):
    the index selects an entry of `details` and every untrusted text travels only in `args`.
    `no_hacer_nada` is always offered as the safe option.

    Candidate canonicals come from `details["candidate_canonicals"]`; when the observation
    carries none, the run-level `state.candidates` context is used. Clusters come from
    `details["clusters"]`, or from `details` itself when it already holds `signals` and
    `product_ids`.
    """
    details = observation.details
    candidates: list[CatalogCandidate] = []

    if observation.kind in (
        CatalogObservationKind.UNMATCHED_PRODUCT,
        CatalogObservationKind.AMBIGUOUS_MATCH,
    ):
        options = _mappings(details.get("candidate_canonicals")) or list(state.candidates)
        for index, option in enumerate(options):
            canonical_id = _int_value(option.get("canonical_id"))
            if canonical_id is None:
                continue
            candidates.append(
                CatalogCandidate(
                    key=f"{CatalogActionKind.ASIGNAR_CANONICO.value}:{index}",
                    kind=CatalogActionKind.ASIGNAR_CANONICO,
                    args={
                        "product_id": observation.product_id,
                        "canonical_id": canonical_id,
                        "canonical_name": _text(option.get("canonical_name")),
                        "confidence": _confidence(option.get("confidence")),
                    },
                    label=f"Asignar al canónico candidato {index}",
                )
            )

    if observation.kind in (
        CatalogObservationKind.UNMATCHED_PRODUCT,
        CatalogObservationKind.CLUSTER_CANDIDATE,
    ):
        for index, cluster in enumerate(_clusters(details)):
            candidates.append(
                CatalogCandidate(
                    key=f"{CatalogActionKind.PROPONER_HOJA_NUEVA.value}:{index}",
                    kind=CatalogActionKind.PROPONER_HOJA_NUEVA,
                    args={
                        "cluster_id": _text(cluster.get("cluster_id")),
                        "label": _text(cluster.get("label")),
                        "signals": list(_signal_names(cluster.get("signals"))),
                        "product_ids": list(_product_ids(cluster.get("product_ids"))),
                    },
                    label=f"Proponer una hoja nueva para el grupo {index}",
                )
            )

    candidates.append(
        CatalogCandidate(
            key=CatalogActionKind.ENVIAR_A_REVISION.value,
            kind=CatalogActionKind.ENVIAR_A_REVISION,
            args={"product_id": observation.product_id, "reason": observation.summary},
            label="Enviar a revisión",
        )
    )
    candidates.append(
        CatalogCandidate(
            key=CatalogActionKind.NO_HACER_NADA.value,
            kind=CatalogActionKind.NO_HACER_NADA,
            args={},
            label="No hacer nada",
        )
    )
    return tuple(candidates)


class CatalogDefaultPolicy:
    """Deterministic degradation mode: never assigns or creates a leaf on its own.

    Every catalog observation becomes `enviar_a_revision`; without that candidate the policy
    answers `no_hacer_nada`. Both outcomes leave the catalog untouched, which is the safe
    degradation ADR 0022 requires when the model is unavailable or keeps failing.
    """

    name = "catalog_default"

    def choose(
        self,
        state: CatalogState,
        observation: CatalogObservation,
        candidates: Sequence[CatalogCandidate],
    ) -> PolicyDecision:
        chosen = next(
            (item for item in candidates if item.kind is CatalogActionKind.ENVIAR_A_REVISION),
            None,
        )
        if chosen is None:
            chosen = next(
                (item for item in candidates if item.kind is CatalogActionKind.NO_HACER_NADA),
                None,
            )
        key = chosen.key if chosen is not None else CatalogActionKind.NO_HACER_NADA.value
        return PolicyDecision(action_key=key)


class _CatalogExecutor:
    """Template for the two-phase catalog effects: propose a payload, validate, apply."""

    def propose(self, state: CatalogState, action: CatalogCandidate) -> Proposal:
        return Proposal(action=action, summary=action.label, payload=self._payload(action))

    def validate(self, state: CatalogState, proposal: Proposal) -> str | None:
        return self._validate(state, proposal.payload)

    def apply(self, state: CatalogState, proposal: Proposal) -> CatalogState:
        return self._apply(state, proposal.payload)

    def _payload(self, action: CatalogCandidate) -> dict[str, Any]:
        return dict(action.args)

    def _validate(self, state: CatalogState, payload: Mapping[str, Any]) -> str | None:
        return None

    def _apply(self, state: CatalogState, payload: Mapping[str, Any]) -> CatalogState:
        return state


class _AssignCanonical(_CatalogExecutor):
    """Assigns a product to an existing canonical, only above the automatic threshold."""

    def __init__(self, min_auto_confidence: float) -> None:
        self.min_auto_confidence = min_auto_confidence

    def _payload(self, action: CatalogCandidate) -> dict[str, Any]:
        payload = dict(action.args)
        payload["product_id"] = _int_value(payload.get("product_id"))
        payload["canonical_id"] = _int_value(payload.get("canonical_id"))
        payload["canonical_name"] = _text(payload.get("canonical_name"))
        payload["confidence"] = _confidence(payload.get("confidence"))
        return payload

    def _validate(self, state: CatalogState, payload: Mapping[str, Any]) -> str | None:
        if payload.get("canonical_id") is None:
            return "asignar_canonico needs a valid canonical_id"
        confidence = payload.get("confidence")
        if confidence is None:
            return "asignar_canonico needs a confidence to apply autonomously"
        if confidence < self.min_auto_confidence:
            return (
                f"confidence {confidence:.2f} is below the automatic threshold "
                f"{self.min_auto_confidence:.2f}"
            )
        return None

    def _apply(self, state: CatalogState, payload: Mapping[str, Any]) -> CatalogState:
        canonical_id = int(payload["canonical_id"])
        record = {
            "product_id": payload.get("product_id"),
            "canonical_id": canonical_id,
            "canonical_name": payload.get("canonical_name") or _canonical_name(state, canonical_id),
            "confidence": payload.get("confidence"),
        }
        return replace(state, assignments=(*state.assignments, record))


class _ProposeNewLeaf(_CatalogExecutor):
    """Proposes a new leaf, enforcing the two-signal and three-product guards of ADR 0022."""

    def _payload(self, action: CatalogCandidate) -> dict[str, Any]:
        payload = dict(action.args)
        payload["signals"] = list(_signal_names(payload.get("signals")))
        payload["product_ids"] = list(_product_ids(payload.get("product_ids")))
        return payload

    def _validate(self, state: CatalogState, payload: Mapping[str, Any]) -> str | None:
        signals = set(payload.get("signals") or ())
        if len(signals) < MIN_SIGNALS_FOR_NEW_LEAF:
            return (
                f"proponer_hoja_nueva needs {MIN_SIGNALS_FOR_NEW_LEAF} independent signals, "
                f"got {len(signals)}"
            )
        products = set(payload.get("product_ids") or ())
        if len(products) < MIN_PRODUCTS_FOR_NEW_LEAF:
            return (
                f"proponer_hoja_nueva needs {MIN_PRODUCTS_FOR_NEW_LEAF} grouped products, "
                f"got {len(products)}"
            )
        return None

    def _apply(self, state: CatalogState, payload: Mapping[str, Any]) -> CatalogState:
        record = {
            "cluster_id": payload.get("cluster_id"),
            "label": payload.get("label"),
            "signals": sorted(set(payload.get("signals") or ())),
            "product_ids": sorted(set(payload.get("product_ids") or ())),
        }
        return replace(state, leaf_proposals=(*state.leaf_proposals, record))


class _SendToReview(_CatalogExecutor):
    """Queues the product for the author: the only effect a conflict is allowed to have."""

    def _payload(self, action: CatalogCandidate) -> dict[str, Any]:
        payload = dict(action.args)
        payload["reason"] = _text(payload.get("reason")) or action.label
        return payload

    def _apply(self, state: CatalogState, payload: Mapping[str, Any]) -> CatalogState:
        record = {
            "product_id": _int_value(payload.get("product_id")),
            "reason": payload.get("reason"),
        }
        return replace(state, review_items=(*state.review_items, record))


class _NoOpCatalog(_CatalogExecutor):
    """Leaves the catalog untouched; the safe option and the `no_hacer_nada` effect."""


def build_pure_catalog_executors(
    min_auto_confidence: float = 0.85,
) -> dict[CatalogActionKind, ActionExecutor]:
    """In-memory catalog executors: pure guard rails, no database, no network.

    `min_auto_confidence` is the floor for an autonomous assignment; a new leaf has its own
    hard guards (`MIN_SIGNALS_FOR_NEW_LEAF`, `MIN_PRODUCTS_FOR_NEW_LEAF`) in `validate()`.
    """
    return {
        CatalogActionKind.ASIGNAR_CANONICO: _AssignCanonical(min_auto_confidence),
        CatalogActionKind.PROPONER_HOJA_NUEVA: _ProposeNewLeaf(),
        CatalogActionKind.ENVIAR_A_REVISION: _SendToReview(),
        CatalogActionKind.NO_HACER_NADA: _NoOpCatalog(),
    }


def build_catalog_harness(config: HarnessConfig | None = None) -> AgentHarness:
    """The shared harness wired with the catalog vocabulary and its conservative defaults."""
    return AgentHarness(
        config,
        candidate_generator=valid_catalog_actions,
        fallback_policy=CatalogDefaultPolicy(),
        low_confidence_action=CatalogActionKind.ENVIAR_A_REVISION,
        pause_action=None,
    )


# -- helpers --------------------------------------------------------------


def _mappings(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or () if isinstance(item, Mapping)]


def _clusters(details: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = details.get("clusters")
    if raw:
        return _mappings(raw)
    if "signals" in details or "product_ids" in details:
        return [dict(details)]
    return []


def _signal_names(value: Any) -> tuple[str, ...]:
    """Normalize signal evidence (strings or mappings) into lower-case family names."""
    names: list[str] = []
    for item in value or ():
        name = (item.get("family") or item.get("name")) if isinstance(item, Mapping) else item
        text = _text(name)
        if text is not None:
            names.append(text.lower())
    return tuple(names)


def _product_ids(value: Any) -> tuple[int, ...]:
    ids = (_int_value(item) for item in value or ())
    return tuple(item for item in ids if item is not None)


def _canonical_name(state: CatalogState, canonical_id: int) -> str | None:
    for option in state.candidates:
        if _int_value(option.get("canonical_id")) == canonical_id:
            return _text(option.get("canonical_name"))
    return None


def _records(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in value or ())


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: Any) -> int | None:
    """A strictly positive integer identifier, or None when the value is not one."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        number = int(value)
    except TypeError, ValueError:
        return None
    return number if number > 0 else None


def _confidence(value: Any) -> float | None:
    """A confidence in [0, 1], or None when the value is not a usable probability."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number
