---
type: Architecture Decision
title: "0016 Ingestion adapters"
description: One adapter per chain that only crawls and parses, shared persistence with change-only prices, run bookkeeping that survives failures, and safeguards before marking products unavailable.
tags: [decision, ingestion, data]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-09T21:00:00+01:00
---
# Context

Decision [0006](/decisions/0006-data-collection-with-a-real-browser.md) collects every chain's catalog periodically and [0007](/decisions/0007-data-model.md) stores prices as change-only intervals with ingestion bookkeeping. Mercadona is the first chain: its site's JSON API works without login. The conventions set here apply to the next adapters ([NFR-09](/requirements/non-functional.md), [NFR-12](/requirements/non-functional.md)).

# Decision

1. **Adapters crawl and parse; one shared store persists.** An adapter (`smart_basket.ingestion.<chain>`) yields category, product and raw-payload observations and per-request errors; `ingestion/store.py` writes them for any chain. The HTTP client sends a desktop browser `User-Agent`, waits between requests (1.5 s by default) and retries timeouts, 5xx and 429 with backoff, honouring `Retry-After`.
2. **Run bookkeeping survives failures.** `ingest_run` is committed before crawling and closed in its own transaction as `succeeded`, `partial` or `failed`, also on interrupts; runs left `running` for more than 6 hours are closed as `failed` by the next run. Errors carry their URL.
3. **Prices change only on change.** One observation time per run, taken after the crawl; a different price or price per unit closes the interval in `price_history` and updates `price_current`; an equal one only refreshes `last_seen`. An advisory lock per zone keeps two runs from closing the same interval.
4. **Unavailability needs a trustworthy run.** Products not seen are marked unavailable only after a complete run (not limited, no hard errors, parser drops within 1 %) that saw at least half of the products available before; otherwise the run ends `partial` and marks nothing.
5. **Raw responses** are gzipped under `DATA_DIR` (a Compose volume, never the repository) with their hash and URL in `raw_response`.
6. **Size normalization** stores the size per unit (`base_quantity` in kg, l or ud) and the pack count; unknown formats leave both empty.
7. Category mappings (`chain_category.category_id`) are owned by the seed ([0015](/decisions/0015-seed-taxonomy.md)): ingestion upserts names and parents only.

# Consequences

* First real runs (2026-11-09, Mercadona León): 4,307 products in about 4 minutes, 153 raw responses (784 KB), 36 products without a known size; a second unchanged run wrote no history.
* Mercadona has no brand field, so brands are left to matching.
* The worker runs the crawl daily at 05:07; `smart-basket-ingest` runs it by hand.

# Revisit when

* A chain needs a real browser session instead of plain HTTP (0006).
* Prices differ by zone in a chain already collected chain-wide.
