---
type: Architecture Decision
title: "0017 Single-chain recommendation end to end"
description: How a list becomes a basket before cross-chain matching exists - leaf as provisional comparable product, per-line candidates with name and unit guards, brand seed, template explanation and an anonymous record without the origin.
tags: [decision, recommender, api, privacy]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-14T02:00:00+01:00
sources:
  - /decisions/0013-basket-optimizer-rules.md
  - /decisions/0014-rule-based-preprocessor.md
  - /decisions/0015-seed-taxonomy.md
---
# Context

Iteration 11 joins the parts built so far into one flow for Mercadona León:
- the preprocessor and LLM fallback ([0014](/decisions/0014-rule-based-preprocessor.md), [0005](/decisions/0005-local-first-ai-models.md));
- the seed taxonomy ([0015](/decisions/0015-seed-taxonomy.md));
- the real catalog ([0016](/decisions/0016-ingestion-adapters.md));
- the optimizer ([0013](/decisions/0013-basket-optimizer-rules.md));
- Valhalla ([0009](/decisions/0009-valhalla-routing-engine.md)).

Canonical products and cross-chain matching ([0007](/decisions/0007-data-model.md)) come in iteration 12, so the recommendation needs a stand-in for "comparable product" that works with a single chain. The brand table was empty, so brand words in lists were not recognized.

# Decision

1. **API.** Five routes, all under `/api`:
   - `GET /categories`: tree with product counts per zone.
   - `GET /search`: leaves and groups; exact, then prefix, then fuzzy matches.
   - `POST /interpret`: preprocessor, then the LLM for unresolved lines. The LLM call runs after the database session is released and has a time limit; without an LLM the answer is marked `degraded`.
   - `GET /geocode`: see [0018](/decisions/0018-osm-stores-and-backend-geocoding.md).
   - `POST /recommendations`.

   Amounts and quantities travel as decimal strings. The lexicon is cached per process and refreshed when a content fingerprint of categories and brands changes.
2. **Provisional comparable product: one per request line.** Each line is resolved to a taxonomy leaf. Its candidate products are the available `chain_product`s of that leaf and its descendants, priced in the candidate store's zone. Each line gets its own synthetic canonical id, so two lines of the same leaf (one with a brand) are optimized separately. `recommendation_item.canonical_id` stays empty until real canonicals exist.
3. **Guards on the candidates of a line**, because mixed sections of the chain map to broad leaves:
   - **Unit dimension:** a product measured by mass is skipped for a leaf measured by volume and the other way round, so milk powder does not answer «leche». A leaf counted in units accepts weighed products, because bread is sold by the kilo.
   - **Name preference:** the products whose names share the most words of the line are kept, counting words of three letters or more without connectors («papel de horno» keeps «Papel vegetal» over a raffia bag in the same leaf). If no name shares a word, every product stays.
   - **Name fallback:** if a leaf has no products, products of its group are matched by name (token-set similarity, whole words for very short texts).
   - **Brands:** a requested brand and the private-label check compare whole folded words of the product name, using brand names and aliases.
4. **Candidate stores:** the nearest active stores of chains with prices in their zone, at most 10, within 3 km on foot or 20 km by car, ordered by distance. The optimizer receives the Valhalla matrix; the route shape comes from Valhalla's `/route` for the chosen order.
5. **Explanation by template**, in Spanish, with the optimizer's figures:
   - store and total;
   - minutes, round trip or not;
   - the sentences for missing lines and separate stops.

   An LLM-written explanation is left for later. When nothing can be bought, the answer is empty with «No hemos encontrado nada de tu lista en las tiendas cercanas.».
6. **Brand seed** (`seed/data/brands_es.json`, migration 0004):
   - **Content:** private labels of the ten chains plus about 100 manufacturer brands.
   - **Aliases**, plus `implies_category` for brands that name a product on their own (Cola Cao → `cacao_soluble`).
   - **`match_name`**: false for brands whose bare name is an ordinary word (Dia, Gallo, Eco+, Cien, Alteza).
   - **Validation:** `implies` must be a non-vague leaf; names and aliases are unique once folded; a matchable name equal to a taxonomy form must imply that form's category. The real seed is validated in the tests.

   When a brand without `implies` consumes the only words of a line, the preprocessor gives them back to the generic match («1 kg de gallo» is fish).
7. **Anonymous record (NFR-06).** Each answer is stored in `recommendation` and `recommendation_item`:
   - **Origin:** rounded to a cell of about 500 m, both in its column and inside the stored request.
   - **Result:** stored without the route.
   - **Logs:** errors are logged without the origin.
   - **Errors:** an optimizer input error answers 422 and a routing failure 503, both with a Spanish `detail`.

# Consequences

- **Real run (2026-11-14, Mercadona León, 4 stores, warm Ollama with Qwen3.5 0.8B on the host):**
  - Interpretation takes 1.3 s for a 6-line list, 3.7-4.8 s for the author's 10-line list and 6.3-6.7 s for the 17-line one, which is over the 5 s of NFR-01.
  - The recommendation takes 0.1-0.2 s, with a Valhalla matrix of about 30 ms.
  - All 27 real lines got a category, and 26 got a product; omega 3 capsules were not found in the store.
- **Guards help but product choice is still crude.**
  - The guards fixed the obvious errors: «Carne hamburguesa» now gets a beef burger, «Nata d cocinar» cooking cream and «papel de horno» baking paper.
  - «Pollo» still gets chicken livers and «Fruta» a single tangerine.
  - Choosing among the products of a broad leaf is what iteration 12's canonical products and matching fix.
- Variants such as «eco» are recognized but do not yet filter products.

# Revisit when

- Iteration 12 introduces canonical products: they replace the per-line ids, and the guards become part of matching.
- Interpretation of long lists stays over 5 s once the model runs on the GPU. Options are batching lines in one LLM call or a smaller prompt.
