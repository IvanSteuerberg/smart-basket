"""Catalog Agent pgvector engine and DB executors (ADR 0022, iteration 14 E5).

Every test runs inside a transaction that is rolled back, against a disposable PostgreSQL with
pgvector. The embedding provider is a deterministic fake that returns unit vectors, so no test
ever touches the network.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from smart_basket.agent import trace
from smart_basket.agent.catalog_agent import (
    CatalogActionKind,
    CatalogCandidate,
    CatalogObservationKind,
    CatalogState,
)
from smart_basket.agent.catalog_cli import build_parser
from smart_basket.agent.catalog_executors import (
    build_db_catalog_executors,
    calibrate_thresholds,
    export_audit_sample,
    run_catalog_agent,
    undo_leaf_proposal,
)
from smart_basket.agent.catalog_policies import LLMVerifiedCatalogPolicy
from smart_basket.db.migrate import alembic_config
from smart_basket.matching.embeddings import (
    EMBEDDING_DIMENSIONS,
    build_canonical_text,
    build_product_text,
    cluster_unmatched_products,
    embed_missing_canonicals,
    embed_missing_products,
    nearest_canonicals,
)

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


def vector(*coordinates: float) -> list[float]:
    """A 768-dimension vector with the given leading coordinates and zeros elsewhere."""
    assert len(coordinates) <= EMBEDDING_DIMENSIONS
    return [*coordinates, *([0.0] * (EMBEDDING_DIMENSIONS - len(coordinates)))]


class FakeEmbeddingProvider:
    """Deterministic provider: returns the unit vector registered for each exact text."""

    model = "fake-embedding"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, table: dict[str, Sequence[float]]) -> None:
        self._table = {key: list(value) for key, value in table.items()}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(self._table[text]) for text in texts]


class FakeCatalogVerifier:
    """Deterministic `LLMProvider` for the catalog verifier: always picks the first candidate."""

    name = "fake"
    model = "fake-verifier"

    def __init__(self, answer: str = "asignar_canonico:0") -> None:
        self.answer = answer
        self.calls = 0

    def generate_json(self, system: str, user: str, schema: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {"action_key": self.answer}

    def generate_text(self, prompt: str) -> str:  # pragma: no cover - unused by the policy
        return ""


@dataclass
class World:
    """The rolled-back session plus the ids of the synthetic catalog."""

    session: Session
    chain_id: int
    categories: dict[str, int]
    chain_categories: dict[str, int]


@pytest.fixture(scope="module")
def engine():
    if not URL:
        pytest.skip("TEST_DATABASE_URL not set")
    command.upgrade(alembic_config(URL), "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[World]:
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        world = _seed(session)
        yield world
        session.close()
        transaction.rollback()


def add_canonical(
    world: World,
    category_key: str,
    name: str,
    *,
    embedding: Sequence[float] | None = None,
    base_unit: str = "kg",
    variant_key: str = "",
    merged_into: int | None = None,
) -> int:
    return world.session.execute(
        text(
            "insert into canonical_product "
            "  (category_id, name, variant_key, base_unit, embedding, merged_into) "
            "values (:category, :name, :variant, :unit, cast(:vec as vector), :merged) returning id"
        ),
        {
            "category": world.categories[category_key],
            "name": name,
            "variant": variant_key,
            "unit": base_unit,
            "vec": None if embedding is None else _literal(embedding),
            "merged": merged_into,
        },
    ).scalar_one()


def add_product(
    world: World,
    sku: str,
    name: str,
    *,
    chain_category: str = "fruta",
    canonical_id: int | None = None,
    match_method: str | None = None,
    embedding: Sequence[float] | None = None,
) -> int:
    return world.session.execute(
        text(
            "insert into chain_product "
            "  (chain_id, chain_sku, name, chain_category_id, canonical_id, match_method, "
            "   embedding) "
            "values (:chain, :sku, :name, :category, :canonical, :method, cast(:vec as vector)) "
            "returning id"
        ),
        {
            "chain": world.chain_id,
            "sku": sku,
            "name": name,
            "category": world.chain_categories[chain_category],
            "canonical": canonical_id,
            "method": match_method,
            "vec": None if embedding is None else _literal(embedding),
        },
    ).scalar_one()


def run_action(world: World, kind: CatalogActionKind, args: dict[str, object]) -> CatalogState:
    """Propose, validate and apply one action, asserting it was valid."""
    executors = build_db_catalog_executors(world.session)
    action = CatalogCandidate(key=f"{kind.value}:0", kind=kind, args=args, label="test")
    executor = executors[kind]
    state = CatalogState()
    proposal = executor.propose(state, action)
    problem = executor.validate(state, proposal)
    assert problem is None
    return executor.apply(state, proposal)


def validate_action(world: World, kind: CatalogActionKind, args: dict[str, object]) -> str | None:
    executors = build_db_catalog_executors(world.session)
    action = CatalogCandidate(key=f"{kind.value}:0", kind=kind, args=args, label="test")
    executor = executors[kind]
    proposal = executor.propose(CatalogState(), action)
    return executor.validate(CatalogState(), proposal)


def test_embeddings_are_incremental_and_stored_as_vector_768(db):
    world = db
    add_canonical(world, "platano", "Plátano de Canarias")
    add_canonical(world, "leche", "Leche entera")
    add_product(world, "M1", "Plátano", chain_category="fruta")
    add_product(world, "M2", "Leche", chain_category="lacteos")
    add_product(world, "M3", "Plátano canario", chain_category="fruta")
    provider = FakeEmbeddingProvider(
        {
            build_canonical_text("Plátano de Canarias", "Plátano", ""): vector(1, 0, 0),
            build_canonical_text("Leche entera", "Leche", ""): vector(0, 1, 0),
            build_product_text("Plátano", "Fruta"): vector(1, 0, 0),
            build_product_text("Leche", "Lácteos"): vector(0, 1, 0),
            build_product_text("Plátano canario", "Fruta"): vector(0.9, 0.1, 0),
        }
    )

    assert embed_missing_canonicals(world.session, provider) == 2
    assert embed_missing_canonicals(world.session, provider) == 0
    assert embed_missing_products(world.session, provider) == 3
    assert embed_missing_products(world.session, provider) == 0

    dimensions = world.session.execute(
        text(
            "select count(*) from canonical_product "
            "where embedding is not null and vector_dims(embedding) = 768"
        )
    ).scalar_one()
    assert dimensions == 2


def test_nearest_canonicals_orders_by_cosine_similarity(db):
    world = db
    alpha = add_canonical(world, "platano", "Alfa", embedding=vector(1, 0, 0))
    beta = add_canonical(world, "manzana", "Beta", embedding=vector(0, 1, 0))
    gamma = add_canonical(world, "leche", "Gamma", embedding=vector(-1, 0, 0))

    matches = nearest_canonicals(world.session, vector(1, 0.2), top_k=3)

    assert [match.canonical_id for match in matches] == [alpha, beta, gamma]
    similarities = [match.similarity for match in matches]
    assert similarities == sorted(similarities, reverse=True)
    assert similarities[0] == pytest.approx(1.0 / math.sqrt(1.04), abs=1e-5)
    assert matches[0].name == "Alfa"
    assert matches[0].category_key == "platano"
    assert len(nearest_canonicals(world.session, vector(1, 0, 0), top_k=1)) == 1


def test_nearest_canonicals_skips_merged_canonicals(db):
    world = db
    survivor = add_canonical(world, "platano", "Alfa", embedding=vector(1, 0, 0))
    add_canonical(
        world,
        "platano",
        "Alfa (antiguo)",
        embedding=vector(1, 0, 0),
        merged_into=survivor,
    )

    matches = nearest_canonicals(world.session, vector(1, 0, 0), top_k=5)

    assert [match.canonical_id for match in matches] == [survivor]


def test_cluster_unmatched_products_rejects_trivial_cluster_size(db):
    with pytest.raises(ValueError, match="min_cluster_size"):
        cluster_unmatched_products(db.session, min_cluster_size=1)


def test_cluster_unmatched_products_groups_close_products(db):
    world = db
    tahini = [
        add_product(world, "T1", "Tahini integral", embedding=vector(0, 1, 0)),
        add_product(world, "T2", "Tahini blanco", embedding=vector(0, 1, 0.15)),
        add_product(world, "T3", "Tahini ecológico", embedding=vector(0, 1, 0.3)),
    ]
    add_product(world, "M1", "Manzana golden", embedding=vector(1, 0, 0))

    clusters = cluster_unmatched_products(world.session)

    assert len(clusters) == 1
    assert set(clusters[0].product_ids) == set(tahini)
    assert clusters[0].mean_similarity >= 0.86
    assert clusters[0].mean_similarity <= 1.0


def test_assign_canonical_updates_product_and_resolves_review(db):
    world = db
    canonical = add_canonical(world, "platano", "Plátano de Canarias", embedding=vector(1, 0, 0))
    product = add_product(world, "M1", "Plátano", embedding=vector(1, 0, 0))
    world.session.execute(
        text("insert into match_review (chain_product_id, candidates) values (:p, '[]'::jsonb)"),
        {"p": product},
    )

    state = run_action(
        world,
        CatalogActionKind.ASIGNAR_CANONICO,
        {
            "product_id": product,
            "canonical_id": canonical,
            "canonical_name": "Plátano de Canarias",
            "confidence": 0.93,
        },
    )

    assert state.assignments[0]["product_id"] == product
    row = (
        world.session.execute(
            text(
                "select canonical_id, match_method, match_confidence "
                "from chain_product where id = :product"
            ),
            {"product": product},
        )
        .mappings()
        .one()
    )
    assert row["canonical_id"] == canonical
    assert row["match_method"] == "embedding"
    assert row["match_confidence"] == pytest.approx(0.93)
    review = (
        world.session.execute(
            text("select status, resolved_at from match_review where chain_product_id = :product"),
            {"product": product},
        )
        .mappings()
        .one()
    )
    assert review["status"] == "accepted"
    assert review["resolved_at"] is not None


def test_assign_canonical_refuses_protected_and_low_confidence(db):
    world = db
    canonical = add_canonical(world, "platano", "Plátano de Canarias", embedding=vector(1, 0, 0))
    other = add_canonical(world, "manzana", "Manzana", embedding=vector(0, 1, 0))
    product = add_product(
        world,
        "M1",
        "Plátano",
        canonical_id=canonical,
        match_method="review",
        embedding=vector(1, 0, 0),
    )

    problem = validate_action(
        world,
        CatalogActionKind.ASIGNAR_CANONICO,
        {
            "product_id": product,
            "canonical_id": other,
            "confidence": 0.95,
        },
    )
    assert problem is not None
    assert "review" in problem

    free = add_product(world, "M2", "Plátano canario", embedding=vector(1, 0, 0))
    low = validate_action(
        world,
        CatalogActionKind.ASIGNAR_CANONICO,
        {
            "product_id": free,
            "canonical_id": canonical,
            "confidence": 0.5,
        },
    )
    assert low is not None
    assert "below" in low

    row = (
        world.session.execute(
            text("select canonical_id, match_method from chain_product where id = :product"),
            {"product": product},
        )
        .mappings()
        .one()
    )
    assert row["canonical_id"] == canonical
    assert row["match_method"] == "review"


def test_assign_canonical_refuses_ean_and_embedding(db):
    world = db
    canonical = add_canonical(world, "platano", "Plátano de Canarias", embedding=vector(1, 0, 0))
    other = add_canonical(world, "manzana", "Manzana", embedding=vector(0, 1, 0))
    products = {
        method: add_product(
            world,
            f"P-{method}",
            "Plátano",
            canonical_id=canonical,
            match_method=method,
            embedding=vector(1, 0, 0),
        )
        for method in ("ean", "embedding")
    }

    for method, product in products.items():
        problem = validate_action(
            world,
            CatalogActionKind.ASIGNAR_CANONICO,
            {
                "product_id": product,
                "canonical_id": other,
                "confidence": 0.95,
            },
        )
        assert problem is not None
        assert method in problem

    untouched = (
        world.session.execute(
            text("select canonical_id, match_method from chain_product where id = any(:ids)"),
            {"ids": list(products.values())},
        )
        .mappings()
        .all()
    )
    assert {(row["canonical_id"], row["match_method"]) for row in untouched} == {
        (canonical, "ean"),
        (canonical, "embedding"),
    }


def test_assign_canonical_rejects_an_incompatible_variant_even_at_high_confidence(db):
    world = db
    plain = add_canonical(world, "leche", "Leche semidesnatada", embedding=vector(1, 0, 0))
    lactose_free = add_canonical(
        world,
        "leche",
        "Leche semidesnatada sin lactosa",
        variant_key="sin_lactosa",
        embedding=vector(1, 0, 0),
    )
    product = add_product(
        world,
        "L1",
        "Leche semidesnatada sin lactosa Dia 1 l",
        chain_category="lacteos",
        embedding=vector(1, 0, 0),
    )

    problem = validate_action(
        world,
        CatalogActionKind.ASIGNAR_CANONICO,
        {"product_id": product, "canonical_id": plain, "confidence": 0.99},
    )

    assert problem is not None
    assert "variante" in problem
    accepted = validate_action(
        world,
        CatalogActionKind.ASIGNAR_CANONICO,
        {"product_id": product, "canonical_id": lactose_free, "confidence": 0.99},
    )
    assert accepted is None
    canonical = world.session.execute(
        text("select canonical_id from chain_product where id = :product"),
        {"product": product},
    ).scalar_one()
    assert canonical is None


def test_propose_new_leaf_creates_category_and_undo_reverts_it(db):
    world = db
    tahini = [
        add_product(world, "T1", "Tahini integral", embedding=vector(0, 1, 0)),
        add_product(world, "T2", "Tahini blanco", embedding=vector(0, 1, 0.15)),
        add_product(world, "T3", "Tahini ecológico", embedding=vector(0, 1, 0.3)),
    ]
    for product in tahini:
        world.session.execute(
            text(
                "insert into match_review (chain_product_id, candidates) values (:p, '[]'::jsonb)"
            ),
            {"p": product},
        )

    state = run_action(
        world,
        CatalogActionKind.PROPONER_HOJA_NUEVA,
        {
            "cluster_id": "cluster_1",
            "label": "Tahini",
            "signals": ["embedding", "category", "name_tokens"],
            "product_ids": tahini,
        },
    )

    record = state.leaf_proposals[0]
    category = (
        world.session.execute(
            text("select key, name, level, parent_id from category where id = :id"),
            {"id": record["category_id"]},
        )
        .mappings()
        .one()
    )
    assert category["key"] == "tahini"
    assert category["name"] == "Tahini"
    assert category["level"] == 3
    assert category["parent_id"] == world.categories["fruta"]

    closure = dict(
        world.session.execute(
            text("select ancestor_id, depth from category_closure where descendant_id = :id"),
            {"id": record["category_id"]},
        ).all()
    )
    assert closure[record["category_id"]] == 0
    assert closure[world.categories["fruta"]] == 1
    assert closure[world.categories["frescos"]] == 2

    canonical = (
        world.session.execute(
            text("select id, category_id, base_unit from canonical_product where id = :id"),
            {"id": record["canonical_id"]},
        )
        .mappings()
        .one()
    )
    assert canonical["category_id"] == record["category_id"]
    assert canonical["base_unit"] == "ud"

    products = (
        world.session.execute(
            text("select id, canonical_id, match_method from chain_product where id = any(:ids)"),
            {"ids": tahini},
        )
        .mappings()
        .all()
    )
    assert {row["canonical_id"] for row in products} == {record["canonical_id"]}
    assert {row["match_method"] for row in products} == {"embedding"}

    proposal = (
        world.session.execute(
            text(
                "select status, category_key, signals_json, product_ids_json "
                "from catalog_leaf_proposal where id = :id"
            ),
            {"id": record["proposal_id"]},
        )
        .mappings()
        .one()
    )
    assert proposal["status"] == "applied"
    assert proposal["category_key"] == "tahini"
    assert sorted(proposal["signals_json"]) == ["category", "embedding", "name_tokens"]
    assert sorted(proposal["product_ids_json"]) == sorted(tahini)

    undone = undo_leaf_proposal(world.session, record["proposal_id"])

    assert undone["status"] == "undone"
    assert undone["products_cleared"] == 3
    assert undone["reviews_queued"] == 3
    proposal = (
        world.session.execute(
            text("select status, undone_at from catalog_leaf_proposal where id = :id"),
            {"id": record["proposal_id"]},
        )
        .mappings()
        .one()
    )
    assert proposal["status"] == "undone"
    assert proposal["undone_at"] is not None
    cleared = (
        world.session.execute(
            text(
                "select canonical_id, match_method, match_confidence "
                "from chain_product where id = any(:ids)"
            ),
            {"ids": tahini},
        )
        .mappings()
        .all()
    )
    assert all(row["canonical_id"] is None for row in cleared)
    assert all(row["match_method"] is None for row in cleared)
    assert all(row["match_confidence"] is None for row in cleared)
    queued = world.session.execute(
        text(
            "select count(*) from match_review "
            "where chain_product_id = any(:ids) and status = 'pending'"
        ),
        {"ids": tahini},
    ).scalar_one()
    assert queued == 3

    again = undo_leaf_proposal(world.session, record["proposal_id"])
    assert again["already_undone"] is True
    assert again["products_cleared"] == 0


def test_propose_new_leaf_enforces_signals_and_products(db):
    world = db
    products = [
        add_product(world, "T1", "Tahini integral"),
        add_product(world, "T2", "Tahini blanco"),
        add_product(world, "T3", "Tahini ecológico"),
    ]

    few_signals = validate_action(
        world,
        CatalogActionKind.PROPONER_HOJA_NUEVA,
        {
            "label": "Tahini",
            "signals": ["embedding"],
            "product_ids": products,
        },
    )
    assert few_signals is not None
    assert "signals" in few_signals

    few_products = validate_action(
        world,
        CatalogActionKind.PROPONER_HOJA_NUEVA,
        {
            "label": "Tahini",
            "signals": ["embedding", "category"],
            "product_ids": products[:2],
        },
    )
    assert few_products is not None
    assert "products" in few_products


def test_propose_new_leaf_rejects_duplicate_product_ids(db):
    world = db
    product = add_product(world, "T1", "Tahini integral")

    problem = validate_action(
        world,
        CatalogActionKind.PROPONER_HOJA_NUEVA,
        {
            "label": "Tahini",
            "signals": ["embedding", "name_tokens"],
            "product_ids": [product, product, product],
        },
    )

    assert problem is not None
    assert "grouped products" in problem
    categories = world.session.execute(
        text("select count(*) from category where key = 'tahini'")
    ).scalar_one()
    assert categories == 0


def test_undo_leaf_proposal_spares_products_reassigned_to_review(db):
    world = db
    tahini = [
        add_product(world, "T1", "Tahini integral", embedding=vector(0, 1, 0)),
        add_product(world, "T2", "Tahini blanco", embedding=vector(0, 1, 0.15)),
        add_product(world, "T3", "Tahini ecológico", embedding=vector(0, 1, 0.3)),
    ]
    state = run_action(
        world,
        CatalogActionKind.PROPONER_HOJA_NUEVA,
        {
            "cluster_id": "cluster_1",
            "label": "Tahini",
            "signals": ["embedding", "category", "name_tokens"],
            "product_ids": tahini,
        },
    )
    record = state.leaf_proposals[0]
    world.session.execute(
        text("update chain_product set match_method = 'review' where id = :product"),
        {"product": tahini[0]},
    )

    undone = undo_leaf_proposal(world.session, record["proposal_id"])

    assert undone["status"] == "undone"
    assert undone["products_cleared"] == 2
    assert undone["reviews_queued"] == 2
    spared = (
        world.session.execute(
            text("select canonical_id, match_method from chain_product where id = :product"),
            {"product": tahini[0]},
        )
        .mappings()
        .one()
    )
    assert spared["canonical_id"] == record["canonical_id"]
    assert spared["match_method"] == "review"
    pending = world.session.execute(
        text(
            "select count(*) from match_review "
            "where chain_product_id = :product and status = 'pending'"
        ),
        {"product": tahini[0]},
    ).scalar_one()
    assert pending == 0


def test_run_catalog_agent_persists_its_trace(db):
    world = db
    add_canonical(world, "platano", "Plátano de Canarias", embedding=vector(1, 0, 0))
    add_product(world, "M1", "Plátano de Canarias", embedding=vector(1, 0, 0))
    add_product(world, "M2", "Manzana golden", embedding=vector(0, 0, 1))
    add_product(world, "T1", "Tahini integral", embedding=vector(0, 1, 0))
    add_product(world, "T2", "Tahini blanco", embedding=vector(0, 1, 0.15))
    add_product(world, "T3", "Tahini ecológico", embedding=vector(0, 1, 0.3))

    summary = run_catalog_agent(world.session, tau_high=0.88, top_k=3)

    assert summary["assigned"] == 1
    assert summary["proposed_leaves"] == 1
    assert summary["sent_to_review"] == 4
    assert summary["steps"] == 6
    assert summary["status"] == "completed"

    run = trace.get_run(world.session, summary["run_id"])
    assert run is not None
    assert run.agent_name == "catalog"
    assert run.status == "completed"
    assert run.steps_count == 6
    assert len(run.steps) == 6
    assert all(step.chosen_action for step in run.steps)
    assert {step.observation_json["kind"] for step in run.steps} == {
        CatalogObservationKind.UNMATCHED_PRODUCT.value,
        CatalogObservationKind.CLUSTER_CANDIDATE.value,
    }
    assert run.steps[-1].observation_json["kind"] == CatalogObservationKind.CLUSTER_CANDIDATE
    assert run.steps[-1].chosen_action.startswith(CatalogActionKind.PROPONER_HOJA_NUEVA.value)


def test_run_catalog_agent_never_assigns_across_variants(db):
    world = db
    add_canonical(world, "leche", "Leche semidesnatada", embedding=vector(1, 0, 0))
    product = add_product(
        world,
        "L1",
        "Leche semidesnatada sin lactosa Dia 1 l",
        chain_category="lacteos",
        embedding=vector(1, 0, 0),
    )

    summary = run_catalog_agent(world.session, tau_high=0.5, top_k=5)

    assert summary["assigned"] == 0
    assert summary["sent_to_review"] == 1
    canonical = world.session.execute(
        text("select canonical_id from chain_product where id = :product"),
        {"product": product},
    ).scalar_one()
    assert canonical is None


def test_run_catalog_agent_applies_a_low_cosine_match_verified_by_the_model(db):
    world = db
    canonical = add_canonical(
        world,
        "leche",
        "Leche semidesnatada sin lactosa",
        variant_key="sin_lactosa",
        embedding=vector(1, 0, 0),
    )
    product = add_product(
        world,
        "L1",
        "Leche semidesnatada sin lactosa Dia 1 l",
        chain_category="lacteos",
        embedding=vector(1, 0.88),
    )
    verifier = FakeCatalogVerifier("asignar_canonico:0")

    summary = run_catalog_agent(
        world.session,
        top_k=5,
        policy=LLMVerifiedCatalogPolicy(verifier, model_name="fake-verifier"),
    )

    assert verifier.calls == 1
    assert summary["assigned"] == 1
    row = (
        world.session.execute(
            text("select canonical_id, match_confidence from chain_product where id = :product"),
            {"product": product},
        )
        .mappings()
        .one()
    )
    assert row["canonical_id"] == canonical
    assert row["match_confidence"] == pytest.approx(1 / math.sqrt(1 + 0.88**2), abs=1e-4)


def test_calibrate_thresholds_and_export_audit_sample(db):
    world = db
    alpha = add_canonical(world, "platano", "Alfa", embedding=vector(1, 0, 0))
    beta = add_canonical(world, "manzana", "Beta", embedding=vector(0, 1, 0))
    add_canonical(world, "leche", "Delta", embedding=vector(0.75, 0.66, 0))
    add_product(
        world,
        "P1",
        "Perfecto alfa",
        canonical_id=alpha,
        match_method="rule",
        embedding=vector(1, 0, 0),
    )
    add_product(
        world,
        "P2",
        "Perfecto beta",
        canonical_id=beta,
        match_method="rule",
        embedding=vector(0, 1, 0),
    )
    add_product(
        world,
        "P3",
        "Dudoso bajo",
        canonical_id=alpha,
        match_method="rule",
        embedding=vector(0.6, 0.8, 0),
    )
    add_product(
        world,
        "P4",
        "Dudoso alto",
        canonical_id=alpha,
        match_method="rule",
        embedding=vector(0.8, 0.6, 0),
    )

    summary = calibrate_thresholds(world.session, sample_size=10)
    assert summary["sample_size"] == 4
    assert len(summary["thresholds"]) == 7
    by_threshold = {row["threshold"]: row for row in summary["thresholds"]}
    assert by_threshold[0.75]["auto_assigned"] == 3
    assert by_threshold[0.75]["coverage"] == pytest.approx(0.75)
    assert by_threshold[0.75]["precision"] == pytest.approx(2 / 3, abs=1e-3)
    assert by_threshold[0.85]["auto_assigned"] == 2
    assert by_threshold[0.85]["precision"] == pytest.approx(1.0)

    sample = export_audit_sample(world.session, chain_code="mercadona", sample_size=10)
    assert len(sample) == 4
    assert set(sample[0]) == {"product_id", "chain_sku", "name", "chain_category"}
    assert "canonical_id" not in sample[0]
    repeat = export_audit_sample(world.session, chain_code="mercadona", sample_size=10)
    assert repeat == sample


def test_cli_parses_every_subcommand():
    parser = build_parser()
    cases = (
        ["embed"],
        ["calibrate"],
        ["run"],
        ["undo-leaf", "7"],
        ["audit-sample", "--chain", "mercadona"],
    )
    for argv in cases:
        args = parser.parse_args(argv)
        assert args.command == argv[0]


def test_cli_parses_the_verifier_policy():
    parser = build_parser()

    llm = parser.parse_args(["run", "--policy", "llm", "--model", "gemini-3.5-flash-lite"])

    assert llm.policy == "llm"
    assert llm.model == "gemini-3.5-flash-lite"
    assert parser.parse_args(["run"]).policy == "threshold"


def _literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


def _seed(session: Session) -> World:
    session.execute(
        text(
            "truncate catalog_leaf_proposal, agent_step, agent_run, product_match, "
            "match_review, chain_product, canonical_product, category_closure, category, "
            "chain_category, brand, chain restart identity cascade"
        )
    )
    chain_id = session.execute(
        text("insert into chain (code, name) values ('mercadona', 'Mercadona') returning id")
    ).scalar_one()
    specs = (
        ("frescos", "Frescos", 1, None, None),
        ("fruta", "Fruta", 2, "frescos", None),
        ("platano", "Plátano", 3, "fruta", "kg"),
        ("manzana", "Manzana", 3, "fruta", "kg"),
        ("lacteos", "Lácteos", 2, "frescos", None),
        ("leche", "Leche", 3, "lacteos", "l"),
    )
    categories: dict[str, int] = {}
    for key, name, level, parent, unit in specs:
        categories[key] = session.execute(
            text(
                "insert into category (key, name, level, parent_id, base_unit) "
                "values (:key, :name, :level, :parent, :unit) returning id"
            ),
            {
                "key": key,
                "name": name,
                "level": level,
                "parent": categories.get(parent) if parent else None,
                "unit": unit,
            },
        ).scalar_one()
    parents = {key: parent for key, _name, _level, parent, _unit in specs}
    for key in categories:
        depth = 0
        node: str | None = key
        while node is not None:
            session.execute(
                text(
                    "insert into category_closure (ancestor_id, descendant_id, depth) "
                    "values (:ancestor, :descendant, :depth)"
                ),
                {
                    "ancestor": categories[node],
                    "descendant": categories[key],
                    "depth": depth,
                },
            )
            node = parents[node]
            depth += 1
    chain_categories = {}
    for code, name, key in (("2", "Fruta", "fruta"), ("3", "Lácteos", "lacteos")):
        chain_categories[key] = session.execute(
            text(
                "insert into chain_category (chain_id, code, name, category_id) "
                "values (:chain, :code, :name, :category) returning id"
            ),
            {"chain": chain_id, "code": code, "name": name, "category": categories[key]},
        ).scalar_one()
    return World(session, chain_id, categories, chain_categories)
