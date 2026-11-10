---
type: Architecture Decision
title: "0012 Schema implementation details"
description: Choices made when turning the logical data model into DDL - extra columns, partition management, validity types, the as-of rule of the price view and pending embedding dimensions.
tags: [decision, data, persistence, bi, implementation]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T01:10:00+01:00
---
# Context

The [data model](/architecture/data-model.md) of [0007](/decisions/0007-data-model.md) names key fields, not final DDL. The first migrations had to settle types, a few missing columns and some behaviour the logical model leaves open.

# Decision

1. **Schemas:** transactional tables in `public`, the star schema in `bi`. `public` is closed to `PUBLIC`, so roles other than the owner see nothing there unless granted.
2. **Columns added to the logical model:**
   * `canonical_product.default_quantity`: usual quantity per unit in the base unit (1 l for milk), used when a list line counts units of a product sold by weight or volume ("6 bricks de leche").
   * `promotion.priority`: the stable tie-break of the effective price (higher first, then lower id).
   * `recommendation_item.part`: a line can be covered by two formats ([0010](/decisions/0010-covering-quantities-with-packs.md)), so the key is (recommendation, line, part).
   * `reference_basket` and `reference_basket_item` (canonical, quantity, weight) for the price index of FR-33, with `bi.dim_reference_basket`.
   * `ingest_run.kind`, `raw_response.status_code`, `match_review.created_at`, `chain_category.parent_code`, `store.address`; `bi.fact_price_category_daily` keys also include `base_unit`, since mean prices per kilogram and per litre cannot be averaged together.
3. **Types:** promotion validity is a `daterange` (inclusive start, exclusive end, no open start), since chains publish dates; price intervals are `timestamptz`. Store locations are `geography(point, 4326)`. Recommendation ids use PostgreSQL 18's `uuidv7()`.
4. **Price history partitions:** yearly range partitions in UTC created by `create_price_history_partition(year)` (2025-2028 by the migration, this year and the next by the worker), plus a default partition so no insert ever fails. The primary key is (id, valid_from), as PostgreSQL requires the partition key in it.
5. **Constraints:** one check constraint per promotion kind with its required parameters and forbidden ones; exactly one target per `promotion_target` row; one chain-wide zone per chain; `price_history.valid_to > valid_from`; `chain_product` has a match method exactly when it has a canonical; one pending review per product.
6. **As-of view:** `bi.v_price_asof` gives, for each day of `bi.dim_date`, the price in force at the end of that day in `Europe/Madrid`, from the closed intervals of `price_history` plus the open interval of `price_current`.
7. **`bi.dim_date`** is filled for 2025-2030 by `bi.fill_dim_date`, with Spanish month and day names; León holidays are left for the BI refresh job.
8. **Embeddings** are `vector` columns without a fixed dimension until the [AI model benchmark](/evaluation/ai-model-benchmark.md) picks the model (the candidates have 384, 768 or 1,024 dimensions); the HNSW index is added in that later migration.

# Consequences

* The recommender can turn "6 bricks" into litres without asking the LLM, and the BI facts never mix units.
* A default partition with rows in a year blocks creating that year's partition; the worker creates partitions a year ahead to avoid it.
* Changing the embedding dimension later needs no data migration, only the index.

# Revisit when

* The embedding model is chosen (fix the dimension, add the index).
* Prices per real zone are needed in the facts ([0007](/decisions/0007-data-model.md), "Revisit when").
