---
type: Architecture Overview
title: Agents in Smart Basket
description: Draft map of the system's agents, their shared harness and memory, and the observation that iteration 12 already ran a multi-agent process outside the product.
tags: [architecture, agents, llm, recommender, matching]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-16T20:00:00+01:00
sources:
  - id: d0001
    resource: /decisions/0001-agent-as-orchestrator.md
    title: 0001 Agent as orchestrator
  - id: d0020
    resource: /decisions/0020-rule-based-canonical-matching.md
    title: 0020 Rule-based canonical matching
  - id: class-2026-09-14
    resource: ../../docs/registro-actividad/registro-actividad.tex
    title: Class notes of 2026-09-14 (local AI and agents are valued)
---
Overview agreed with the author on 2026-11-16 and recorded in decision [0022](/decisions/0022-recommender-agent-and-system-agents.md) (Señal de Tiempo 9), which revises [0001](/decisions/0001-agent-as-orchestrator.md) and [0005](/decisions/0005-local-first-ai-models.md). Where this note and 0022 differ, 0022 rules.

# Why this note

The course requires a **recommender agent**. A multi-agent design and local AI score higher (class of 2026-09-14). As implemented up to iteration 12, the system uses an LLM in a single structured-output call for the list lines the rules cannot resolve. The flow is a fixed pipeline with no perceive-act-observe loop.

# Key observation for the final report

**Iteration 12 already ran a multi-agent process, but it lives in the development sessions, not in the product.** To classify the catalog ([0020](/decisions/0020-rule-based-canonical-matching.md)):

* one model labelled every product blind;
* a second arbitrated its disagreements with the rules;
* a third reviewed every leaf for homogeneity;
* a fourth, which took no part in the fixes, measured the result;
* an orchestrator consolidated the outputs and the author approved them.

Every role was distinct, and the work reached 95.6 % accuracy on an independent sample. The next step is to move that process into the system, where it runs on every scrape without the development session.

# Definition

The recommender is a **rational agent with a perceive-act loop around it**:

* **The rational core decides the basket.** The optimizer maximizes cost and time, with deterministic numbers, as in 0001.
* **The LLM loop decides what to do when the world does not fit the core's model.** Examples are a vague line, a product missing everywhere, a near tie, or a change asked by the shopper. The loop asks, searches, tries another scenario and calls the optimizer again.

Agreed points:

* **The loop starts on an observation.** The first plan still comes from the fast pipeline, so NFR-01 holds.
* **Each step picks one action from a closed set of typed actions,** with schema-constrained output. That set is part of the harness, and it is what makes small local models usable.
* **The model is chosen by measurement,** with the rule fixed before measuring. Local models and decision models are candidates; Gemini is the fallback only.

# Agents and shared harness

All agents share one harness (loop, step limit, validation, state, trace), each with its own action set. They do not talk to each other: they coordinate through the database.

| Agent | Runs | Role | Order |
| --- | --- | --- | --- |
| Recommender | Online, with the shopper | Resolves what the pipeline cannot, explores scenarios, explains. Required by the course | 1 |
| Catalog agent | On every scrape | Rules first; for the rest, finds similar products with pgvector, inspects candidate leaves and assigns, proposes a new leaf or flags. Its output is what the recommender buys from | 2 |
| Watcher | On every scrape | Triage of price anomalies (scraping error, promotion, real change) | 3 |
| Conversational BI | On demand | Read-only questions on the `bi` schema | Extra |
| Leaflets | — | Extraction rather than an agent; no chain to read yet | SWOT, future work |

The catalog agent is a good fit for local AI because it runs offline, so latency does not matter. In iteration 12 the classification ran on strong cloud models, so the local version must be measured the same way, on a reviewed sample.

# Author involvement

The author wants as little interaction as possible:

* Agents apply what they are confident about.
* Quality is guarded by sampled audits by another model, as in iteration 12, instead of approving item by item.
* Only real conflicts reach the author.

# Memory

* **Shared memory of the world:** PostgreSQL, with the catalog, canonicals, prices, the `bi` star schema and embeddings in pgvector.
* **Decision memory:** the agents' traces and decisions, such as the match decisions file of 0020. Past decisions can be retrieved by similarity as examples for new ones, so the agents need the author less over time.
