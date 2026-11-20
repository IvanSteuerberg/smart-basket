---
type: Evaluation
title: Catalog agent calibration and pgvector benchmark (I14)
description: Calibration of pgvector cosine similarity (gemini-embedding-001, 768 dims) over the 2,185 canonical products and 4,307 Mercadona products from I12, showing precision and coverage across thresholds.
tags: [evaluation, agents, pgvector, embeddings, matching]
status: draft
generated:
  by: antigravity/gemini-4-neon
  at: 2026-11-20T00:10:00+01:00
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
  2. `pgvector` is best used as a **high-recall top-k candidate retriever** and **one of the two independent signals** for clustering new leaves (`cluster_unmatched_products`), while autonomous assignment above 90 % requires pairing `pgvector` top-k with variant-key filtering and/or an LLM verifier over the top-5 candidates (next step once the live Dia catalog is crawled in the worker with Playwright + `xvfb-run`).
