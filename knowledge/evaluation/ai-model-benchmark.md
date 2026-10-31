---
type: Test Plan
title: AI model benchmark
description: How the local and cloud models of decision 0005 are measured on the author's laptop, and the rule that picks them.
tags: [evaluation, llm, embeddings, benchmark]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-31T19:30:00+01:00
sources:
  - id: st5
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 5
---
Measures the candidates of [0005](/decisions/0005-local-first-ai-models.md) against [NFR-01](/requirements/non-functional.md) and [NFR-14](/requirements/non-functional.md). It covers the AI part of the recommender evaluation; the evaluation of the optimizer and of the recommendations as a whole is still to be planned.

# Setup

* **Hardware:** the author's laptop (Intel Core Ultra 7 258V, 32 GB, Intel Arc 140V). Each local model runs twice: on the Arc iGPU (Ollama, Vulkan) and on CPU only.
* **Settings:** temperature 0, fixed seed, the same prompts and tool schemas for every model, JSON schema enforced where the runtime supports it. Model versions and quantizations are recorded with the results.
* **Warm-up:** the first request after loading a model is discarded.

# Candidates

| Part | Candidates |
| --- | --- |
| Orchestrator LLM (local) | Qwen3.5 2B, Qwen3.5 4B, Granite 4.2 3B |
| Orchestrator LLM (cloud fallback) | Gemini 3.5 Flash-Lite (free tier) |
| Embeddings (local) | Qwen3-Embedding-0.6B, EmbeddingGemma 2 (270M), multilingual-e5-small |

The list is revised just before running the benchmark, in case newer models are available.

# Datasets

* **Shopping lists:** about 30 real lists written by the author and other users, about 300 lines in total, each labeled by hand with the expected item, quantity, unit and attributes. They include ambiguous lines ("algo para la cena") and soft preferences.
* **Product pairs:** 200-500 pairs from the scraped catalog with hard negatives (same family with a different size, variant or pack; same product with a different brand), plus same-product pairs across chains matched by EAN code when the scraping provides it. Needs real catalog data, so this part runs after the data-source viability study.

# Metrics

| Part | Metric |
| --- | --- |
| LLM | Prompt processing and generation speed (tokens/s) |
| LLM | Plan latency p50 and p95 (interpretation plus deterministic tools) |
| LLM | Explanation time to first token and total time |
| LLM | Valid tool-call JSON, first attempt and after validation plus one retry |
| LLM | Interpretation precision, recall and F1 per line |
| Embeddings | Recall@1, Recall@5 and MRR against the right canonical product |
| Embeddings | Hard-negative confusion rate (the main embedding metric) |
| Embeddings | Precision and coverage at the confidence threshold; embedding time per item |

The same lists are also run with the rule-based preprocessor alone, to measure how many lines it resolves without an LLM.

# Decision rule

Fixed before measuring:

* **Orchestrator:** the fastest local candidate that meets the acceptance rule of [0005](/decisions/0005-local-first-ai-models.md) (plan p95 ≤ 5 s, valid JSON ≥ 95 % on the first attempt, F1 ≥ 0.90) becomes primary. If none does, Gemini interprets the list and the best local candidate stays as fallback.
* **Explanation:** local if it meets the streaming targets of NFR-01.
* **Embeddings:** the candidate with the lowest hard-negative confusion that meets NFR-14; ties go to the smaller model. If none meets it, add the size veto and lexical re-ranking before trying larger models.

Results are recorded in this file and in a new prompt log entry, and decision 0005 is updated.
