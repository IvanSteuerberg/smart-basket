---
type: Architecture Decision
title: "0004 Canonical product model"
description: Equivalences resolved by mapping every scraped product to a canonical product.
tags: [decision, recommender, data-model]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: st3
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 3
---
# Context

Storing equivalences as free pairwise links lets them chain: skimmed and semi-skimmed milk are similar, semi-skimmed and whole are similar, so skimmed ends up "equivalent" to whole (semantic drift). That breaks functional equivalence, especially for allergies or diets.[^st3]

# Decision

Every scraped product is assigned to one canonical product, by nearest-neighbour search on embeddings above a confidence threshold or by deterministic rules. Products sharing a canonical product are equivalents, so finding equivalents is a single-hop join.

# Consequences

* No transitive drift; equivalence is explicit and auditable.
* The canonical catalog must be built and maintained, with a review path for low-confidence assignments.
* Pack size and unit price still need checking: one canonical product can come in different formats.

# Open questions

* How canonical products are created (manual seed, clustering, LLM-assisted).
* Granularity: how specific a canonical product must be.

[^st3]: Proposed by Gemini in prompt log Señal de Tiempo 3.
