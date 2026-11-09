---
type: Architecture Decision
title: "0014 Rule-based preprocessor v1"
description: Pipeline, output and resolution criteria of the rule-based list preprocessor, the lexicon interface and the LLM provider protocol.
tags: [decision, recommender, llm, preprocessor, implementation]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T02:30:00+01:00
---
# Context

Decision [0005](/decisions/0005-local-first-ai-models.md) (point 3) makes a rule-based preprocessor resolve most list lines so the LLM only interprets the rest; [FR-41](/requirements/functional.md) requires a basket without an LLM. The first benchmark pass found that a real household list uses abbreviations ("d" for "de"), joined words and typos ([AI model benchmark](/evaluation/ai-model-benchmark.md)). The catalog and the seed taxonomy do not exist yet, so the vocabulary has to come through an interface. Module: `smart_basket.preprocessor`; providers in `smart_basket.llm`.

# Decision

1. **Output:** one item per line with the shape of `ITEM_SCHEMA` in `experiments/llm-benchmark/bench.py` (`item`, `quantity`, `unit` in ud/kg/g/l/ml, `brand`, `attributes`, `ambiguous`), plus `resolved`, the reasons when not, the matched generic term and canonical id, the corrections applied and a purpose context ("para el finde"). `item` keeps the user's own words, corrected and without quantity or brand ("yogures sin lactosa"), as the LLM is asked to do; the canonical comes in its own field.
2. **Pipeline, per line:** split on new lines, semicolons, "+" and commas not between digits ("1,5 kg" stays), and on "y" only when both halves resolve ("kilo y medio" stays); fold case and accents for matching and restore the lexicon's accents for display; segment unknown joined words into lexicon words ("pandemolde" → pan de molde); correct typos of unknown words of 4+ letters with Damerau-Levenshtein similarity ≥ 0.8 against product words ("cafe molio" → café molido); expand abbreviations ("d", "semi", "s/", "aove", "paqs"); apply a small synonym list ("jugo" → zumo, "papel wc"); extract one quantity ("2 l", "1kg", "medio kilo", "un cuarto de kilo", "kilo y medio", "1/2 kg", "una docena", "x8", "pack de 3", "6x1,5 l", "6 bricks"); detect a brand (spelling variants such as "coca cola" and "cocacola"); match the longest generic term, ignoring connectors and plural -s/-es; collect variants from what is left.
3. **Resolved** means: a generic term was found, it is not a vague category ("fruta"), there is no ambiguity marker ("algo", "lo de siempre", "cosas") and no unknown word is left. Purpose phrases made only of filler and purpose words ("para el desayuno") become context and do not block resolution. Everything else is marked unresolved and goes to the LLM; in degraded mode it is kept as the rule-based best effort.
4. **Defaults:** a line without quantity is 1 ud, as the LLM prompt says; container words count units ("2 paquetes" is 2 ud), unless the container is part of the product ("bolsas de basura"). Turning units into kilograms or litres for the optimizer uses the canonical's `default_quantity` ([0013](/decisions/0013-basket-optimizer-rules.md), point 3).
5. **Lexicon interface** (`Lexicon` protocol): generic terms (key, display name, forms, base unit, default quantity, canonical id, vague flag), brands (aliases, private label flag, the generic term an eponymous brand implies, e.g. Cola Cao → cacao soluble), variants and units. `InMemoryLexicon` loads JSON. Tests use a **synthetic fixture lexicon** (`backend/tests/fixtures/lexicon_es.json`, about 145 product types, 30 variants and 47 brands); the real one will be built from canonical products, the seed taxonomy and the `brand` table. Language rules (abbreviations, units, numbers, connectors, ambiguity and purpose words, synonyms) live in code (`rules_es.py`). Personal vocabulary ("lo de siempre", aliases) is not here: it will live per user in the browser.
6. **LLM provider protocol** (NFR-12): `generate_json(system, user, schema)` and `generate_text(prompt)`, implemented for Ollama (`/api/chat` with a JSON schema, temperature 0, seed 42, thinking off for Qwen and Gemma, as in the benchmark) and Gemini (`generateContent` with a response JSON schema). `interpret_unresolved` sends only the unresolved lines, in one call, with the benchmark's interpretation prompt, and falls back to the rule items if the provider is missing, fails or answers invalid JSON (FR-41). Not called in tests; fakes test the merge.

# Consequences

* On the 8 example lists, with `bench.py`'s own scoring and no LLM: mean F1 0.967 (micro 0.974), quantity and unit right for 76 of 78 gold items, 72 of 78 lines (92 %) resolved without the LLM; the 6 unresolved are the ambiguous lines. The two misses are plural mismatches of the scoring ("yogures naturales" against "yogur natural", "cervezas" against "cerveza").
* **These figures are optimistic:** the fixture lexicon was written knowing the lists. They show that the rules work, not how much of a real list the real catalog lexicon will resolve; that needs the 30 real lists of the benchmark plan.
* With the LLM only seeing ambiguous lines, its output shrinks to a few dozen tokens, which is what 0005 needs to meet the 5 s target.
* The segmentation and typo correction depend on the lexicon's vocabulary: a richer lexicon corrects more but also risks wrong corrections, so both have thresholds and every correction is reported.

* **Numbers inside names and alternatives** (fixed on 2026-11-09 after a second real list). A number without unit or multiplier counts units only at the start of the line ("3 yogures") or at the end, alone or before filler ("huevos 12"); it stays in the name when followed by "%" ("leche 0%"), glued to a word ("carpetas A3"), followed by another word ("pan 7 cereales", so "leche 2 sin lactosa" is 1 unit), or inside a lexicon form that contains a number ("omega 3"). A number after a word the lexicon does not know still counts units ("bolis 3"). "3x yogures" is a count. A slash between words and a standalone "o" mark alternatives ("pasta/espaguetis", "pasta o espaguetis"; "1/2 kg" stays half a kilo): the line stays one item, the item text joins them with " o ", the match uses the first specific (non-vague) alternative found in the lexicon, and the others are reported in `alternatives`, outside the benchmark item shape. A line with alternatives is also tried split on "y" ("pan y leche o zumo").

# Revisit when

* The catalog lexicon exists (measure on real lists, tune thresholds and stop words).
* The 30 real benchmark lists are labelled (report rules-only and rules + LLM F1).
* Users report wrong corrections or splits.
