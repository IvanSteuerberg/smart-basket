# LLM benchmark, first pass (2026-11-01)

First pass of the [AI model benchmark](../../knowledge/evaluation/ai-model-benchmark.md) for decision 0005, run on the author's laptop (Intel Core Ultra 7 258V, 32 GB, Intel Arc 140V) with Ollama 0.40.13.

* `lists.json`: 8 example shopping lists in Spanish (5 to 29 items) with the expected interpretation. They were written for this pass; the full benchmark needs about 30 real lists.
* `bench.py`: for each model, interprets every list with JSON schema output, asks for one tool call per item on four lists, and writes a ~120-word explanation twice. Temperature 0, seed 42, thinking off for Qwen and Gemma, 1,500 output tokens at most.
* `results.jsonl`: one line per call with validity, F1, token counts and timings.

Run with a local Ollama server (`ollama serve`); the integrated GPU needs a second server started with `OLLAMA_IGPU_ENABLE=1` and its own `OLLAMA_HOST`:

```bash
python bench.py 127.0.0.1:11434 cpu qwen3.5:2b gemma4:e4b
```
