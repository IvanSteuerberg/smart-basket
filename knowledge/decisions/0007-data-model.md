---
type: Architecture Decision
title: "0007 Data model"
description: Brand- and size-agnostic canonical products, prices as change-only intervals, typed promotions, and an aggregated star schema in the same PostgreSQL.
tags: [decision, data, persistence, bi]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-01T12:00:00+01:00
sources:
  - id: st7
    resource: ../../docs/memoria-prompts/entradas/noviembre.tex
    title: Señal de Tiempo 7
---
# Context

The data model has to serve the recommender (effective price of each product on the shopping date), the ingestion of 7 chains plus offers and flyers ([0006](/decisions/0006-data-collection-with-a-real-browser.md)) and the BI requirements ([FR-29](/requirements/functional.md) to FR-35), inside one PostgreSQL instance ([0003](/decisions/0003-postgresql-single-database.md)). Decision [0004](/decisions/0004-canonical-product-model.md) left open the granularity and creation of canonical products. The viability study found that assortment depends on the zone while sampled prices did not, and that catalogs range from about 4,500 (Mercadona) to about 26,000 products (Carrefour) per chain.

The design was drafted by Claude and checked against DeepSeek V4.1 Flash; both agreed on change-only price intervals and on keeping OLAP in the same PostgreSQL.[^st7]

# Decision

1. **Canonical product = product type + variants that change the equivalence** (fat level, lactose-free, gluten-free, flavour), with no brand and no size. Brand, private-label flag and normalized size (`base_quantity`, `base_unit`, `pack_count`) live in the chain product, which also stores the price per base unit. The optimizer covers the quantity the user asked for comparing per base unit, and keeps the exact format or brand when the user asks for it ([FR-04](/requirements/functional.md)). Marketing variants ("new look", "limited edition") never create a canonical.
2. **Creating canonicals:** a one-off seed taxonomy of leaf categories adapted from the chains' trees (338 leaves covering the whole Mercadona catalog, see [0015](/decisions/0015-seed-taxonomy.md)); rules extract size, pack, variant and brand; embeddings are compared only within the same leaf category and base unit; an EAN match wins when available. Clear matches are automatic, the grey zone goes to the review queue ([FR-27](/requirements/functional.md)), and an unmatched product becomes a new canonical after a few sightings. Precision over recall: a false merge corrupts prices and savings, a false split only duplicates. Canonicals are never deleted; merges are recorded and resolved with `merged_into`.
3. **Prices as change-only intervals:** `price_current` holds one row per chain product and zone with the price in force; `price_history` is append-only with closed intervals `[valid_from, valid_to)`, written only when a price changes and partitioned by year on `valid_from`. A daily snapshot would mean about 18-36 million rows a year; intervals, about 1-2 million. Each ingestion run records which products it saw, so a missing observation is not mistaken for an unchanged price, and data older than 48 h is flagged ([NFR-02](/requirements/non-functional.md)).
4. **Zones:** every chain has a chain-wide zone for single national prices; real zones are added only where prices differ. Assortment per zone has its own table.
5. **Promotions:** one table with typed columns for the common mechanics (promo price, percent, amount, buy N pay M, reference price), JSONB only for volume tiers, validity range, loyalty or coupon requirement, source (web or flyer) and whether the observed price already includes it. Targets are a chain product, a canonical, a category (with its descendants) or a brand, optionally restricted to zones. No stacking in the MVP: the best mechanic per line wins.
6. **Effective price** is a pure, versioned function in the application code: base price as of the date, candidate promotions, line cost by mechanic for the quantity, best line, stable tie-break. The engine version is stored with each recommendation ([NFR-03](/requirements/non-functional.md), [NFR-05](/requirements/non-functional.md)).
7. **Ingestion bookkeeping:** ingestion runs, raw responses (metadata in the database, compressed files on disk) and the review queue ([FR-28](/requirements/functional.md)).
8. **Recommendations** are stored anonymously: request (interpreted list, mode, stores, lambda, origin rounded to a grid cell), result, data date and engine version, plus one row per line ([NFR-06](/requirements/non-functional.md)).
9. **BI in a `bi` schema of the same PostgreSQL**, as a star schema of aggregated daily facts refreshed for a recent window after each ingestion: prices by category, chain, brand type and zone; a reference-basket price index per chain; promotions by chain, category and type; recommendations and their lines; anonymous usage. Product-level price evolution is served by an as-of view over the price history. Dimensions start as type 1 with `valid_from`/`valid_to` columns ready for type 2. Metabase OSS reads through a role limited to `bi`.
10. **Versions:** PostgreSQL 18 with pgvector 0.8 and PostGIS 3.6 or later.

The entities and facts are described in the [data model](/architecture/data-model.md).

# Consequences

* Equivalents across sizes and brands are found in one hop and compared fairly by unit price; the optimizer gains the job of choosing formats for a quantity.
* The price history stays about a hundred times smaller than daily snapshots, and charts are the steps of the intervals.
* The BI facts stay small (around a million rows a year) and need no separate engine.
* The seed taxonomy is the only manual work, done once.

# Revisit when

* More than 2 % of products show different prices between zones: prices per real zone and a zone key in the facts.
* The matching error exceeds 2 % on a labelled sample, or the review queue exceeds 10 % of products.
* Users need products compared at a fixed size, or a canonical mixes products that should not be substitutes.
* BI facts exceed about 100 million rows or reports take more than 5 s (p95): DuckDB on exported data or a read replica.
* Promotions need stacking (loyalty price plus coupon): an ordered rule model.

[^st7]: Prompt log, Señal de Tiempo 7 (Claude and DeepSeek V4.1 Flash with web search). DeepSeek contributed the split between current and historical prices, the aggregated facts and the flag for promotions already included in the price; it proposed including size in the canonical product, which was not adopted.
