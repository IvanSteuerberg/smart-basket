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
| Analytics (BI) | Analytical model separated from the transactional one, for price evolution and savings indicators. Design pending. |
| User interface | React web app, mobile-first and installable as a PWA: lists, recommendations, routes, savings history. A native Android app would be another client of the same API. See [0008](/decisions/0008-application-structure-and-stack.md). |

# Recommendation flow

1. The agent interprets the shopping list and preferences in natural language.
2. Each item is resolved to a canonical product and its equivalents across chains ([0004](/decisions/0004-canonical-product-model.md)).
3. PostGIS selects nearby candidate stores ([0002](/decisions/0002-routing-in-three-layers.md)).
4. The routing engine returns the travel-time matrix for those stores.
5. The optimizer picks the stores and per-store purchases minimizing cost + lambda * minutes.
6. The agent explains the result: savings, extra time and route.

# Deployment

Docker Compose services `db`, `api`, `worker`, `routing`, `web` and `metabase` on the author's laptop, with Ollama native on the host to use the Arc GPU. The backend is one Python package used by `api` and `worker`. See [0008](/decisions/0008-application-structure-and-stack.md).

# Open points

* Routing engine: Valhalla for the MVP, with a later comparison against OSRM ([0009](/decisions/0009-valhalla-routing-engine.md)).
* OLTP/OLAP separation for the BI layer: a `bi` star schema in the same PostgreSQL, see [0007](/decisions/0007-data-model.md) and the [data model](/architecture/data-model.md).
* Embedding and LLM models: local first, picked with the [AI model benchmark](/evaluation/ai-model-benchmark.md) ([0005](/decisions/0005-local-first-ai-models.md)).
