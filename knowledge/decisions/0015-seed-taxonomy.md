---
type: Architecture Decision
title: "0015 Seed taxonomy"
description: A three-level taxonomy of interchangeable product types covering the whole Mercadona catalog, versioned as JSON with chains, zones and the Mercadona category mapping, and loaded idempotently after every migration.
tags: [decision, data, taxonomy, seed]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-09T21:00:00+01:00
---
# Context

Decision [0007](/decisions/0007-data-model.md) needs a seed taxonomy of leaf categories adapted from the chains' trees, used to compare products only within the same leaf, to build the list from the catalog ([FR-02](/requirements/functional.md)) and to give the rule-based preprocessor a real vocabulary ([0014](/decisions/0014-rule-based-preprocessor.md)). Mercadona's tree for León has 26 sections, 152 subcategories and 443 level 3 sections; the author chose to cover everything it sells, make-up included, and to version the category mapping (codes and names only) in the public repository.

# Decision

1. **Three levels:** 13 sections, 57 groups and 338 leaves after the author's review (2026-11-09), more than the 120-200 of 0007 because the whole catalog is covered. Keys are stable snake_case identifiers; names are Spanish.
2. **A leaf holds interchangeable products only.** "Naranja y mandarina" and "Limón y lima" are separate leaves, coffee capsules are split by system, ground and bean coffee are apart, biscuits have four leaves (breakfast, wholemeal, chocolate and filled, assorted), and fresh chorizo for cooking is apart from cured chorizo. Differences a shopper does not care about when comparing (size, nappy size, perfume for men or women) are variants of canonical products; where shoppers do not swap the products (plain, flavoured and skimmed yogurt; juice flavours), they stay separate leaves, following the chains.
3. **Each node carries what the preprocessor needs:** leaves have a `base_unit` (kg, l or ud, the unit prices are compared in), an optional `default_quantity` (what "1 X" means without a size) and `forms` (the phrases a shopper writes). Groups a shopper may write as a whole ("fruta", "yogures") are `vague`; no form belongs to two nodes.
4. **Chain mapping:** every Mercadona level 3 section maps to one leaf, or to its group when the section mixes products ("Plátano y uva", "Cítricos", "Otras salsas"). Placing those products in a leaf is left to product matching. Carrefour's tree was only a naming reference; its mapping comes with its adapter.
5. **Storage and loading:** `seed/data/taxonomy_es.json`, `chains_es.json` (10 chains, each with its chain-wide zone plus the known León zones) and `chain_categories/<chain>.json`, validated with pydantic and loaded by `smart-basket-seed` after every migration in Compose. Loading is idempotent: categories are upserted by key and never deleted (missing ones are reported as stale), the closure table is rebuilt, and the chain mapping follows the file. Migration 0003 adds `key`, `base_unit`, `default_quantity`, `forms` and `is_vague` to `category`.
6. **Vocabulary:** the preprocessor's lexicon is built from these categories (`smart-basket-lexicon export`), with general Spanish variants from `seed/data/variants_es.json`; brands come from the `brand` table.

# Consequences

* The first real Mercadona crawl (2026-11-09) placed all 4,307 products in a category; products of mixed sections sit in their group until matching.
* The author reviewed the draft on 2026-11-09 (turkey, fresh sausages, coffee, biscuits, supplements and hand cream split). Changing a leaf is a JSON edit and a reload: renamed or removed keys stay as stale categories without forms.
* With the real vocabulary, the rules resolve 64 of 78 lines of the example lists (82 %, F1 unchanged at 0.967) and more lines of the author's real lists, but brand detection needs a brand seed: the `brand` table is empty.

# Revisit when

* A second chain is mapped and its tree does not fit the leaves.
* Product matching shows leaves that mix products shoppers would not swap.
