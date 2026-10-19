---
type: Glossary
title: Glossary
description: Domain and technical terms used across the project.
tags: [product, terminology]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
---
# Terms

* **Private label (marca blanca):** a product sold under the retailer's own brand (e.g. Hacendado, Dia).
* **Functional equivalence:** two products can replace each other for the user's purpose: same kind of product and compatible format, nutrition and allergens. Defined per canonical product, not by chains of similarity.
* **Canonical product:** a chain-independent product definition (e.g. "UHT whole milk, 1 L"). Every scraped product maps to one canonical product; products sharing it are equivalents. See [0004](/decisions/0004-canonical-product-model.md).
* **Unit price:** price normalized per kg, L or unit, needed to compare different pack sizes.
* **Travel-time matrix:** travel times between the user and each candidate store and between every pair of stores, computed by a routing engine over OpenStreetMap.
* **Traveling Purchaser Problem (TPP):** choosing which stores to visit and what to buy in each, minimizing purchase cost plus travel cost. NP-hard in general; small instances are solved exhaustively. See [0002](/decisions/0002-routing-in-three-layers.md).
* **Time value (lambda):** how much the user values one minute of travel, used to combine money and time into one cost: cost + lambda * minutes.
* **Orchestrator agent:** the LLM-based recommender agent. It interprets requests, calls tools and explains results; it never computes prices or routes itself. See [0001](/decisions/0001-agent-as-orchestrator.md).
* **OLTP / OLAP:** transactional schema serving the application vs. analytical (star) schema serving BI.
* **Señal de Tiempo:** an entry of the academic prompt log (`docs/memoria-prompts`), numbered across months.
