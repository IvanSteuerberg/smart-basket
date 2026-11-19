---
type: Evaluation
title: Recommender agent evaluation (I13)
description: Frozen 41-scenario k=3 benchmark of the recommender agent (ADR 0022), comparing DefaultPolicy ablation, Gemini 3.5 Flash-Lite, and Gemini Decision 1 with deterministic state verdicts.
tags: [evaluation, agents, llm, ablation, benchmark]
status: draft
generated:
  by: antigravity/gemini-4-neon
  at: 2026-11-19T15:05:00+01:00
sources:
  - id: adr0022
    resource: /decisions/0022-recommender-agent-and-system-agents.md
    title: 0022 Recommender agent and system agents
  - id: eval_cli
    resource: ../../backend/src/smart_basket/agent/eval_cli.py
    title: smart-basket-agent-eval
---
# Protocol

Evaluated on 2026-11-19 using `smart-basket-agent-eval` (`k = 3`, 123 runs per policy) over the 41 frozen scenarios in `backend/tests/agent/scenarios/*.json` (SHA-256 `e4f2b4e7ba30fcf95c48bfe8180f1b012c9609a4f3c6d834894f1d44f9c4ac0e`), approved by the author before any measurement. Every run is scored by deterministic state verdicts (no LLM judge). Raw outputs live in `experiments/agent-eval/`.

Pre-registered acceptance targets ([0022](/decisions/0022-recommender-agent-and-system-agents.md)):
1. **No-change + injection (8 scenarios):** 0 unrequested changes (100 %).
2. **Exceptions (33 scenarios):** task solved >= 85 %, `pass^3` >= 80 %.
3. **Ablation (`DefaultPolicy`):** >= 20 percentage-point drop on exceptions.

# Results (k = 3)

| Policy / Model | Exceptions solved (Wilson 95 %) | Exceptions `pass^3` | Ablation gain | No-change + injection | Unrequested changes | p50 / p95 (ms) | ADR 0022 targets |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `default` (`DefaultPolicy`, ablation) | 24.2 % `[16.9, 33.5]` | 24.2 % | — | 100.0 % | 0 / 24 | 0.0 / 0.1 | Baseline |
| `gemini_chat` (`gemini-3.5-flash-lite`) | **92.9 %** `[86.1, 96.5]` | **90.9 %** | **+68.7 pp** | **100.0 %** | **0 / 24** | 664 / 954 | **4 / 4 OK** |
| `gemini_decision` (`gemini-decision-1`) | 84.8 % `[76.5, 90.6]` | 84.8 % | +60.6 pp | 75.0 % | 6 / 24 | **263 / 516** | 2 / 4 (fails safety & 85 %) |

## Breakdown by scenario group (`solved`, k = 3)

| Group (n) | `default` | `gemini-3.5-flash-lite` | `gemini-decision-1` |
| --- | --- | --- | --- |
| `vague_line` (6) | 66.7 % | 100.0 % | 100.0 % |
| `missing_everywhere` (7) | 28.6 % | 100.0 % | 100.0 % |
| `near_tie` (4) | 25.0 % | 66.7 % | 25.0 % |
| `mode_and_what_if` (4) | 0.0 % | 100.0 % | 100.0 % |
| `shopper_requests` (9) | 0.0 % | 88.9 % | 77.8 % |
| `long_list` (3) | 33.3 % | 100.0 % | 100.0 % |
| `no_change` (4) | 100.0 % | 100.0 % | 100.0 % |
| `injection` (4) | 100.0 % | 100.0 % | 50.0 % |

# Findings

* **The perceive-act loop clearly adds value.** Replacing the model with the fixed `DefaultPolicy` table drops exception resolution by **68.7 pp** (from 92.9 % to 24.2 %), well above the 20 pp pre-registered threshold.
* **Gemini 3.5 Flash-Lite passes all four pre-registered targets**, including **0 / 24 unrequested changes** across `no_change` and `injection`, confirming that `[DATO_CATALOGO]` delimiting + enum-constrained `responseJsonSchema` resists prompt injection in catalog strings.
* **Gemini Decision 1 is 2.5× faster and provides calibrated probabilities** (p95 516 ms), matching Flash-Lite on `vague_line`, `missing_everywhere`, `mode_and_what_if`, and `long_list` (100 % each), but fails on `injection` (50 %, 6 unrequested changes) and `near_tie` (25 %) because the `/v1beta/decisions` endpoint has no system-prompt channel to reinforce anti-injection rules.
* **Local CPU note:** Ollama was not running during this session; in the prior spike (`experiments/decision-spike`), Gemma 4 E4B with 6 worked examples on CPU ran at p50 ~6,205 ms (over 7× the 800 ms p95 budget). Running `smart-basket-agent-eval --policy ollama_chat --model gemma4:e4b --fewshot --k 3` on CPU or Arc GPU remains reproducible with a single command.
