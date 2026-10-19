---
type: Product Vision
title: Smart Basket vision
description: Problem, value proposition and users of Smart Basket.
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

* **Shopper:** writes or builds a shopping list, receives the recommended basket and route, and tracks savings locally in the browser (no account).
* **Analyst** (academic BI scope): explores price evolution, promotions and private-label vs. national-brand prices across chains and categories.
* **Administrator:** monitors data ingestion and reviews low-confidence product equivalences.

# Scope

The MVP scope (León, responsive web, no accounts, walking or car with up to 3 stores, all public promotions) is defined in [MVP scope](/requirements/scope.md).

[^concept]: Documento de Concepto, sections "Problema de Negocio" and "Propuesta de Valor".
