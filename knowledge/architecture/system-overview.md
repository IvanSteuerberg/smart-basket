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
| Ingestion (scraping) | Periodic extraction of catalogs, prices and store locations from each chain. |
| Persistence | Single PostgreSQL instance: users, lists, catalog, embeddings, store locations, price history. See [0003](/decisions/0003-postgresql-single-database.md). |
| Recommender | Orchestrator agent plus three tools: equivalence search, travel-time matrix, basket optimizer. See [0001](/decisions/0001-agent-as-orchestrator.md). |
| Analytics (BI) | Analytical model separated from the transactional one, for price evolution and savings indicators. Design pending. |
| User interface | Web (and later mobile) app: lists, recommendations, routes, savings history. |

# Recommendation flow

1. The agent interprets the shopping list and preferences in natural language.
2. Each item is resolved to a canonical product and its equivalents across chains ([0004](/decisions/0004-canonical-product-model.md)).
3. PostGIS selects nearby candidate stores ([0002](/decisions/0002-routing-in-three-layers.md)).
4. The routing engine returns the travel-time matrix for those stores.
5. The optimizer picks the stores and per-store purchases minimizing cost + lambda * minutes.
6. The agent explains the result: savings, extra time and route.

# Open points

* Choice of routing engine (OSRM or Valhalla).
* OLTP/OLAP separation for the BI layer.
* Embedding model for products.
