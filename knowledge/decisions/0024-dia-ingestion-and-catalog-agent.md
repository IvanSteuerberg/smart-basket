---
type: Architecture Decision
title: "0024 Dia ingestion adapter and Catalog Agent foundation"
description: Multi-chain postal_code ingestion, Dia plp-insight adapter with headed Playwright transport, 768-dim pgvector HNSW embeddings (gemini-embedding-001), and Catalog Agent on the shared ADR 0022 harness.
tags: [decision, ingestion, agents, pgvector, matching]
status: draft
generated:
  by: antigravity/gemini-4-neon
  at: 2026-11-20T13:37:00+01:00
sources:
  - id: adr0016
    resource: /decisions/0016-ingestion-adapters.md
    title: 0016 Ingestion adapters
  - id: adr0020
    resource: /decisions/0020-rule-based-canonical-matching.md
    title: 0020 Rule-based canonical matching and canonical baskets
  - id: adr0022
    resource: /decisions/0022-recommender-agent-and-system-agents.md
    title: 0022 Recommender agent and system agents
  - id: eval
    resource: /evaluation/catalog-agent-evaluation.md
    title: Catalog agent calibration and pgvector benchmark (I14)
---
# Context

Up to iteration 13, Smart Basket only ingested Mercadona (`warehouse` zones) and product-to-canonical matching was rule-based plus offline development-session reviews. Iteration 14 introduces the second chain (**Dia**, 7 stores in León) and builds the **Catalog Agent** specified in [0022](/decisions/0022-recommender-agent-and-system-agents.md) on top of the shared harness and `pgvector`.

A live probe of `dia.es` confirmed:
* Akamai returns `403 Access Denied` to plain HTTP and headless browsers, but a normal headed browser (`xvfb-run` + Chromium in Linux Docker) receives `200 OK` without login or CAPTCHA.
* Setting León postal code `24001` is a single `PUT /api/v1/common-aggregator/save-shipping-address?new_postal_code=24001&skip_dry_run=true` call inside the browser session.
* `/api/v1/plp-insight/initial_analytics{path}?navigation={code}&page={page}` returns both the full 31-root category tree (`menu_analytics`) and paginated products (`page_product_analytics` with `item_id`, `item_name`, `item_brand`, `price`, `stock_availability`).

# Decision

1. **Multi-chain ingestion (`ingestion/store.py`, `ingestion/dia.py`):** generalize `store.py` to honor `adapter.zone_kind` (`"warehouse"` for Mercadona, `"postal_code"` for Dia `24001`), register chains in `ADAPTERS`, and implement `DiaAdapter` over an injectable `DiaTransport` (`PlaywrightDiaTransport` lazy-imported for headed Chromium / `xvfb-run`).
2. **Public-catalog embeddings (`llm/embeddings.py`, migration `0010`):** support both `GeminiEmbeddingProvider` (`gemini-embedding-001`, 768 dims, batching <= 100 with HTTP 429 exponential backoff) and `OllamaEmbeddingProvider` (`/api/embed`). Fix `canonical_product.embedding` and `chain_product.embedding` to `vector(768)` with HNSW `vector_cosine_ops` indexes. Public catalog text raises no privacy concern.
3. **Shared harness + Catalog Agent (`agent/core.py`, `agent/catalog_agent.py`, `agent/catalog_executors.py`):** generalize `AgentHarness` with injectable `candidate_generator`, `fallback_policy`, `low_confidence_action`, and `pause_action=None` (offline). The Catalog Agent writes `agent_run`/`agent_step` traces with `agent_name = "catalog"`, never overwrites `PROTECTED_METHODS` (`review`, `ean`, `embedding`), and enforces ADR 0022's reversible new-leaf guard (`>= 2` distinct signal families and `>= 3` distinct products) backed by `catalog_leaf_proposal` + `undo-leaf`.
4. **BI telemetry (`0011_bi_catalog_agent.py`):** expose `bi.v_catalog_leaf_proposal` and `bi.v_catalog_agent_summary` to `bi_reader` (no PII) and add a 6th card to `scripts/metabase_agent_dashboard.py`.
5. **LLM top-5 verifier + deterministic variant-key guard (`agent/catalog_policies.py`, I15):** because raw `pgvector` top-1 cosine alone reaches 75.7–81.5 % precision on 300 Mercadona products ([catalog-agent-evaluation.md](/evaluation/catalog-agent-evaluation.md)), below NFR-04 (90 %), autonomous assignment uses two independent layers:
   * **`variants_compatible(product_name, canonical_variant_key)`** (offline, deterministic, also enforced inside `_DbAssignCanonical.validate`): blocks sibling-variant mismatches (`sin lactosa`, `sin gluten`, `integral`, `descafeinado`, `sin alcohol`, `zero`, milk fat levels `entera`/`semidesnatada`/`desnatada`, oils, and carrier flavours).
   * **`LLMVerifiedCatalogPolicy`** (`--policy llm`, `gemini-3.5-flash-lite` by default, cosine floor `0.60`, closed enum JSON Schema, HTTP 429 exponential backoff): verifies top-5 compatible candidates and routes uncertain items to `match_review`.
6. **Production Docker `worker` image and Dia category endpoint (`backend/Dockerfile`, `ingestion/dia.py`, I15):** split `Dockerfile` into slim `runtime` (`api`, `migrate`) and `worker` (adds `xvfb`, `xauth`, `libatomic1`, `playwright`, Chromium, `/tmp/.X11-unix`, `XDG_CONFIG_HOME=/tmp/.config`, `shm_size: 1gb`, and `/usr/local/bin/with-xvfb`). Bootstrap the 31-L1 / 267-L2 menu from `plp-insight/initial_analytics`, then fetch per-category listings from `/api/v1/plp-back/reduced` (`plp_items`, properly capitalized names, `price_per_unit`, exact category filtering) with a 30 s `AbortSignal.timeout`.

# Consequences

* **9,745 live León products** are now in PostgreSQL (**4,307** Mercadona + **5,438** Dia `24001`), all embedded with `gemini-embedding-001` (768 dims) and HNSW indexed.
* **1,527 Dia products (28.1 %)** are automatically assigned across **595 shared Mercadona + Dia canonicals**; **3,911** are queued conservatively in `match_review`.
* Independent 250-product blind audit by **DeepSeek V4.1 Flash** confirmed **94.00 % strict accuracy** (Wilson 95 % CI `[90.34 %, 96.33 %]`, meeting NFR-04 ≥ 90 %) and **0.00 % hard negatives** (`0/250`, Wilson 95 % CI `[0.00 %, 1.51 %]`, meeting NFR-14 ≤ 3 %).
* `24001` vs `24008` probe showed 0/18 price differences in León, so one zone (`24001`) suffices for Dia León.
* Multi-chain recommendation (`Mercadona` + `Dia`) is verified both in integration tests (`tests/recommender/test_multichain.py`) and live against `/api/recommendations` in León.

# Revisit when

* New chains (Carrefour, Alcampo, Gadis, Lidl) are onboarded or when Dia's `3,911` reviewed items are clustered into new canonical leaves (`PROPONER_HOJA_NUEVA`).
