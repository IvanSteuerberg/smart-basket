---
type: Architecture Decision
title: "0020 Rule-based canonical matching and canonical baskets"
description: Chain products are assigned to canonical products by rules, with a review queue decided by the author on a model's proposal; decisions live outside the repository and are re-applied by chain and SKU; the basket resolves list lines through canonicals.
tags: [decision, matching, recommender, data-quality]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-15T00:30:00+01:00
sources:
  - /decisions/0004-canonical-product-model.md
  - /decisions/0007-data-model.md
  - /decisions/0015-seed-taxonomy.md
  - /decisions/0017-single-chain-recommendation.md
  - /decisions/0019-shopper-preferences.md
---
# Context

Until iteration 12 every chain product inherited the leaf of its chain section, and the basket compared all products of a leaf with provisional guards ([0017](/decisions/0017-single-chain-recommendation.md)). Leaves that mixed non-interchangeable products made the basket pick a chicken carcass for «pollo» or a strawberry yoghurt for «yogur», and 239 products sat in groups without a leaf. The canonical model of [0004](/decisions/0004-canonical-product-model.md) and [0007](/decisions/0007-data-model.md) existed in the schema but nothing filled it.

# Decision

1. **Rules first, precision over recall.** `smart_basket.matching` assigns each product a leaf inside the subtree its chain section allows, from the taxonomy forms found in the name; anything doubtful goes to `match_review` with its candidates. A product that names a fresh ingredient of another section keeps its section leaf ("Tomate frito" is a sauce). Method `rule` with a confidence; `review`, `ean` and `embedding` assignments are never overwritten by a later run.
2. **Canonical = leaf + variants that change equivalence.** Variants marked `canonical` in `variants_es.json` (without lactose or gluten, wholemeal, fat level, zero, without salt or sugar, in olive or sunflower oil, natural, hot, sweet…) and the flavour ("sabor X") create separate canonicals; brand, size and marketing words do not.
3. **Every product is reviewed twice.** In iteration 12 a model labelled the whole catalog blind (DeepSeek V4.1 Flash), a second model arbitrated every disagreement with the rules and reviewed suspicious leaves with all their products (Gemini 3.8 Flash), the orchestrator checked the cases where neither was right, and the author approved the taxonomy changes. Measurement uses a third model that took no part in the fixes (Claude Haiku) and a full human-level review of its sample.
4. **Review by a model, decision by the author.** The run's report and queue are exported; a model (Gemini in iteration 12) proposed leaf splits, new leaves, vague terms and a decision per doubtful product; the orchestrator consolidated them and the author approved a summary before loading (2026-11-14). The taxonomy changes go into the seed ([0015](/decisions/0015-seed-taxonomy.md)).
5. **Decisions outside the repository, re-applied by chain and SKU.** Product decisions are collected chain data (NFR-07): they live in a JSON file under `DATA_DIR`, written by `smart-basket-match export-decisions` as `{chain, sku, category_key, variant_key}`. When `MATCH_DECISIONS_FILE` is set, the `migrate` service and the worker's matching job import it with missing products skipped and then run the rules, so a rebuilt database gets the same assignments.
6. **The basket resolves lines through canonicals.** A generic line takes the canonicals of its leaf and descendants whose canonical variant set equals the one asked (the set read from the text, or explicit `variants`), or that contain it when none has products; other variants filter by name. Without variants asked, canonicals whose variants are all `plain` (skimmed, semi-skimmed, organic, in olive or sunflower oil, natural, sweet) are accepted; a flavour never is. Content words of the line that are not the category name, a variant, a brand or a unit («basmati», «trozos») keep only the products whose name contains them, when some but not all do. A concrete line (`product_id`) buys exactly that product (`exact`) or any product of its canonical (`equivalent`). Products without a canonical are never candidates. The name fallback, name preference and processed-food filter of 0017 are removed; the typical pack, the mass/volume check and the brand and private-label filters stay.
7. **Vague terms are asked, never guessed.** A vague category has an `options` list in the seed (pollo, fruta, verdura, pescado fresco, quesos, yogures, fiambres) or offers its children with products; `/api/interpret` returns the options with photo and lowest price per unit, and `/api/recommendations` rejects a vague line with 422 `VAGUE_LINE`. Bread, wine and beer are no longer vague.
8. **Flexibility is priced, not imposed.** With exact lines, the basket is computed again with them as equivalent; `flex_savings` reports the difference in money, total and per line ([0019](/decisions/0019-shopper-preferences.md): preferences restrict candidates and never enter the objective).

# Consequences

* After the full review (batch 3): 4,307 of 4,307 Mercadona León products have a canonical (924 canonicals, 446 active leaves; 75 new leaves and the variants in tomato, in pickling sauce, marinated and wrap), with 1,363 decisions re-applied on start. The rules missed flavours not written as «sabor X» («refresco de naranja» and «de limón» shared a canonical); 324 products now carry their flavour.
* Measurement after batch 3, on a new stratified sample of 300 products labelled blind by Claude Haiku and reviewed in full: accuracy 92.0 % (95 % interval 88.4-94.6 %, NFR-04 met) and 7.7 % hard negatives (NFR-14 not met). Most remaining errors are leaves that both labellers accept although they mix products (pork cuts, nuts and seeds, soft and hard nougat, whipping and cooking cream, refined and virgin olive oil); double labelling cannot see them. Cosmetics and dyes with shades share canonicals and should be concrete-only.
* First evaluation (batch 2), on a stratified sample of 299 products, labelled blind by DeepSeek V4.1 Flash and adjudicated by Claude Opus with 30 agreements checked: accuracy between 89.6 % and 92.6 % ([NFR-04](/requirements/non-functional.md), target 90 %, at the limit) and about 5 % hard negatives taken as equivalents (NFR-14, target 3 %, not met). The errors are sibling leaves (juices, cold meats, chocolates, make-up) and formats a leaf still mixes (grated carrot with carrots).
* Author's three real lists after batch 3: chicken, bananas, omega 3, tuna, basmati rice, chorizo, drain cleaner, whole carrots, custard and petit suisse are right; «pasta» and «yogur grande» are asked; «pasta/espaguetis» buys dry tagliatelle (same leaf as spaghetti). Interpretation and basket stay under 0.4 s.
* Author's three real lists after batch 2, before and after: «pollo» now asks and buys breast instead of a carcass, «plátanos» and «omega 3» are found, «yogur grande» gives natural yoghurt, and interpretation plus basket stay under 0.4 s. New errors appear where a leaf mixes products the old name preference separated: «arroz basmati» gives round rice, «espaguetis» soup pasta, «carne hamburguesa» a breaded chicken burger, «atún» tuna in tomato (the exact-empty variant set picks the canonical without variants, not the usual one), «desinfectante» cleaning vinegar.
* The equivalence quality now depends on the taxonomy and the variant list, which are reviewable data, instead of code guards.

# Revisit when

* A homogeneity review of every leaf with all its products (pending) and concrete-only leaves for shades lower the hard negatives to the NFR-14 target.

* The pending fixes are decided: words of the line that name a product inside the leaf (basmati, espaguetis) should rank canonicals again; the empty-variant rule should prefer the usual canonical; leaves to split (pasta shapes, rice types, hamburgers, disinfectants, grated vegetables) and missing leaves (tofu and plant protein, other white fish, lemon juice, other soft drinks).
* A second chain is matched: cross-chain equivalence needs embeddings or EAN ([0005](/decisions/0005-local-first-ai-models.md)), and the review step will need sampling instead of full review.
