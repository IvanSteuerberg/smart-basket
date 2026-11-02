---
type: Architecture Decision
title: "0005 Local-first AI models"
description: Local embeddings and a local-first orchestrator LLM on the author's laptop, with Gemini as fallback, a single agent and a pre-registered benchmark rule.
tags: [decision, llm, embeddings, recommender]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-31T19:30:00+01:00
sources:
  - id: st5
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 5
---
# Context

The MVP has no recurring cost, a 5 s p95 target for a 30-item list ([NFR-01](/requirements/non-functional.md)) and a recommender agent that only orchestrates deterministic tools ([0001](/decisions/0001-agent-as-orchestrator.md)). The app is for personal use and is not published, so it runs on the author's laptop: Intel Core Ultra 7 258V, 32 GB of shared RAM and an integrated Intel Arc 140V GPU, which Ollama uses through Vulkan (the NPU is not used). The author prefers local models.

Three sources were consulted (Claude, Gemini and DeepSeek).[^st5] All agree that a 3-8B model on CPU cannot write a full 30-item interpretation in 5 s, but that the LLM output drops to about 150-250 tokens when a rule-based preprocessor resolves most lines first. At that size a 2-4B model on the laptop may meet the target; this has to be measured.

# Decision

1. **Embeddings run locally.** The model is chosen with the [AI model benchmark](/evaluation/ai-model-benchmark.md) among Qwen3-Embedding-0.6B, EmbeddingGemma 2 and multilingual-e5-small. Format, quantity, variant and brand are extracted with rules at ingestion and stored as columns to filter on; the vector only decides the product type ([0004](/decisions/0004-canonical-product-model.md)).
2. **The orchestrator LLM is local first:** Ollama on the laptop (Arc iGPU or CPU, whichever is faster). Candidates: Qwen3.5 0.8B, 2B and 4B, Gemma 4 E2B and E4B (Granite 4.2 3B was discarded in the first benchmark pass). Gemini Flash-Lite on the free API tier (currently Gemini 3.5 Flash-Lite) is the fallback, behind the same provider interface ([NFR-12](/requirements/non-functional.md)).
3. **A single agent with at most two LLM calls** per recommendation: one to interpret only the lines the rule-based preprocessor could not resolve, plus soft preferences, and one to write the explanation. Figures in the explanation come from templates. A multi-agent design is rejected for its latency, quota use and failure points.
4. **The system always returns a basket.** Without an LLM, the list is interpreted by rules only and the explanation comes from a template ([FR-41](/requirements/functional.md)).
5. **The interpreted list is stored** with each recommendation, so it can be recomputed without calling the LLM again ([NFR-05](/requirements/non-functional.md)).

## Acceptance rule

Fixed before measuring. The local LLM stays primary if, on the laptop and over the benchmark lists:

* the plan (items, stores, cost and minutes) is ready in at most 5 s at p95,
* at least 95 % of tool calls carry valid JSON on the first attempt, and
* list interpretation reaches an F1 of at least 0.90.

Otherwise Gemini interprets the list and the local model stays as fallback. The explanation stays local as long as it meets the streaming targets of NFR-01.

# Consequences

* The first benchmark pass (2026-11-01) confirmed that no small model interprets a whole list within 5 s, even on the Arc, so the rule-based preprocessor is required; Qwen3.5 0.8B and 2B and Gemma 4 E4B on the Arc lead. See the [AI model benchmark](/evaluation/ai-model-benchmark.md).

* By default no data leaves the laptop, and the demo works offline.
* The rule-based preprocessor (quantities, units, brands, dietary terms) becomes a core component with its own tests.
* Ollama may run natively on Windows, outside Docker Compose, to reach the Arc iGPU ([NFR-10](/requirements/non-functional.md)).
* The embedding part of the benchmark needs real product names, so it runs after the data-source viability study.
* The Gemini API terms allow only the paid tier when an app is made available to users in the EEA, Switzerland or the UK. The free tier covers the author's own use; a published app would pay about 0.001-0.004 $ per recommendation with Gemini 3.5 Flash-Lite (November 2026 prices) or keep the fallback local.

# Revisit when

* The benchmark results are in (this decision becomes `stable` or switches the primary LLM).
* Gemini changes its free tier or retires Flash-Lite.
* The app is published to other users (paid Gemini tier required).
* The app moves to a different machine, especially one with a dedicated GPU (local becomes easier) or a small VPS (local becomes harder).

[^st5]: Prompt log, Señal de Tiempo 5 (Claude, Gemini 3.8 Flash and DeepSeek V4.1 Flash with web search; the rule-based draft and the local explanation come from DeepSeek).
