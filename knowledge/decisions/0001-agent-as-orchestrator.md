---
type: Architecture Decision
title: "0001 Agent as orchestrator"
description: The required recommender agent is an LLM orchestrator; numbers come from deterministic tools.
tags: [decision, recommender, llm]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: st3
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 3
---
# Context

The course requires a "recommender agent". Deciding what to buy and where is a combinatorial optimization problem, and LLMs do not guarantee optimal or reproducible results on it.[^st3]

# Decision

The recommender agent is an LLM-based orchestrator. It interprets the shopping list and soft preferences, calls tools (equivalence search, travel-time matrix, basket optimizer) and explains the recommendation. All prices, times and the optimal basket are computed by deterministic code.

# Consequences

* Recommendations are verifiable and reproducible; the LLM can be swapped without changing results.
* Tools need clear, typed interfaces the agent can call.

[^st3]: Prompt log, Señal de Tiempo 3 (Claude and Gemini agree).
