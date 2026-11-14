---
type: Architecture Overview
title: System overview
description: Modules and how a recommendation flows through them.
tags: [architecture]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: concept
    resource: ../../docs/idea-base/idea.tex
    title: Documento de Concepto v1.1
---
# Modules

| Module | Responsibility |
| --- | --- |
| Ingestion (scraping) | Periodic extraction of catalogs, prices, promotions and flyers from each chain with a real browser or the site's own API; store locations from OpenStreetMap. Runs in the `worker` service. See [0006](/decisions/0006-data-collection-with-a-real-browser.md). |
| Persistence | Single PostgreSQL instance: users, lists, catalog, embeddings, store locations, price history. See [0003](/decisions/0003-postgresql-single-database.md). |
| Recommender | Orchestrator agent plus three tools: equivalence search, travel-time matrix, basket optimizer. See [0001](/decisions/0001-agent-as-orchestrator.md). A rule-based preprocessor resolves most list lines before the LLM; models in [0005](/decisions/0005-local-first-ai-models.md). |
| Analytics (BI) | Star schema in the `bi` schema of the same PostgreSQL, refreshed by the worker, read by Metabase through a read-only role. See [0007](/decisions/0007-data-model.md) and the [data model](/architecture/data-model.md). |
| User interface | React web app, mobile-first and installable as a PWA: lists, recommendations, routes, savings history. A native Android app would be another client of the same API. See [0008](/decisions/0008-application-structure-and-stack.md). |

# Recommendation flow

1. The agent interprets the shopping list and preferences in natural language.
2. Each item is resolved to a canonical product and its equivalents across chains ([0004](/decisions/0004-canonical-product-model.md)).
3. PostGIS selects nearby candidate stores ([0002](/decisions/0002-routing-in-three-layers.md)).
4. The routing engine returns the travel-time matrix for those stores.
5. The optimizer picks the stores and per-store purchases minimizing cost + lambda * minutes.
6. The agent explains the result: savings, extra time and route.

# Deployment

Docker Compose services `db`, `migrate` (one-shot), `api`, `worker`, `routing`, `web` and `metabase` on the author's laptop, with Ollama native on the host to use the Arc GPU. The backend is one Python package (`backend/`, package `smart_basket`) used by `migrate`, `api` and `worker`; the web app lives in `web/`. See [0008](/decisions/0008-application-structure-and-stack.md) and, for the layout and tooling of the skeleton, [0011](/decisions/0011-skeleton-layout-and-tooling.md).

# Implementation status

| Part | Status |
| --- | --- |
| Skeleton: Compose services, database image, migrations of both schemas, `/api/health`, worker with placeholder jobs, PWA placeholder, CI | Done (2026-11-03) |
| Basket optimizer and effective price (`smart_basket.optimizer`), routing interface with a Valhalla client (`smart_basket.routing`) | Done, not yet wired to the API (2026-11-03, [0013](/decisions/0013-basket-optimizer-rules.md)) |
| Rule-based preprocessor v1 (`smart_basket.preprocessor`) with a lexicon interface, LLM provider protocol with Ollama and Gemini (`smart_basket.llm`) | Done with a synthetic lexicon, not yet wired to the API (2026-11-03, [0014](/decisions/0014-rule-based-preprocessor.md)) |
| Seed taxonomy, chains and zones loaded after every migration (`smart_basket.seed`, [0015](/decisions/0015-seed-taxonomy.md)) | Done, taxonomy reviewed by the author (2026-11-09) |
| Mercadona catalog and price ingestion (`smart_basket.ingestion`, [0016](/decisions/0016-ingestion-adapters.md)), daily in the worker | Done (2026-11-09) |
| Preprocessor lexicon built from the database (`smart_basket.vocabulary`), with the brand seed | Done (2026-11-09, brands 2026-11-14) |
| Stores of the ten chains from OpenStreetMap (`smart_basket.stores`), monthly in the worker; geocoding through the backend ([0018](/decisions/0018-osm-stores-and-backend-geocoding.md)) | Done (2026-11-14) |
| API for categories, search, interpretation and single-chain recommendations (`smart_basket.api`, `smart_basket.recommender`, [0017](/decisions/0017-single-chain-recommendation.md)); web flow list → review → origin → basket with a Leaflet map; Playwright end-to-end test in CI | Done for Mercadona (2026-11-14) |
| Other chains, canonical products and matching, BI refresh, LLM-written explanation | Pending |

# Open points

* Routing engine: Valhalla for the MVP, with a later comparison against OSRM ([0009](/decisions/0009-valhalla-routing-engine.md)).
* OLTP/OLAP separation for the BI layer: a `bi` star schema in the same PostgreSQL, see [0007](/decisions/0007-data-model.md) and the [data model](/architecture/data-model.md).
* Embedding and LLM models: local first, picked with the [AI model benchmark](/evaluation/ai-model-benchmark.md) ([0005](/decisions/0005-local-first-ai-models.md)).
