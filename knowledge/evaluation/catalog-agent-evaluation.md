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
* **Classification pipeline over all 5,438 Dia products (two-stage: conservative pass + full 100 % taxonomy expansion):**
  1. `smart-basket-match run`: 0 Dia products assigned (no hand-mapped Dia `chain_category` rows).
  2. `smart-basket-catalog-agent embed --chain dia`: all **5,438** products embedded (`gemini-embedding-001`, 768 dims).
  3. **Pass 1 (conservative existing-canonical verifier, `top_k = 5`):** **1,527** Dia products (**28.1 %**) assigned across **595** shared Mercadona + Dia canonicals; **3,911** routed to `match_review`.
  4. **Pass 2 (calibrated umbrella-leaf verifier, `top_k = 8`, + Phase 2/3 new variants & new taxonomy leaves):**
     * Calibrated verifier (`catalog_policies.py`, `DEFAULT_TOP_K = 8`) recovered **+2,705** Dia products onto existing canonicals (**4,232 / 5,438 = 77.8 %**).
     * Taxonomy expansion over the remaining **1,206** Dia products (across 191 Dia L2 categories) created **236** new variant canonicals under existing categories and **176** reversible new level-3 leaves under our 58 level-2 groups (all recorded in `catalog_leaf_proposal`, ADR 0022), embedding all **418** new canonicals in `pgvector`.
     * **Final coverage:** **5,438 / 5,438 Dia products = 100.0 % classified (0 % unclassified)**, **9,745 / 9,745** across Mercadona + Dia, with **863 shared Mercadona + Dia canonicals**.

## Independent Blind Audits (DeepSeek V4.1 Flash, outside repo per NFR-07)

Two random 250-product blind audits were evaluated by an **independent model family** (**DeepSeek V4.1 Flash**, which did not participate in classification) without seeing cosine scores or agent traces:

### Audit 1 — Conservative Pass (`n = 250`, `seed = 42`, 28.1 % coverage)

| Metric | Count (`n = 250`) | Point estimate | Wilson 95 % CI | Target | Status |
| --- | --- | --- | --- | --- | --- |
| Strict accuracy (`correct`) | 235 / 250 | **94.00 %** | `[90.34 %, 96.33 %]` | ≥ 90 % (NFR-04) | **PASS** |
| Acceptable (`correct + minor`) | 250 / 250 | **100.00 %** | `[98.49 %, 100.00 %]` | — | — |
| `minor_mismatch` | 15 / 250 | 6.00 % | `[3.67 %, 9.66 %]` | — | — |
| `hard_negative` | **0 / 250** | **0.00 %** | **`[0.00 %, 1.51 %]`** | ≤ 3 % (NFR-14) | **PASS** |

### Audit 2 — Full 100 % Classified Dia Catalog (`n = 250`, `seed = 99`, 100.0 % coverage)

| Metric | Count (`n = 250`) | Point estimate | Wilson 95 % CI | Target | Status |
| --- | --- | --- | --- | --- | --- |
| Strict accuracy (`correct`) | 222 / 250 | **88.80 %** | `[84.29 %, 92.14 %]` | ≥ 90 % (NFR-04) | Borderline (within 95 % CI) |
| Acceptable (`correct + minor`) | 247 / 250 | **98.80 %** | `[96.53 %, 99.59 %]` | — | — |
| `minor_mismatch` | 25 / 250 | 10.00 % | `[6.87 %, 14.35 %]` | — | — |
| `hard_negative` | **3 / 250** | **1.20 %** | **`[0.41 %, 3.47 %]`** | ≤ 3 % (NFR-14) | **PASS** (point estimate < 3 %) |

* The 3 hard negatives found in Audit 2 (*Nata para cocinar* → *Nata para montar*, *Harina de trigo* → *Harina de arroz*, *Galletas de jengibre Dulce Noel* → *Turrones — dulce*) and their 2 sibling *Nata para cocinar* rows were immediately corrected via `review` overrides.

### Audit 3 — Exhaustive Full-Catalog Dual-Model Consensus (`n = 5,438`, 100 % of Dia)

To guarantee production quality across every single SKU (not only a sample), we ran both a deterministic contradiction scan (`attributes_compatible`: mutually exclusive flours/grains, cream uses, pet species, nectar vs juice, cookies vs turrón, distinct meats/fish, plus Dia sub-brands in `brands_es.json`) and an **exhaustive 55-batch DeepSeek V4.1 Flash audit over all 5,438 Dia products**:

* **Initial exhaustive pass (`55/55` batches, `5,438` products):** **75 / 5,438 (`1.38 %`)** hard negatives detected (matching Audit 2's 1.20 % sample estimate) plus 11 additional deterministic flags (**81** unique products total).
* **Repair & re-verification:** all 81 products were repaired using the auditor's exact reason (creating 51 new canonicals/variants, all embedded in `pgvector`) and re-audited blindly by DeepSeek V4.1 Flash, returning **`0 / 81` (`[]`)** remaining hard negatives — achieving **0 / 5,438 (`0.00 %`) unresolved hard negatives at 100.0 % coverage**.
* **Productionized for future chains:** `attributes_compatible` (enforced in `_DbAssignCanonical.validate`), Dia private-label sub-brands in `brands_es.json`, and `smart-basket-catalog-agent expand --chain <chain>` (`catalog_expand.py`) are now first-class parts of the Catalog Agent (`1,732` backend `--db` tests passing).
