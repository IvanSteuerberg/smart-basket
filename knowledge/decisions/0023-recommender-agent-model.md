---
type: Architecture Decision
title: "0023 Recommender agent model selection"
description: Select Gemini 3.5 Flash-Lite (`gemini_chat`) for the recommender agent's perceive-act loop with DefaultPolicy as degraded fallback, based on the frozen 41-scenario k=3 evaluation.
tags: [decision, agents, llm, evaluation]
status: draft
generated:
  by: antigravity/gemini-4-neon
  at: 2026-11-19T15:05:00+01:00
sources:
  - id: adr0022
    resource: /decisions/0022-recommender-agent-and-system-agents.md
    title: 0022 Recommender agent and system agents
  - id: eval
    resource: /evaluation/agent-evaluation.md
    title: Recommender agent evaluation (I13)
  - id: st10
    resource: ../../docs/memoria-prompts/entradas/noviembre.tex
    title: Señal de Tiempo 10
---
# Context

[0022](/decisions/0022-recommender-agent-and-system-agents.md) fixed a pre-registered selection rule before measuring: on the frozen 41-scenario set (`backend/tests/agent/scenarios/*.json`, SHA-256 `e4f2b4e7ba30fcf9...`), choose the cheapest local option whose lower 95 % Wilson bound is within 3 points of the best option with p95 <= 800 ms; if no local option meets that rule, use cloud as fallback with a spending cap.

The `k = 3` evaluation ([agent-evaluation.md](/evaluation/agent-evaluation.md)) measured:
* `default` (`DefaultPolicy` ablation): 24.2 % exceptions solved, 100 % zero-change on safety split.
* `gemini_chat` (`gemini-3.5-flash-lite`): **92.9 %** exceptions solved (`[86.1, 96.5]`), **90.9 %** `pass^3`, **+68.7 pp** over ablation, **100 %** zero-change on `no_change` + `injection` (0 / 24), p50 664 ms / p95 954 ms. **Passes all 4 pre-registered targets.**
* `gemini_decision` (`gemini-decision-1`): **84.8 %** exceptions solved (`[76.5, 90.6]`), **84.8 %** `pass^3`, p50 263 ms / p95 516 ms, but **75.0 %** on safety split (6 / 24 unrequested changes on `injection`) and 25.0 % on `near_tie`. **Fails the 100 % safety target.**
* Local CPU (`gemma4:e4b`, from `experiments/decision-spike`): ~6.2 s p50 on CPU, failing the 800 ms p95 latency rule.

# Decision

1. **Use `gemini_chat` (`gemini-3.5-flash-lite`) as the recommender agent's model** when cloud API access is configured (paid tier only for real shopper data, per 0022, with a spending cap).
2. **Keep `DefaultPolicy` (`policy = "default"`) as the default when no API key is configured** (preserving [FR-41](/requirements/functional.md) degraded mode and powering the web «Sin agente» ablation toggle).
3. **Do not adopt the decision-model split (`gemini-decision-1`) for the recommender loop today:** despite its 2.5× lower latency and calibrated probabilities, failing prompt-injection safety (50 % on `injection`) is a blocker for an online shopper-facing agent. Keep `GeminiDecisionPolicy` in `agent/policies.py` so it can be re-evaluated if Google adds a system-instruction channel or for non-adversarial internal tasks (catalog agent).
4. **Keep `OllamaChatPolicy` (`gemma4:e4b` with few-shot)** for offline/local fallback and batch agents (catalog agent, watcher) where 6 s latency is acceptable.

# Consequences

* All four pre-registered ADR 0022 acceptance targets are met by the selected model (`gemini-3.5-flash-lite`), and the +68.7 pp ablation gap provides quantitative evidence for the defence that the agent loop adds value over fixed rules.
* DeepSeek V4.1 Flash (Señal de Tiempo 10, without project context and with primary-source verification) confirmed that Google's official Decisions API documentation explicitly states there is no dedicated prompt-injection defense or `system_prompt` channel, and that exact probability ties break alphabetically by key — reinforcing both the rejection of `gemini-decision-1` for online use and the architectural rule to pass only sanitized canonical labels rather than raw catalog strings.
* p95 latency on `gemini-3.5-flash-lite` is 954 ms (slightly above the 800 ms target for local models, well within the interactive shopper budget because the initial basket still comes from the fast deterministic pipeline). At MVP scale cost is negligible (~$0.0005/decision); at 1,000 concurrent users the bottleneck is RPM rate limits, sized by the exception ratio rather than total baskets.
* Model catalogs rotate roughly every 12 months, so the explicit model ID is pinned and the 41-scenario harness remains model-agnostic for periodic re-baselining.

# Revisit when

* Any local option (discrete GPU, Intel Arc measured with OpenVINO/INT4, or a new small Spanish model) meets the pre-registered rule on the frozen 41×3 harness (lower 95 % Wilson bound within 3 pp of the best option and p95 <= 800 ms).
* Gemini Decisions API adds a system-prompt channel or reaches 100 % on the frozen injection split.
* A cheaper equivalent cloud model (e.g. `gemini-3.1-flash-lite`) or a mandatory model deprecation triggers a quarterly re-baseline.
