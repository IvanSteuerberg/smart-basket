---
okf_version: "0.2"
---
# Smart Basket knowledge base

Engineering knowledge for Smart Basket, structured as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2 bundle. This is the source of truth for scope, architecture and decisions. The academic documents (concept document and prompt log, in Spanish) live in `docs/` and cite this bundle.

## Product

* [Vision](/product/vision.md) - Problem, value proposition and users of Smart Basket.
* [Glossary](/product/glossary.md) - Domain and technical terms used across the project.

## Requirements

* [MVP scope](/requirements/scope.md) - What the MVP covers and excludes, constraints and assumptions agreed with the author.
* [Functional requirements](/requirements/functional.md) - Functional requirements of the MVP with MoSCoW priorities.
* [Non-functional requirements](/requirements/non-functional.md) - Quality targets for the MVP; numeric values are proposals to confirm.

## Architecture

* [System overview](/architecture/system-overview.md) - Modules and how a recommendation flows through them.
* [Data model](/architecture/data-model.md) - Transactional entities and the BI star schema of the MVP.

## Data

* [Data-source viability study](/data/source-viability.md) - What each chain in León publishes, how to collect it automatically and what is still to check.

## Decisions

* [0001 Agent as orchestrator](/decisions/0001-agent-as-orchestrator.md) - The required recommender agent is an LLM orchestrator; numbers come from deterministic tools.
* [0002 Routing in three layers](/decisions/0002-routing-in-three-layers.md) - Spatial filter in PostGIS, travel-time matrix from an external routing engine, basket optimizer in our code.
* [0003 PostgreSQL as single database](/decisions/0003-postgresql-single-database.md) - pgvector, PostGIS and native partitioning in one PostgreSQL instance for the MVP.
* [0004 Canonical product model](/decisions/0004-canonical-product-model.md) - Equivalences resolved by mapping every scraped product to a canonical product.
* [0005 Local-first AI models](/decisions/0005-local-first-ai-models.md) - Local embeddings and a local-first LLM on the author's laptop, Gemini as fallback, a single agent and a pre-registered benchmark rule.
* [0006 Data collection with a real browser](/decisions/0006-data-collection-with-a-real-browser.md) - Every chain with an online catalog, collected periodically with a real browser or the site's own API; catalog, prices and promotions stored apart.
* [0007 Data model](/decisions/0007-data-model.md) - Brand- and size-agnostic canonical products, prices as change-only intervals, typed promotions and an aggregated star schema in the same PostgreSQL.

## Evaluation

* [AI model benchmark](/evaluation/ai-model-benchmark.md) - How the candidate LLMs and embedding models are measured on the laptop, and the rule that picks them.
* [Recommender evaluation plan](/evaluation/recommender-evaluation.md) - Optimizer correctness, data quality, savings against baselines, robustness, performance, usability and BI.
