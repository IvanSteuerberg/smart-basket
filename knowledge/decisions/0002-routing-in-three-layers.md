---
type: Architecture Decision
title: "0002 Routing in three layers"
description: Spatial filter in PostGIS, travel-time matrix from an external routing engine, basket optimizer in our code.
tags: [decision, routing, geospatial]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: st1
    resource: ../../docs/memoria-prompts/entradas/septiembre.tex
    title: Señal de Tiempo 1
  - id: st2
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 2
---
# Context

Prompt log entry ST1 credited PostGIS and Neo4j with route calculation.[^st1] PostGIS only handles geometry (straight-line distance, radius, areas); road routing needs the OpenStreetMap road graph with directions, turn restrictions and speeds.[^st2]

# Decision

1. **Spatial filter:** PostGIS selects candidate stores near the user.
2. **Travel times:** an external routing engine over OpenStreetMap (OSRM or Valhalla, to be chosen) returns the travel-time matrix.
3. **Optimization:** our own optimizer solves the Traveling Purchaser Problem. MVP: exhaustive search with at most 3 stores among about 10 candidates; mixed-integer programming (OR-Tools, HiGHS) if the problem grows.

# Consequences

* Routing capability is no longer a criterion for choosing the database.
* Self-hosted engines use per-road-type speeds, not live traffic.

[^st1]: Prompt log, Señal de Tiempo 1 (claim corrected later).
[^st2]: Prompt log, Señal de Tiempo 2.
