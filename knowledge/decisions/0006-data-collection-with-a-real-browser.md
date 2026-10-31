---
type: Architecture Decision
title: "0006 Data collection with a real browser"
description: Every chain with an online catalog, collected periodically with a real browser or the site's own public API, with catalog, prices and promotions stored apart.
tags: [decision, data, ingestion, scraping]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-31T22:00:00+01:00
sources:
  - id: st6
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 6
---
# Context

Good recommendations need prices and promotions from as many chains in León as possible, collected with no manual steps ([NFR-13](/requirements/non-functional.md)). The [data-source viability study](/data/source-viability.md) found that plain HTTP clients are blocked by Carrefour, Dia and Alimerka and that Mercadona keeps prices in an API its robots.txt disallows, but that a real browser reaches every chain checked; only Alimerka needs a login. A conservative reading (DeepSeek in Señal de Tiempo 6) would keep only 4-5 chains and a few hundred products each.[^st6] The author chose to go further, for personal, non-commercial academic use with the data kept private, under the research exception of art. 135 TRLPI.

# Decision

1. **Chains:** every chain with an online catalog: Mercadona, Carrefour, Dia, Alcampo, Eroski, Gadis, Lupa (if its online shop covers León) and Alimerka (with the author's account). Lidl, Aldi and E.Leclerc contribute their flyers.
2. **Method:** a real browser (Chromium driven by a script) sets León's postal code, keeps the session and walks the categories, reading the JSON or HTML the site itself loads. Where the site's own public API is enough once the zone is set, it is called directly (Mercadona). A login with the author's account is used where needed; credentials live in `.env` or the author's vault, never in the repository.
3. **Scope:** the full catalog of each chain. Rate and frequency are set after the first runs, with prices no older than 48 h as the target ([NFR-02](/requirements/non-functional.md)).
4. **Storage, collected periodically and not when a basket is requested:**
   * **Raw snapshots** of every response, with date and hash, for auditing and reprocessing.
   * **Chain products:** name, brand, format, category, EAN when known and the link to the canonical product ([0004](/decisions/0004-canonical-product-model.md)). They change slowly.
   * **Price observations** per product and zone (warehouse or postal code), kept as history ([0003](/decisions/0003-postgresql-single-database.md)).
   * **Promotions** apart, each with its type (price cut, NxM, second unit, volume, loyalty, coupon), parameters, validity period and source (web or flyer).
   * **Stores** from OpenStreetMap, linked to their chain and zone.

   At request time the recommender reads the latest price and the promotions valid on the shopping date to get the effective price.
5. **Enrichment:** Open Food Facts for EAN and attributes.
6. **Flyers:** text extracted from the PDF first; OCR or a local vision model only where needed, with a confidence threshold.

# Consequences

* Coverage is much wider than the reference TFG: the full catalog of 7-8 chains, unit prices and price cuts, with no hand-kept URLs.
* Collecting ahead of time keeps the 5 s target ([NFR-01](/requirements/non-functional.md)) and feeds the BI price history; separate promotions handle validity periods and flyer sources.
* One adapter per chain ([NFR-12](/requirements/non-functional.md)); site changes will break adapters, so each one has contract tests on saved snapshots and its own failure handling ([NFR-09](/requirements/non-functional.md)).
* Risks: the chains' terms of use, the data-mining reservation in Mercadona's robots.txt, and blocks if a site tightens its protection. Mitigations: personal use, no publication of the data, moderate rate.

# Revisit when

* A chain blocks the real browser or changes its site substantially.
* The app is published or used by more people.
* The first runs set the rate and frequency.

[^st6]: Prompt log, Señal de Tiempo 6 (Claude and DeepSeek V4.1 Flash with web search).
