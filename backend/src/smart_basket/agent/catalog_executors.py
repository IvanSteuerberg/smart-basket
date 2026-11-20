"""Database-backed executors and policy for the catalog agent (ADR 0022, iteration 14 E5).

The pure core of `agent.catalog_agent` decides *what* to do; this module decides *whether the
catalog allows it* and writes the result. Every executor keeps the harness contract
`propose → validate → apply`: `validate` re-reads PostgreSQL, so a stale observation can never
overwrite a decision a human or an earlier stronger method already made, and `apply` runs inside
a savepoint so a half-written leaf leaves no trace.

The three effects of ADR 0022 are enforced here, not in the policy:

* an assignment never overwrites `PROTECTED_METHODS` (`review`, `ean`, `embedding`) and only
  applies above `min_auto_confidence`;
* a new leaf needs two independent signal families and at least three distinct unmatched
  products, and it records a `catalog_leaf_proposal` that `undo_leaf_proposal` can reverse;
* everything else waits in `match_review`, with the nearest canonicals as suggestions.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.agent import trace
from smart_basket.agent.catalog_agent import (
    MIN_PRODUCTS_FOR_NEW_LEAF,
    MIN_SIGNALS_FOR_NEW_LEAF,
    CatalogActionKind,
    CatalogCandidate,
    CatalogObservation,
    CatalogObservationKind,
    CatalogState,
    build_catalog_harness,
)
from smart_basket.agent.catalog_policies import (
    LLM_MIN_AUTO_CONFIDENCE,
    LLMVerifiedCatalogPolicy,
    variants_compatible,
)
from smart_basket.agent.core import (
    ActionExecutor,
    HarnessConfig,
    NoOpExecutor,
    Policy,
    PolicyDecision,
    Proposal,
    RunResult,
)
from smart_basket.matching.catalog import PROTECTED_METHODS
from smart_basket.matching.embeddings import (
    cluster_unmatched_products,
    nearest_canonicals,
)

#: Selective-classification threshold: above it an assignment is applied without review.
DEFAULT_TAU_HIGH = 0.88
#: Canonicals offered to the agent and stored as review suggestions.
DEFAULT_TOP_K = 5
#: The catalog agent's name in `agent_run` and `agent_step`.
CATALOG_AGENT_NAME = "catalog"


def build_db_catalog_executors(
    session: Session,
    *,
    run_id: UUID | None = None,
    min_auto_confidence: float = 0.85,
) -> dict[CatalogActionKind, ActionExecutor]:
    """The four catalog executors, wired to PostgreSQL.

    `run_id` links the leaf proposals this run creates to its `agent_run`; `min_auto_confidence`
    is the floor of an autonomous assignment (the calibrated `tau_high` of the caller).
    """
    return {
        CatalogActionKind.ASIGNAR_CANONICO: _DbAssignCanonical(
            session, min_auto_confidence=min_auto_confidence
        ),
        CatalogActionKind.PROPONER_HOJA_NUEVA: _DbProposeNewLeaf(session, run_id=run_id),
        CatalogActionKind.ENVIAR_A_REVISION: _DbSendToReview(session),
        CatalogActionKind.NO_HACER_NADA: NoOpExecutor(),
    }


class ThresholdCatalogPolicy:
    """Deterministic selective classification over calibrated thresholds (ADR 0022).

    Best first: assign when the nearest canonical reaches `tau_high`; otherwise create a leaf
    when a cluster carries two signal families and three products; otherwise send the product to
    review. A cluster observation that cannot justify a leaf is left alone instead of opening a
    review for a group.
    """

    name = "threshold_calibrated"

    def __init__(self, *, tau_high: float = DEFAULT_TAU_HIGH) -> None:
        self.tau_high = tau_high

    def choose(
        self,
        state: CatalogState,
        observation: CatalogObservation,
        candidates: Sequence[CatalogCandidate],
    ) -> PolicyDecision:
        for candidate in candidates:
            if candidate.kind is not CatalogActionKind.ASIGNAR_CANONICO:
                continue
            confidence = _confidence(candidate.args.get("confidence"))
            if confidence is not None and confidence >= self.tau_high:
                return PolicyDecision(action_key=candidate.key, confidence=confidence)
        for candidate in candidates:
            if candidate.kind is CatalogActionKind.PROPONER_HOJA_NUEVA and _leaf_ready(
                candidate.args
            ):
                return PolicyDecision(action_key=candidate.key)
        if observation.kind is not CatalogObservationKind.CLUSTER_CANDIDATE:
            review = _first_of(candidates, CatalogActionKind.ENVIAR_A_REVISION)
            if review is not None:
                return PolicyDecision(action_key=review.key)
        no_op = _first_of(candidates, CatalogActionKind.NO_HACER_NADA)
        return PolicyDecision(
            action_key=no_op.key if no_op is not None else CatalogActionKind.NO_HACER_NADA.value
        )


def run_catalog_agent(
    session: Session,
    *,
    chain_code: str | None = None,
    tau_high: float = DEFAULT_TAU_HIGH,
    top_k: int = DEFAULT_TOP_K,
    limit: int | None = None,
    policy: Policy | None = None,
    min_auto_confidence: float = 0.85,
) -> dict[str, Any]:
    """Run the catalog agent over unmatched embedded products and persist its trace.

    Each product becomes an observation with the nearest canonicals as candidates; each cluster
    of at least three unmatched products becomes a leaf candidate. Candidates whose variant is
    incompatible with the product are dropped before any policy sees them (ADR 0024), so neither
    the threshold nor the model can propose a sibling-variant assignment. The run, its steps and
    its final state are stored in `agent_run`/`agent_step` with `agent_name = "catalog"`.

    `policy` defaults to `ThresholdCatalogPolicy(tau_high=...)`; a model-verified policy lowers
    the autonomous floor to `LLM_MIN_AUTO_CONFIDENCE`, because the model, not the cosine alone,
    vouches for the match.
    """
    chosen_policy = policy if policy is not None else ThresholdCatalogPolicy(tau_high=tau_high)
    floor = tau_high if policy is None else min_auto_confidence
    is_llm_policy = isinstance(chosen_policy, LLMVerifiedCatalogPolicy)
    if is_llm_policy:
        floor = min(floor, LLM_MIN_AUTO_CONFIDENCE)

    rows = _load_unmatched_products(session, chain_code=chain_code, limit=limit)
    observations = [
        CatalogObservation(
            kind=CatalogObservationKind.UNMATCHED_PRODUCT,
            summary=f"{row['name']} sin canónico asignado",
            product_id=row["id"],
            details={
                "product_name": row["name"],
                "category_name": row["category_name"],
                "candidate_canonicals": [
                    {
                        "canonical_id": match.canonical_id,
                        "canonical_name": match.name,
                        "category_key": match.category_key,
                        "variant_key": match.variant_key,
                        "confidence": _clamp_similarity(match.similarity),
                    }
                    for match in nearest_canonicals(session, row["embedding"], top_k=top_k)
                    if variants_compatible(row["name"], match.variant_key)
                    and (not is_llm_policy or _clamp_similarity(match.similarity) >= floor)
                ],
            },
        )
        for row in rows
    ]
    observed = {row["id"] for row in rows}
    observations.extend(_cluster_observations(session, chain_code=chain_code, observed=observed))

    state = CatalogState(observations=tuple(observations))
    run_id = trace.create_run(
        session,
        agent_name=CATALOG_AGENT_NAME,
        policy_name=chosen_policy.name,
        state_json=state.to_dict(),
    )
    executors = build_db_catalog_executors(session, run_id=run_id, min_auto_confidence=floor)
    step_budget_ms = 10_000 if is_llm_policy else 1_000
    config = HarnessConfig(
        max_steps=max(6, len(observations)),
        max_retries=0 if is_llm_policy else 2,
        time_budget_ms=max(60_000, step_budget_ms * max(1, len(observations))),
    )
    result = build_catalog_harness(config).run(state, chosen_policy, executors)
    _persist_trace(session, run_id, result)
    return {
        "run_id": run_id,
        "assigned": len(result.state.assignments),
        "proposed_leaves": len(result.state.leaf_proposals),
        "sent_to_review": len(result.state.review_items),
        "steps": len(result.steps),
        "status": result.status.value,
        "stopped_reason": result.stopped_reason,
    }


def undo_leaf_proposal(session: Session, proposal_id: int) -> dict[str, Any]:
    """Reverse an applied leaf: unassign its products and send them back to review.

    Idempotent: a proposal already undone is reported and left untouched. Products a human or a
    stronger method matched after the proposal are never cleared — only `embedding` assignments
    to the canonical of this leaf are.
    """
    row = session.execute(
        text(
            "select id, category_key, status, product_ids_json "
            "from catalog_leaf_proposal where id = :id"
        ),
        {"id": proposal_id},
    ).one_or_none()
    if row is None:
        raise ValueError(f"leaf proposal {proposal_id} does not exist")
    if row.status != "applied":
        return {
            "proposal_id": proposal_id,
            "status": row.status,
            "products_cleared": 0,
            "reviews_queued": 0,
            "already_undone": True,
        }

    cleared: list[int] = []
    with session.begin_nested():
        claimed = session.execute(
            text(
                "update catalog_leaf_proposal set status = 'undone', undone_at = now() "
                "where id = :id and status = 'applied' returning id"
            ),
            {"id": proposal_id},
        ).scalar_one_or_none()
        if claimed is None:
            current = session.execute(
                text("select status from catalog_leaf_proposal where id = :id"),
                {"id": proposal_id},
            ).scalar_one()
            return {
                "proposal_id": proposal_id,
                "status": current,
                "products_cleared": 0,
                "reviews_queued": 0,
                "already_undone": True,
            }
        product_ids = [int(value) for value in row.product_ids_json]
        canonical_ids = list(
            session.execute(
                text(
                    "select cp.id from canonical_product cp "
                    "join category cat on cat.id = cp.category_id "
                    "where cat.key = :key"
                ),
                {"key": row.category_key},
            ).scalars()
        )
        if product_ids and canonical_ids:
            cleared = list(
                session.execute(
                    text(
                        "update chain_product set canonical_id = null, match_method = null, "
                        "  match_confidence = null "
                        "where id = any(:ids) and match_method = 'embedding' "
                        "  and canonical_id = any(:canonicals) "
                        "returning id"
                    ),
                    {"ids": product_ids, "canonicals": canonical_ids},
                ).scalars()
            )
        for product_id in cleared:
            session.execute(
                text(
                    "insert into match_review (chain_product_id, candidates) "
                    "values (:product, '[]'::jsonb) "
                    "on conflict (chain_product_id) where status = 'pending' do nothing"
                ),
                {"product": product_id},
            )
    return {
        "proposal_id": proposal_id,
        "status": "undone",
        "products_cleared": len(cleared),
        "reviews_queued": len(cleared),
    }


def calibrate_thresholds(
    session: Session,
    *,
    chain_code: str | None = None,
    sample_size: int = 200,
    thresholds: Sequence[float] = (0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95),
) -> dict[str, Any]:
    """Precision and coverage of automatic assignment at each threshold, over matched products.

    For every sampled matched product, `own` is the cosine similarity to the canonical it is
    assigned to and `best_other` is the highest similarity among the *other* canonicals
    (leave-one-out). At threshold `tau`, coverage is the share of products with `own >= tau`
    (what the agent would assign alone) and precision is the share of those where `own` beats
    every other canonical (what it would get right).
    """
    where = ["cp.canonical_id is not null", "cp.embedding is not null", "cp.is_active"]
    params: dict[str, Any] = {"sample_size": sample_size}
    if chain_code is not None:
        where.append("ch.code = :chain")
        params["chain"] = chain_code
    rows = list(
        session.execute(
            text(
                "select s.product_id, s.canonical_id, "
                "  1 - (s.embedding <=> oc.embedding) as own_similarity, "
                "  (select max(1 - (s.embedding <=> c.embedding)) "
                "     from canonical_product c "
                "    where c.embedding is not null and c.merged_into is null "
                "      and c.id <> s.canonical_id) as best_other "
                "from ("
                "  select cp.id as product_id, cp.canonical_id, cp.embedding "
                "  from chain_product cp "
                "  join chain ch on ch.id = cp.chain_id "
                f"  where {' and '.join(where)} "
                "  order by cp.id limit :sample_size"
                ") s "
                "join canonical_product oc on oc.id = s.canonical_id "
                "  and oc.embedding is not null and oc.merged_into is null"
            ),
            params,
        ).mappings()
    )
    pairs = [
        (
            float(row["own_similarity"]),
            None if row["best_other"] is None else float(row["best_other"]),
        )
        for row in rows
    ]
    results = []
    for threshold in thresholds:
        automatic = [pair for pair in pairs if pair[0] >= threshold]
        correct = sum(1 for own, other in automatic if other is None or own > other)
        results.append(
            {
                "threshold": round(float(threshold), 4),
                "precision": round(correct / len(automatic), 4) if automatic else 0.0,
                "coverage": round(len(automatic) / len(pairs), 4) if pairs else 0.0,
                "auto_assigned": len(automatic),
            }
        )
    return {
        "chain_code": chain_code,
        "sample_size": len(pairs),
        "thresholds": results,
    }


def export_audit_sample(
    session: Session,
    *,
    chain_code: str,
    sample_size: int = 250,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """A blind, deterministic sample of matched products for a human audit.

    The sample never carries the canonical, the method or the confidence: the auditor labels the
    product without seeing the automatic decision. The same seed always returns the same rows.
    """
    rows = session.execute(
        text(
            "select cp.id as product_id, cp.chain_sku, cp.name, cc.name as chain_category "
            "from chain_product cp "
            "join chain ch on ch.id = cp.chain_id "
            "left join chain_category cc on cc.id = cp.chain_category_id "
            "where ch.code = :chain and cp.canonical_id is not null and cp.is_active "
            "order by md5(cast(:seed as text) || ':' || cp.id::text) "
            "limit :sample_size"
        ),
        {"chain": chain_code, "seed": seed, "sample_size": sample_size},
    ).mappings()
    return [
        {
            "product_id": row["product_id"],
            "chain_sku": row["chain_sku"],
            "name": row["name"],
            "chain_category": row["chain_category"],
        }
        for row in rows
    ]


class _DbAssignCanonical:
    """Assigns a product to an existing canonical, never over a protected method."""

    def __init__(self, session: Session, *, min_auto_confidence: float) -> None:
        self.session = session
        self.min_auto_confidence = min_auto_confidence

    def propose(self, state: CatalogState, action: CatalogCandidate) -> Proposal:
        payload = {
            "product_id": _int_value(action.args.get("product_id")),
            "canonical_id": _int_value(action.args.get("canonical_id")),
            "canonical_name": _text(action.args.get("canonical_name")),
            "confidence": _confidence(action.args.get("confidence")),
        }
        return Proposal(action=action, summary=action.label, payload=payload)

    def validate(self, state: CatalogState, proposal: Proposal) -> str | None:
        payload = proposal.payload
        if payload["product_id"] is None:
            return "asignar_canonico needs a valid product_id"
        if payload["canonical_id"] is None:
            return "asignar_canonico needs a valid canonical_id"
        confidence = payload["confidence"]
        if confidence is None:
            return "asignar_canonico needs a confidence to apply autonomously"
        if confidence < self.min_auto_confidence:
            return (
                f"confidence {confidence:.2f} is below the automatic threshold "
                f"{self.min_auto_confidence:.2f}"
            )
        row = self.session.execute(
            text("select id, name, match_method from chain_product where id = :product"),
            {"product": payload["product_id"]},
        ).one_or_none()
        if row is None:
            return f"product {payload['product_id']} does not exist"
        if row.match_method in PROTECTED_METHODS:
            return (
                f"product {payload['product_id']} is already matched with method "
                f"{row.match_method!r}"
            )
        canonical = self.session.execute(
            text(
                "select id, name, variant_key from canonical_product "
                "where id = :canonical and merged_into is null"
            ),
            {"canonical": payload["canonical_id"]},
        ).one_or_none()
        if canonical is None:
            return f"canonical {payload['canonical_id']} does not exist"
        if not variants_compatible(row.name, canonical.variant_key):
            return (
                f"la variante del producto «{row.name}» no es compatible con la del canónico "
                f"«{canonical.name}» ({canonical.variant_key or 'sin variante'})"
            )
        return None

    def apply(self, state: CatalogState, proposal: Proposal) -> CatalogState:
        payload = proposal.payload
        canonical_name = payload["canonical_name"]
        with self.session.begin_nested():
            updated = self.session.execute(
                text(
                    "update chain_product set canonical_id = :canonical, "
                    "  match_method = 'embedding', match_confidence = :confidence "
                    "where id = :product "
                    "  and (match_method is null "
                    "       or not (match_method = any(:protected))) "
                    "returning id"
                ),
                {
                    "product": payload["product_id"],
                    "canonical": payload["canonical_id"],
                    "confidence": payload["confidence"],
                    "protected": list(PROTECTED_METHODS),
                },
            ).scalar_one_or_none()
            if updated is None:
                raise ValueError(f"product {payload['product_id']} was matched concurrently")
            self.session.execute(
                text(
                    "insert into product_match "
                    "  (chain_product_id, canonical_id, method, score) "
                    "values (:product, :canonical, 'embedding', :confidence)"
                ),
                {
                    "product": payload["product_id"],
                    "canonical": payload["canonical_id"],
                    "confidence": payload["confidence"],
                },
            )
            self.session.execute(
                text(
                    "update match_review set status = 'accepted', resolved_at = now() "
                    "where chain_product_id = :product and status = 'pending'"
                ),
                {"product": payload["product_id"]},
            )
            if canonical_name is None:
                canonical_name = self.session.execute(
                    text("select name from canonical_product where id = :canonical"),
                    {"canonical": payload["canonical_id"]},
                ).scalar_one()
        record = {
            "product_id": payload["product_id"],
            "canonical_id": payload["canonical_id"],
            "canonical_name": canonical_name,
            "confidence": payload["confidence"],
        }
        return replace(state, assignments=(*state.assignments, record))


class _DbProposeNewLeaf:
    """Creates a new leaf and a canonical for a cluster, enforcing the ADR 0022 guards."""

    def __init__(self, session: Session, *, run_id: UUID | None) -> None:
        self.session = session
        self.run_id = run_id

    def propose(self, state: CatalogState, action: CatalogCandidate) -> Proposal:
        payload = {
            "cluster_id": _text(action.args.get("cluster_id")),
            "label": _text(action.args.get("label")),
            "signals": _signal_names(action.args.get("signals")),
            "product_ids": _product_ids(action.args.get("product_ids")),
            "parent_category_id": _int_value(action.args.get("parent_category_id")),
        }
        return Proposal(action=action, summary=action.label, payload=payload)

    def validate(self, state: CatalogState, proposal: Proposal) -> str | None:
        payload = proposal.payload
        signals = set(payload["signals"])
        if len(signals) < MIN_SIGNALS_FOR_NEW_LEAF:
            return (
                f"proponer_hoja_nueva needs {MIN_SIGNALS_FOR_NEW_LEAF} independent signals, "
                f"got {len(signals)}"
            )
        products = list(dict.fromkeys(payload["product_ids"]))
        if len(products) < MIN_PRODUCTS_FOR_NEW_LEAF:
            return (
                f"proponer_hoja_nueva needs {MIN_PRODUCTS_FOR_NEW_LEAF} grouped products, "
                f"got {len(products)}"
            )
        payload["product_ids"] = tuple(products)
        label = payload["label"]
        if label is None:
            return "proponer_hoja_nueva needs a label"
        rows = list(
            self.session.execute(
                text("select id, canonical_id, is_active from chain_product where id = any(:ids)"),
                {"ids": list(products)},
            ).mappings()
        )
        found = {row["id"]: row for row in rows}
        missing = [product for product in products if product not in found]
        if missing:
            return f"products do not exist: {missing}"
        matched = [product for product in products if found[product]["canonical_id"] is not None]
        if matched:
            return f"products are already matched: {matched}"
        inactive = [product for product in products if not found[product]["is_active"]]
        if inactive:
            return f"products are inactive: {inactive}"
        parent_id = payload["parent_category_id"] or self._derive_parent(products)
        if parent_id is not None:
            parent = self.session.execute(
                text("select id, level from category where id = :parent"),
                {"parent": parent_id},
            ).one_or_none()
            if parent is None:
                return f"parent category {parent_id} does not exist"
            if parent.level >= 5:
                return "cannot create a leaf below level 5"
            payload["parent_level"] = parent.level
        existing = self.session.execute(
            text(
                "select id from category "
                "where parent_id is not distinct from :parent and name = :name"
            ),
            {"parent": parent_id, "name": label},
        ).scalar_one_or_none()
        if existing is not None:
            return f"a category named {label!r} already exists under its parent"
        payload["parent_category_id"] = parent_id
        return None

    def apply(self, state: CatalogState, proposal: Proposal) -> CatalogState:
        payload = proposal.payload
        products = list(payload["product_ids"])
        label = payload["label"]
        parent_id = payload["parent_category_id"]
        level = payload["parent_level"] + 1 if parent_id is not None else 3
        name = label
        unit = self._base_unit(products)
        with self.session.begin_nested():
            category_key = _unique_category_key(self.session, _slugify(label))
            category_id = self.session.execute(
                text(
                    "insert into category "
                    "  (key, name, level, parent_id, base_unit) "
                    "values (:key, :name, :level, :parent, :unit) returning id"
                ),
                {
                    "key": category_key,
                    "name": name,
                    "level": level,
                    "parent": parent_id,
                    "unit": unit,
                },
            ).scalar_one()
            self.session.execute(
                text(
                    "insert into category_closure (ancestor_id, descendant_id, depth) "
                    "values (:category, :category, 0)"
                ),
                {"category": category_id},
            )
            if parent_id is not None:
                self.session.execute(
                    text(
                        "insert into category_closure (ancestor_id, descendant_id, depth) "
                        "select ancestor_id, :category, depth + 1 "
                        "from category_closure where descendant_id = :parent"
                    ),
                    {"category": category_id, "parent": parent_id},
                )
            canonical_id = self.session.execute(
                text(
                    "insert into canonical_product "
                    "  (category_id, name, variant_key, base_unit) "
                    "values (:category, :name, '', :unit) returning id"
                ),
                {"category": category_id, "name": name, "unit": unit},
            ).scalar_one()
            assigned = list(
                self.session.execute(
                    text(
                        "update chain_product set canonical_id = :canonical, "
                        "  match_method = 'embedding', match_confidence = null "
                        "where id = any(:ids) and canonical_id is null "
                        "returning id"
                    ),
                    {"canonical": canonical_id, "ids": products},
                ).scalars()
            )
            if len(assigned) != len(products):
                raise ValueError("the clustered products changed while the leaf was applied")
            self.session.execute(
                text(
                    "insert into product_match "
                    "  (chain_product_id, canonical_id, method) "
                    "values (:product, :canonical, 'embedding')"
                ),
                [{"product": product, "canonical": canonical_id} for product in products],
            )
            self.session.execute(
                text(
                    "update match_review set status = 'accepted', resolved_at = now() "
                    "where chain_product_id = any(:ids) and status = 'pending'"
                ),
                {"ids": products},
            )
            proposal_id = self.session.execute(
                text(
                    "insert into catalog_leaf_proposal "
                    "  (run_id, category_key, category_name, parent_category_id, "
                    "   signals_json, product_ids_json, status) "
                    "values (:run, :key, :name, :parent, cast(:signals as jsonb), "
                    "        cast(:products as jsonb), 'applied') returning id"
                ),
                {
                    "run": self.run_id,
                    "key": category_key,
                    "name": name,
                    "parent": parent_id,
                    "signals": json.dumps(sorted(set(payload["signals"]))),
                    "products": json.dumps(products),
                },
            ).scalar_one()
        record = {
            "proposal_id": proposal_id,
            "cluster_id": payload["cluster_id"],
            "label": label,
            "signals": sorted(set(payload["signals"])),
            "product_ids": sorted(products),
            "category_id": category_id,
            "canonical_id": canonical_id,
        }
        return replace(state, leaf_proposals=(*state.leaf_proposals, record))

    def _derive_parent(self, products: Sequence[int]) -> int | None:
        """The common canonical category of the clustered products, when there is exactly one."""
        categories = list(
            self.session.execute(
                text(
                    "select distinct cc.category_id "
                    "from chain_product cp "
                    "join chain_category cc on cc.id = cp.chain_category_id "
                    "where cp.id = any(:ids) and cc.category_id is not null"
                ),
                {"ids": list(products)},
            ).scalars()
        )
        return categories[0] if len(categories) == 1 else None

    def _base_unit(self, products: Sequence[int]) -> str:
        """The most common base unit of the group; `ud` when none declares one."""
        unit = self.session.execute(
            text(
                "select base_unit from chain_product "
                "where id = any(:ids) and base_unit is not null "
                "group by base_unit order by count(*) desc, base_unit limit 1"
            ),
            {"ids": list(products)},
        ).scalar_one_or_none()
        return unit or "ud"


class _DbSendToReview:
    """Queues a product for the author with the nearest canonicals as suggestions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def propose(self, state: CatalogState, action: CatalogCandidate) -> Proposal:
        payload = {
            "product_id": _int_value(action.args.get("product_id")),
            "reason": _text(action.args.get("reason")),
            "candidates": action.args.get("candidates"),
        }
        return Proposal(action=action, summary=action.label, payload=payload)

    def validate(self, state: CatalogState, proposal: Proposal) -> str | None:
        product_id = proposal.payload["product_id"]
        if product_id is None:
            return "enviar_a_revision needs a valid product_id"
        exists = self.session.execute(
            text("select 1 from chain_product where id = :product"),
            {"product": product_id},
        ).scalar_one_or_none()
        if exists is None:
            return f"product {product_id} does not exist"
        return None

    def apply(self, state: CatalogState, proposal: Proposal) -> CatalogState:
        payload = proposal.payload
        product_id = payload["product_id"]
        candidates = payload["candidates"]
        with self.session.begin_nested():
            if not isinstance(candidates, list):
                candidates = self._suggestions(product_id)
            self.session.execute(
                text(
                    "insert into match_review (chain_product_id, candidates) "
                    "values (:product, cast(:candidates as jsonb)) "
                    "on conflict (chain_product_id) where status = 'pending' "
                    "do update set candidates = excluded.candidates"
                ),
                {
                    "product": product_id,
                    "candidates": json.dumps(candidates, ensure_ascii=False),
                },
            )
        record = {"product_id": product_id, "reason": payload["reason"]}
        return replace(state, review_items=(*state.review_items, record))

    def _suggestions(self, product_id: int) -> list[dict[str, Any]]:
        row = self.session.execute(
            text("select embedding::real[] as embedding from chain_product where id = :product"),
            {"product": product_id},
        ).one_or_none()
        if row is None or row.embedding is None:
            return []
        return [
            {
                "canonical_id": match.canonical_id,
                "category_key": match.category_key,
                "name": match.name,
                "similarity": round(match.similarity, 4),
            }
            for match in nearest_canonicals(self.session, row.embedding, top_k=DEFAULT_TOP_K)
        ]


def _load_unmatched_products(
    session: Session, *, chain_code: str | None, limit: int | None
) -> list[Mapping[str, Any]]:
    params: dict[str, Any] = {}
    where = ["cp.canonical_id is null", "cp.embedding is not null", "cp.is_active"]
    if chain_code is not None:
        where.append("ch.code = :chain")
        params["chain"] = chain_code
    sql = (
        "select cp.id, cp.name, cp.embedding::real[] as embedding, "
        "  cc.name as category_name "
        "from chain_product cp "
        "join chain ch on ch.id = cp.chain_id "
        "left join chain_category cc on cc.id = cp.chain_category_id "
        f"where {' and '.join(where)} order by cp.id"
    )
    if limit is not None:
        sql += " limit :limit"
        params["limit"] = limit
    return list(session.execute(text(sql), params).mappings())


def _cluster_observations(
    session: Session, *, chain_code: str | None, observed: set[int]
) -> list[CatalogObservation]:
    """One leaf observation per cluster, keeping only products of this run."""
    observations = []
    for position, cluster in enumerate(
        cluster_unmatched_products(session, chain_code=chain_code), start=1
    ):
        product_ids = tuple(product for product in cluster.product_ids if product in observed)
        if len(product_ids) < MIN_PRODUCTS_FOR_NEW_LEAF:
            continue
        names = [
            cluster.product_names[i]
            for i, product in enumerate(cluster.product_ids)
            if product in observed
        ]
        signals = _cluster_signals(session, product_ids)
        if len(signals) < MIN_SIGNALS_FOR_NEW_LEAF:
            continue
        observations.append(
            CatalogObservation(
                kind=CatalogObservationKind.CLUSTER_CANDIDATE,
                summary=f"{len(product_ids)} productos sin canónico forman un grupo",
                details={
                    "clusters": [
                        {
                            "cluster_id": f"cluster_{position}",
                            "label": _cluster_label(names),
                            "signals": signals,
                            "product_ids": list(product_ids),
                            "mean_similarity": cluster.mean_similarity,
                        }
                    ]
                },
            )
        )
    return observations


def _cluster_signals(session: Session, product_ids: Sequence[int]) -> list[str]:
    """The independent families that justify a leaf: embeddings plus names, section or brand.

    The cluster itself is one family (`embedding`); a shared meaningful name token, one shared
    chain section and one shared brand are each an independent family.
    """
    rows = list(
        session.execute(
            text(
                "select id, name, chain_category_id, brand_id from chain_product "
                "where id = any(:ids)"
            ),
            {"ids": list(product_ids)},
        ).mappings()
    )
    signals = ["embedding"]
    token_sets = [_tokens(row["name"]) for row in rows]
    if token_sets and set.intersection(*token_sets):
        signals.append("name_tokens")
    categories = {row["chain_category_id"] for row in rows}
    if len(categories) == 1 and None not in categories:
        signals.append("category")
    brands = {row["brand_id"] for row in rows}
    if len(brands) == 1 and None not in brands:
        signals.append("brand")
    return signals


def _cluster_label(names: Sequence[str]) -> str:
    """The shared meaningful token as the leaf name, or the first product name."""
    token_sets = [_tokens(name) for name in names]
    common = set.intersection(*token_sets) if token_sets else set()
    if common:
        return sorted(common, key=lambda token: (-len(token), token))[0].capitalize()
    return names[0] if names else "Hoja nueva"


def _tokens(name: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", name)
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return {token for token in re.split(r"[^a-z0-9]+", plain.lower()) if len(token) >= 3}


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    return slug or "hoja"


def _unique_category_key(session: Session, base: str) -> str:
    key = base
    suffix = 2
    while (
        session.execute(
            text("select 1 from category where key = :key"), {"key": key}
        ).scalar_one_or_none()
        is not None
    ):
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def _persist_trace(session: Session, run_id: UUID, result: RunResult) -> None:
    """Write every step and the final state of a catalog run to `agent_run`/`agent_step`."""
    for step in result.steps:
        trace.append_step(
            session,
            run_id=run_id,
            step_number=step.step_number,
            observation_json=(step.observation.to_dict() if step.observation is not None else {}),
            candidates_json=[candidate.to_dict() for candidate in step.candidates],
            chosen_action=step.chosen_action or CatalogActionKind.NO_HACER_NADA.value,
            action_args_json=step.action_args,
            confidence=step.confidence,
            probabilities_json=step.probabilities,
            retries=step.retries,
            used_default=step.used_default,
            result_json={"summary": step.result} if step.result is not None else {},
            latency_ms=round(step.latency_ms),
            error=step.error,
        )
    trace.update_run(
        session,
        run_id,
        state_json=result.state.to_dict(),
        status=result.status.value,
        steps_count=len(result.steps),
        total_latency_ms=round(result.total_latency_ms),
        finished_at=datetime.now(UTC),
    )


def _first_of(
    candidates: Sequence[CatalogCandidate], kind: CatalogActionKind
) -> CatalogCandidate | None:
    return next((candidate for candidate in candidates if candidate.kind is kind), None)


def _leaf_ready(args: Mapping[str, Any]) -> bool:
    signals = set(_signal_names(args.get("signals")))
    products = set(_product_ids(args.get("product_ids")))
    return len(signals) >= MIN_SIGNALS_FOR_NEW_LEAF and len(products) >= MIN_PRODUCTS_FOR_NEW_LEAF


def _signal_names(value: Any) -> tuple[str, ...]:
    """Normalize signal evidence (strings or mappings) into lower-case family names."""
    names: list[str] = []
    for item in value or ():
        name = (item.get("family") or item.get("name")) if isinstance(item, Mapping) else item
        text_value = _text(name)
        if text_value is not None:
            names.append(text_value.lower())
    return tuple(names)


def _product_ids(value: Any) -> tuple[int, ...]:
    ids = (_int_value(item) for item in value or ())
    return tuple(item for item in ids if item is not None)


def _clamp_similarity(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


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
    if not 0.0 <= number <= 1.0:
        return None
    return number
