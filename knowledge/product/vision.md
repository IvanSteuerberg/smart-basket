---
type: Product Vision
title: Smart Basket vision
description: Problem, value proposition and open scope questions for the MVP.
tags: [product, scope]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T18:45:00+02:00
sources:
  - id: concept
    resource: ../../docs/idea-base/idea.tex
    title: Documento de Concepto v1.1
---
# Problem

Grocery prices change constantly and the market is split across chains. Comparing prices and finding cheaper equivalent products (national brand vs. private label) by hand is not feasible day to day, and shoppers cannot weigh savings against the extra travel time of visiting another store.[^concept]

# Value proposition

Given a generic or specific shopping list, Smart Basket recommends which products to buy and in which stores so that total cost and travel time are minimized, while guaranteeing that recommended items are functionally equivalent to what the user asked for.

The system is also a Business Intelligence tool: it keeps a price history that supports analysis of market evolution and of the savings each user achieves.

# Users

* **Shopper:** manages shopping lists, receives recommendations and routes, tracks savings.
* **Analyst** (academic BI scope): explores price evolution across chains and categories.

# Open scope questions

To be answered when defining requirements:

* Which chains are included in the MVP, and is their data obtainable?
* Geographic scope (one city, e.g. León, or wider).
* Platform for the MVP: web first, or web and mobile from the start.
* Travel mode (walking, car) and maximum number of stores per trip.
* Whether user accounts and purchase history are part of the MVP.

[^concept]: Documento de Concepto, sections "Problema de Negocio" and "Propuesta de Valor".
