---
type: Architecture Decision
title: "0009 Valhalla as routing engine"
description: Valhalla, self-hosted in Docker Compose over the León OpenStreetMap extract, returns walking and driving travel-time matrices; a comparison with OSRM is left for later.
tags: [decision, routing, geospatial]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T12:00:00+01:00
---
# Context

Decision [0002](/decisions/0002-routing-in-three-layers.md) left the routing engine open between OSRM and Valhalla. The optimizer needs a travel-time matrix between the user's origin and about 10 candidate stores, walking or by car ([FR-08](/requirements/functional.md)), and everything runs locally without recurring cost ([NFR-10](/requirements/non-functional.md), [NFR-11](/requirements/non-functional.md)).

* **OSRM** is very fast, but each travel mode needs its own preprocessed graph, so walking and driving mean two datasets or two services.
* **Valhalla** is somewhat slower but serves walking and driving from one instance with costing chosen per request, and offers a time-distance matrix and isochrones.

For a city the size of León both are fast enough.

# Decision

1. **Valhalla** is the routing engine of the MVP, run as the `routing` service in Docker Compose ([0008](/decisions/0008-application-structure-and-stack.md)) over an OpenStreetMap extract that covers León.
2. The backend calls it through a small interface (origin and stores in, minutes matrix out), so the engine can be swapped.
3. **OSRM is compared later** on the same León cases: matrix latency, memory, setup effort and travel-time agreement.

# Consequences

* One routing service covers both travel modes.
* Isochrones are available for the map ("stores within 10 minutes").
* The optimizer receives the matrix as input and does not depend on the engine.

# Revisit when

* The OSRM comparison is done (this decision becomes `stable` or switches engine).
* Matrix latency threatens the 5 s target of [NFR-01](/requirements/non-functional.md).
