---
type: Evaluation
title: Catalog agent calibration and live Dia blind audit (I14–I15)
description: Calibration of pgvector cosine similarity on Mercadona (I14) and independent 250-product blind audit of the LLM-verified Catalog Agent over the full 5,438-product live Dia León catalog (I15).
tags: [evaluation, agents, pgvector, embeddings, matching]
status: draft
generated:
  by: antigravity/gemini-4-neon
  at: 2026-11-20T13:37:00+01:00
sources:
  - id: adr0020
    resource: /decisions/0020-rule-based-canonical-matching.md
    title: 0020 Rule-based canonical matching and canonical baskets
  - id: adr0022
    resource: /decisions/0022-recommender-agent-and-system-agents.md
    title: 0022 Recommender agent and system agents
---
# Protocol

On 2026-11-20, all **2,185** canonical products and **4,307** Mercadona products in PostgreSQL were embedded with `gemini-embedding-001` (`outputDimensionality = 768`, `SEMANTIC_SIMILARITY`) and indexed with HNSW (`vector_cosine_ops`, migration `0010`).

We then ran `smart-basket-catalog-agent calibrate --chain mercadona --sample-size 300`, measuring whether a product's assigned canonical from iteration 12 (`95.6 %` audited accuracy) beats every other non-merged canonical in cosine similarity, across thresholds `0.75` to `0.95`.

# Results (Mercadona calibration, n = 300)

| Cosine threshold (`tau`) | Top-1 precision | Coverage | Auto-assigned (of 300) |
| --- | --- | --- | --- |
| `0.75` | 75.7 % | 100.0 % | 300 |
| `0.80` | 75.7 % | 100.0 % | 300 |
| `0.85` | 77.0 % | 98.3 % | 295 |
| `0.88` | 77.7 % | 97.3 % | 292 |
| `0.90` | 79.0 % | 88.7 % | 266 |
| `0.92` | 79.2 % | 67.3 % | 202 |
| `0.95` | 81.5 % | 30.7 % | 92 |

# Findings

* **Dense cosine similarity alone does not reach NFR-04 (90 %) or NFR-14 (<= 3 % hard negatives):** even at `tau = 0.95`, raw embedding top-1 precision is **81.5 %** (at 30.7 % coverage). With 2,185 fine-grained canonicals, sibling variants (`sin lactosa`, `integral`, `sin azúcar`, flavours) sit very close in embedding space (~0.93–0.96 cosine).
* **Implication for the Catalog Agent:**
  1. Deterministic rules (`matching/rules.py`) MUST always run first (ADR 0020).
  2. `pgvector` is best used as a **high-recall top-k candidate retriever** and **one of the two independent signals** for clustering new leaves (`cluster_unmatched_products`), while autonomous assignment above 90 % requires pairing `pgvector` top-k with variant-key filtering and an LLM verifier over the top-5 candidates.

# Live Dia León (`24001`) Ingestion and Blind Audit (I15, 2026-11-20)

## Ingestion & Classification Pipeline

* **Full live Dia León (`24001`) crawl inside Docker (`worker` target with Chromium + `with-xvfb`):** **5,438** active products ingested across 267 L2 categories via `/api/v1/plp-back/reduced` (266/267 categories succeeded; 1 category `L2082` returned invalid JSON).
* **Zone price check (ADR 0006):** comparing `24001` vs `24008` on `quesos/curado` (`L2007`, 18 products) showed **0 price differences** (18/18 identical), confirming a single zone (`24001`) suffices for León.
* **Classification pipeline over all 5,438 Dia products:**
  1. `smart-basket-match run`: 0 Dia products assigned (no hand-mapped Dia `chain_category` rows).
  2. `smart-basket-catalog-agent embed --chain dia`: all **5,438** products embedded (`gemini-embedding-001`, 768 dims).
  3. `smart-basket-catalog-agent run --chain dia --policy llm` (`LLMVerifiedCatalogPolicy` with `gemini-3.5-flash-lite` + deterministic `variants_compatible` guard, cosine floor `0.60`): **1,527** Dia products (**28.1 %**) assigned automatically across **595** shared Mercadona + Dia canonicals; **3,911** (**71.9 %**) routed conservatively to `match_review` (mostly Dia-only brands/SKUs not present in Mercadona's 2,185-canonical seed).

## Independent Blind Audit (`n = 250`, seed `42`)

A random sample of **250** automatically assigned Dia products (`seed = 42`, stored outside the repository per NFR-07) was audited blindly by an **independent model family** (**DeepSeek V4.1 Flash**, which did not participate in classification) without seeing cosine scores or agent traces. Each pair was graded as `correct`, `minor_mismatch`, or `hard_negative` (never interchangeable).

| Metric | Count (`n = 250`) | Point estimate | Wilson 95 % CI | Target | Status |
| --- | --- | --- | --- | --- | --- |
| Strict accuracy (`correct`) | 235 / 250 | **94.00 %** | `[90.34 %, 96.33 %]` | ≥ 90 % (NFR-04) | **PASS** (lower bound > 90 %) |
| Acceptable (`correct + minor`) | 250 / 250 | **100.00 %** | `[98.49 %, 100.00 %]` | — | — |
| `minor_mismatch` | 15 / 250 | 6.00 % | `[3.67 %, 9.66 %]` | — | — |
| `hard_negative` | **0 / 250** | **0.00 %** | **`[0.00 %, 1.51 %]`** | ≤ 3 % (NFR-14) | **PASS** (upper bound < 3 %) |

* **Conclusion:** Pairing `pgvector` top-5 retrieval with the deterministic `variants_compatible` guard and `LLMVerifiedCatalogPolicy` (`gemini-3.5-flash-lite`) lifts precision from **75.7–81.5 %** (raw cosine) to **94.00 % strict accuracy** (`[90.34 %, 96.33 %]`) with **0.00 % hard negatives** (`[0.00 %, 1.51 %]`), satisfying both NFR-04 and NFR-14 with statistical margin on a live unseen supermarket chain.
