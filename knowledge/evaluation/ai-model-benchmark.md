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
Measures the candidates of [0005](/decisions/0005-local-first-ai-models.md) against [NFR-01](/requirements/non-functional.md) and [NFR-14](/requirements/non-functional.md). It covers the AI part of the recommender evaluation; the rest is in the [recommender evaluation plan](/evaluation/recommender-evaluation.md).

# Setup

* **Hardware:** the author's laptop (Intel Core Ultra 7 258V, 32 GB, Intel Arc 140V). Each local model runs twice: on the Arc iGPU (Ollama, Vulkan) and on CPU only.
* **Settings:** temperature 0, fixed seed, the same prompts and tool schemas for every model, JSON schema enforced where the runtime supports it. Model versions and quantizations are recorded with the results.
* **Warm-up:** the first request after loading a model is discarded.

# Candidates

| Part | Candidates |
| --- | --- |
| Orchestrator LLM (local) | Qwen3.5 0.8B, Qwen3.5 2B, Qwen3.5 4B, Gemma 4 E2B, Gemma 4 E4B, Granite 4.2 3B |
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

Results are recorded in this file, and decision 0005 is updated; a prompt log entry only if the results change the decision.

# First pass (2026-11-01)

Preliminary: 8 example lists written for the pass (5 to 29 items), not the 30 real lists, and the LLM interpreted every line (no rule-based preprocessor yet). Script, lists and raw results are in `experiments/llm-benchmark/`. Ollama 0.40.13; the Arc runs through Vulkan once the integrated GPU is enabled (`OLLAMA_IGPU_ENABLE=1`), which Ollama does not do by default.

| Model | Device | Generation (tokens/s) | Valid JSON | F1 | 5 items | 12 items | 29 items | Valid tool calls | Explanation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen3.5 0.8B | Arc | 81 | 8/8 | 0.92 | 3 s | 7 s | 15 s | 19/22 | 1.5 s |
| Qwen3.5 0.8B | CPU | 39 | 8/8 | 0.88 | 5 s | 13 s | 30 s | 19/22 | 5.5 s |
| Gemma 4 E2B | Arc | 55 | 8/8 | 0.79 | 4 s | 10 s | 22 s | 14/22 | 6 s |
| Gemma 4 E2B | CPU | 28 | 8/8 | 0.88 | 9 s | 20 s | 45 s | 9/22 | 12 s |
| Gemma 4 E4B | Arc | 35 | 8/8 | 0.86 | 6 s | 15 s | 34 s | 17/22 | 7.5 s |
| Gemma 4 E4B | CPU | 16 | 8/8 | 0.90 | 17 s | 36 s | 76 s | 17/22 | 19 s |
| Qwen3.5 2B | Arc | 24 | 8/8 | 0.92 | 9 s | 21 s | 50 s | 20/22 | 4 s |
| Qwen3.5 2B | CPU | 15 | 8/8 | 0.92 | 16 s | 35 s | 80 s | 17/22 | 9 s |
| Qwen3.5 4B | Arc | 17 | 8/8 | 0.94 | 13 s | 32 s | 70 s | 20/22 | 12 s |
| Qwen3.5 4B | CPU | 10 | 8/8 | 0.94 | 24 s | 52 s | 117 s | 20/22 | 19 s |
| Granite 4.2 3B | Arc | 20 | 2/8 | 0.25 | 69 s | 74 s | 80 s | 0/22 | 58 s |

Findings:

* **No candidate meets the 5 s rule when the LLM interprets the whole list.** Output length decides: a 29-item list is 1,000-1,300 tokens. The rule-based preprocessor of 0005 is therefore required, and the LLM must only handle the lines it cannot resolve.
* **The Arc helps:** generation is 1.5-2.2 times faster than on CPU for every model, and prompt processing 5-8 times faster.
* **Accuracy:** Qwen3.5 is the most accurate (F1 0.92-0.94, 20/22 tool calls). Gemma 4 E4B is about twice as fast as Qwen3.5 4B with slightly lower accuracy and the same results on CPU and Arc. Gemma 4 E2B is the fastest but unstable: its tool calls drop from 14/22 on the Arc to 9/22 on CPU.
* **Granite 4.2 3B is discarded:** with schema-constrained output it keeps generating until the token limit, and it produced no valid tool call.
* **Ambiguous lines:** no model called the tool for "lo de siempre para el desayuno..."; they probably ask for clarification instead, which may be the right behaviour and needs its own scoring.
* **Explanation:** a ~120-word explanation takes 4-6 s on the Arc with the small models, so a local explanation in streaming fits NFR-01.
* **Reproducibility:** with the same seed and temperature 0, CPU and Arc gave different interpretations in some cases; storing the interpreted list with each recommendation (0005) covers this.

* **Qwen3.5 0.8B** (measured on 2026-11-02) is the fastest model tried, three times faster than Qwen3.5 2B on the Arc, with the same accuracy on the example lists and 19/19 valid tool calls outside the ambiguous list.
* **A real household list** (abbreviations such as "d" for "de", joined words, a misspelt product, no quantities) was much harder than the example lists: F1 0.7 for Qwen3.5 0.8B and 2B and 0.8 for Gemma 4 E4B. The 0.8B model mostly copied the lines without normalizing them and invented litres for coffee; the 2B model invented kilograms and marked most lines as ambiguous; Gemma 4 E4B normalized best but turned a brand into a generic product. The rule-based preprocessor must normalize abbreviations and joined words before the LLM, and the example lists overestimate accuracy, so the next pass needs real lists.

Provisional ranking for the next pass: Qwen3.5 0.8B, Qwen3.5 2B and Gemma 4 E4B on the Arc. The next pass adds the rule-based preprocessor, the 30 real lists and scoring for clarification questions.
