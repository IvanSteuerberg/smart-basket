---
type: Data Model
title: Data model
description: Transactional entities and the BI star schema of the MVP, as decided in 0007.
tags: [architecture, data, persistence, bi]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-01T12:00:00+01:00
---
Logical model behind [0007](/decisions/0007-data-model.md). Column lists name the key fields, not the final DDL, which lives in the Alembic migrations of `backend/src/smart_basket/db/migrations/` (choices made there are recorded in [0012](/decisions/0012-schema-implementation-details.md)). Conventions: money as `numeric` (never float), timestamps as `timestamptz` in UTC, BI dates in `Europe/Madrid`, internal keys as `bigint` identities and anonymous public identifiers as `uuidv7()`.

# Transactional schema

## Reference

| Entity | Key fields | Notes |
| --- | --- | --- |
| `chain` | id, code, name | Mercadona, Carrefour, Dia, Alcampo, Gadis, Lupa, Alimerka, Aldi, Lidl, E.Leclerc |
| `zone` | id, chain_id, kind (`chain`, `postal_code`, `warehouse`, `salepoint`), code | Every chain has a chain-wide zone; real zones such as Mercadona warehouse `3683` or Carrefour salepoint `0000GV` are added as needed |
| `store` | id, chain_id, zone_id, osm_id, name, format, geom (PostGIS point), opening_hours, is_active | From OpenStreetMap; format feeds [FR-40](/requirements/functional.md) |
| `category` | id, key, parent_id, name, level, base_unit, default_quantity, forms, is_vague | Own seed taxonomy ([0015](/decisions/0015-seed-taxonomy.md)): 3 levels, 327 leaves; a closure table lists ancestors |
| `chain_category` | chain_id, code, name, category_id | Maps each chain's tree to the seed taxonomy |
| `brand` | id, name, is_private_label, owner_chain_id | Hacendado, Carrefour, Dia, Auchan… marked as private labels |

## Products

| Entity | Key fields | Notes |
| --- | --- | --- |
| `canonical_product` | id, category_id, name, variant_key, base_unit, default_quantity, embedding, merged_into, created_at | Type plus equivalence-changing variants, no brand or size ([0004](/decisions/0004-canonical-product-model.md)) |
| `chain_product` | id, chain_id, chain_sku, name, brand_id, ean, base_quantity, base_unit, pack_count, packaging, dietary_tags, chain_category, canonical_id, match_confidence, match_method, embedding, url, first_seen, last_seen, is_active | One row per product of a chain; `unique (chain_id, chain_sku)` |
| `chain_product_zone` | chain_product_id, zone_id, first_seen, last_seen, is_available | Assortment per zone |
| `product_match` | id, chain_product_id, canonical_id, method (`ean`, `rule`, `embedding`, `review`), score, decided_at | Audit of every assignment and merge |
| `match_review` | id, chain_product_id, candidates (ids and scores), status, resolved_at | Review queue ([FR-27](/requirements/functional.md)) |

## Prices and promotions

| Entity | Key fields | Notes |
| --- | --- | --- |
| `price_current` | chain_product_id, zone_id, price, price_per_unit, valid_from, last_seen_run | One row per product and zone, read by the recommender |
| `price_history` | id, chain_product_id, zone_id, price, price_per_unit, valid_from, valid_to | Closed intervals, written on change; partitioned by year on `valid_from`; index on (chain_product_id, zone_id, valid_from) including price |
| `promotion` | id, chain_id, kind (`promo_price`, `percent_off`, `nxm`, `second_unit`, `volume_tier`, `loyalty_price`, `coupon`), promo_price, percent, amount, buy_n, pay_m, reference_price, tiers (JSONB), requires_loyalty, coupon_code, applied_in_price, priority, valid (daterange), source (`web`, `flyer`), source_ref, raw_text, confidence | Check constraints per kind |
| `promotion_target` | promotion_id, chain_product_id \| canonical_id \| category_id \| brand_id | Exactly one target per row |
| `promotion_zone` | promotion_id, zone_id | No rows means the whole chain |
| `reference_basket` | id, code, name | Reference baskets of the price index ([FR-33](/requirements/functional.md)) |
| `reference_basket_item` | basket_id, canonical_id, quantity, weight | Items and weights of each reference basket |

## Ingestion

| Entity | Key fields | Notes |
| --- | --- | --- |
| `ingest_run` | id, chain_id, zone_id, started_at, finished_at, status, products_seen, prices_changed, errors | Admin view ([FR-28](/requirements/functional.md)) |
| `raw_response` | id, run_id, url, fetched_at, sha256, path | Metadata only; compressed files on disk |

## Recommendations

| Entity | Key fields | Notes |
| --- | --- | --- |
| `recommendation` | id (uuidv7), created_at, data_as_of, engine_version, origin_cell, mode, max_stores, lambda, request (JSONB: interpreted list, preferences), result (JSONB), total_cost, reference_cost, savings, minutes | Anonymous; the origin is rounded to a grid cell ([NFR-06](/requirements/non-functional.md)) |
| `recommendation_item` | recommendation_id, line, part, canonical_id, chain_product_id, store_id, quantity, unit_price, line_total, promotion_id | One row per line and format bought |
| `not_found_report` | store_id, chain_product_id, reported_at | Anonymous reports behind [FR-38](/requirements/functional.md) |

## Effective price

`effective_price(chain_product, zone, date, quantity, loyalty_cards, coupons)` runs in the application code:

1. Base price as of the date (`price_current`, or `price_history` for past dates). No price means not available.
2. Candidate promotions of the chain valid on that date, matching the zone and a target (product, canonical, category or ancestor, brand), with loyalty or coupon requirements met.
3. Line cost per mechanic for the quantity, e.g. buy N pay M: `pay = qty - floor(qty / N) * (N - M)`; second unit at X %: pairs at `base * (2 - X/100)` plus a single unit at base.
4. The lowest line cost wins, tie-break by priority (higher first) and id; promotions already included in the observed price are not applied again.

Implemented in `smart_basket.optimizer.pricing`, together with the pack-covering rule of [0010](/decisions/0010-covering-quantities-with-packs.md); the remaining rules (comparable cost between stores, coupons, volume tiers, mixing formats) are in [0013](/decisions/0013-basket-optimizer-rules.md).

# BI star schema (`bi`)

## Dimensions

| Dimension | Grain | Change handling |
| --- | --- | --- |
| `dim_date` | Day | Static; ISO week, month, holidays in León |
| `dim_chain` | Chain | Type 0 |
| `dim_zone` | Zone | Type 1 |
| `dim_store` | Store | Type 1, columns ready for type 2 |
| `dim_category` | Leaf category with levels 1-3 flattened | Type 1 |
| `dim_brand` | Brand, with brand type (private label or manufacturer) | Type 1, ready for type 2 |
| `dim_product` | Canonical product | Type 1, ready for type 2; merges resolved |
| `dim_promotion_kind` | Promotion mechanic | Type 0 |
| `dim_reference_basket` | Reference basket | Type 1 |

## Facts

| Fact | Grain | Measures | Serves |
| --- | --- | --- | --- |
| `fact_price_category_daily` | Day × category × chain × brand type × zone × base unit | Mean, median, min and max price per unit, products, products on promotion | [FR-31](/requirements/functional.md), FR-32 |
| `fact_price_index_daily` | Day × chain × reference basket | Index (base 100), coverage, items | FR-33 |
| `fact_promotion_daily` | Day × chain × category × promotion kind | Promotions, products, mean and max depth, share needing a loyalty card | FR-34 |
| `fact_recommendation` | Recommendation | Total cost, reference cost, savings, minutes, stores, lambda, data age | FR-29, FR-35 |
| `fact_recommendation_line` | Recommendation line | Quantity, unit price, line total, promotion applied | FR-35 |
| `fact_usage_daily` | Day × event | Events | FR-35 |

The reference basket is a set of canonical products with weights; a chain missing an item lowers its coverage instead of borrowing another chain's price. Product-level price evolution (FR-31) comes from the view `bi.v_price_asof` over `price_history`. After each ingestion run a job recomputes the last few days of the facts and the index; monthly roll-ups are materialized views refreshed at night. Metabase OSS connects with a read-only role limited to `bi`.

# Browser storage

Without accounts, personal data lives in the user's browser. It is stored as versioned JSON with the same entities and fields a future server schema would use, so adding accounts is a copy ([Path to user accounts](/requirements/scope.md#path-to-user-accounts)):

| Entity | Key fields |
| --- | --- |
| `list` | id (uuid), name, created_at, updated_at, items (text, interpreted item, quantity, unit, preferences) |
| `accepted_basket` | recommendation_id, accepted_at, total_cost, savings |
| `loyalty_card` | chain_id |
| `not_found` | store_id, chain_product_id, reported_at |

A `schema_version` field lets the app migrate stored data when the structure changes.
