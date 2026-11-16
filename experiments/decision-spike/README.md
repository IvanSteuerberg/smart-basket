# Decision spike

A quick first check for [decision 0022](../../knowledge/decisions/0022-recommender-agent-and-system-agents.md): can a model choose the recommender agent's next action from a closed set, and how fast? It is **not** the evaluation 0022 asks for. That evaluation needs a frozen scenario set reviewed by the author, repetitions (pass^k) and the ablation.

* `scenarios.json`: 13 actions and 20 synthetic situations in Spanish. Each situation lists the options the code would allow, the expected action (`gold`) and, in some cases, other acceptable ones (`also_ok`). The situations and labels were written by Claude and have not been reviewed by the author.
* `spike.py`: runs every situation once against a backend and appends one line per situation to `results.jsonl`. The local models use Ollama chat with the output restricted to the enum of options. The cloud models use Gemini with a response schema, or the Gemini Decisions API. All runs use temperature 0.

## Results (2026-11-16)

The local models ran on CPU, as a production server without a GPU would.

| Model | Strict | Lenient | p50 per decision | p95 |
| --- | --- | --- | --- | --- |
| Gemini 3.5 Flash-Lite (cloud) | 18/20 | 19/20 | 727 ms | 1,097 ms |
| Gemini Decision 1 (cloud) | 17/20 | 19/20 | 237 ms | 314 ms |
| Gemini 3.5 Flash (cloud, thinks) | 17/20 | 19/20 | 1,848 ms | 4,585 ms |
| Gemma 4 E4B (CPU, 6 worked examples) | 17/20 | 20/20 | 6,205 ms | 42,721 ms |
| Gemma 4 E2B (CPU) | 14/20 | 15/20 | 3,821 ms | 4,867 ms |
| Gemma 4 E2B (CPU, 6 worked examples) | 13/20 | 14/20 | 3,450 ms | 24,218 ms |
| Gemma 4 E4B (CPU) | 13/20 | 16/20 | 7,330 ms | 8,817 ms |
| Qwen 3.5 4B (CPU) | 11/20 | 12/20 | 7,435 ms | 8,827 ms |
| Qwen 3.5 2B (CPU) | 8/20 | 10/20 | 4,515 ms | 5,025 ms |
| Qwen 3.5 0.8B (CPU) | 6/20 | 7/20 | 3,219 ms | 3,737 ms |

* **The local generative models fall back on the same few actions.** They lean on "find a substitute" or "do nothing". None of them asks when the shopper pinned a brand (s11). Qwen 2B and 4B and both Gemma models act on the injected product name (s12).
* **The cloud models agree with each other and miss mostly debatable cases:** asking versus comparing on a near tie, and whether "¿cuánto me ahorraría en coche?" changes the mode or compares.
* **Cost per decision is negligible in the cloud.** Flash-Lite uses about 219 input and 12 output tokens, about 0.0001 USD. Decision 1 has no output tokens, about 0.00002 USD.
* **Decision 1's advantage is speed and probabilities, not accuracy.** It is about 3 times faster than Flash-Lite and returns probabilities that can drive the trace bars and the ask-when-unsure rule.
* **Worked examples (`fewshot.json`) lift Gemma 4 E4B to the cloud's level** (17/20 strict, 20/20 lenient) but not E2B. The 6 examples are written apart from the 20 situations but cover the same kinds of situation, with their reasons as criteria in the system prompt: they teach the policy, not the answers. The cloud models ran without examples. E4B still takes about 6 s per decision on CPU. The high p95 values come from the first call, which processes the longer example prefix before the cache warms up.
* **With 20 cases, intervals are wide.** For 17/20, the Wilson 95 % interval is about 64-95 %.

## Not tested

* **Local decision models.** Ollama's `nimble` (9B, 5.6 GB in q4) and `tev1` are documented in English only. Kev-4B is English-only and needs CUDA or Apple Silicon.
* **The laptop's Arc GPU.**
* **The cloud models with the same worked examples.**
