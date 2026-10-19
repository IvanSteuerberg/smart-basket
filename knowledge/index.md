---
okf_version: "0.2"
---
# Smart Basket knowledge base

Engineering knowledge for Smart Basket, structured as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2 bundle. This is the source of truth for scope, architecture and decisions. The academic documents (concept document and prompt log, in Spanish) live in `docs/` and cite this bundle.

## Product

* [Vision](/product/vision.md) - Problem, value proposition and open scope questions for the MVP.
* [Glossary](/product/glossary.md) - Domain and technical terms used across the project.

## Architecture

* [System overview](/architecture/system-overview.md) - Modules and how a recommendation flows through them.

## Decisions

* [0001 Agent as orchestrator](/decisions/0001-agent-as-orchestrator.md) - The required recommender agent is an LLM orchestrator; numbers come from deterministic tools.
* [0002 Routing in three layers](/decisions/0002-routing-in-three-layers.md) - Spatial filter in PostGIS, travel-time matrix from an external routing engine, basket optimizer in our code.
* [0003 PostgreSQL as single database](/decisions/0003-postgresql-single-database.md) - pgvector, PostGIS and native partitioning in one PostgreSQL instance for the MVP.
* [0004 Canonical product model](/decisions/0004-canonical-product-model.md) - Equivalences resolved by mapping every scraped product to a canonical product.
