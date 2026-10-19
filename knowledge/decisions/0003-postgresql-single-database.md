---
type: Architecture Decision
title: "0003 PostgreSQL as single database"
description: pgvector, PostGIS and native partitioning in one PostgreSQL instance for the MVP.
tags: [decision, persistence]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: st2
    resource: ../../docs/memoria-prompts/entradas/septiembre.tex
    title: Señal de Tiempo 2
  - id: st4
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 4
---
# Context

Expected volume: 30,000-100,000 products from 3-5 chains, about 300 MB of 768-dimension embeddings, and about 36 million price rows per year with daily snapshots. Alternatives evaluated: PostgreSQL alone, PostgreSQL + Qdrant, PostgreSQL + Neo4j. The decision was first taken on 2026-09-21[^st2] and revalidated with volume estimates and a second source on 2026-10-19.[^st4]

# Decision

Use a single PostgreSQL instance:

* **pgvector** for product embeddings (HNSW, iterative filtered scans since 0.8.0).
* **PostGIS** for store locations.
* **Native monthly partitioning** for price history; TimescaleDB only if analytical aggregations need it.

Development starts directly on pgvector, without a prior benchmark.

# Revisit when

* **Qdrant:** equivalence search performance is unacceptable on the real catalog.
* **Neo4j:** multi-hop relationship queries or graph algorithms become a core feature. It could also be added later as an offline analytical copy of the equivalence data.
* **OLAP engine (ClickHouse, DuckDB):** price history beyond about 100 million rows, or BI reports slower than a few seconds.

# Consequences

* One service, ACID transactions, no dual-write synchronization.
* BI tools connect over standard SQL.

[^st2]: Prompt log, Señal de Tiempo 2 (Gemini and DeepSeek recommend this option).
[^st4]: Prompt log, Señal de Tiempo 4 (Claude and Gemini confirm it).
