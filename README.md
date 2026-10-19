# Smart Basket

Business Intelligence and semantic recommendation engine for grocery shopping: given a shopping list, it proposes the combination of products and supermarkets that minimizes total cost and travel time, including equivalences between national brands and private labels.

> **Status:** concept phase. There is no code yet; the repository holds the design documentation and the generative AI usage log.

## Problem

Prices change constantly and the retail market is fragmented across chains. Comparing prices and finding cheaper equivalent alternatives by hand is not feasible day to day.

## Proposal

A recommender agent that, from a generic or specific shopping list:

- finds **functionally equivalent** products across brands and chains,
- computes the **lowest-cost** basket,
- takes **travel time** between stores into account.

## Planned architecture

| Module | Responsibility |
| --- | --- |
| Ingestion (scraping) | Periodic extraction and refresh of catalogs and prices from each chain. |
| Persistence | Price history, user data and vector representations of the catalog. |
| Recommender | Semantic product matching and shopping-route optimization. |
| Interface | Web and mobile app: shopping lists, savings history and routes. |

The persistence stack is still under evaluation (PostgreSQL with extensions, a polyglot setup with a vector database, or a graph database). See the prompt log.

## Repository layout

```
docs/
  idea-base/          Concept document (LaTeX, Spanish)
  memoria-prompts/    Generative AI prompt log (LaTeX, Spanish)
    entradas/         One entry file per month, included from memoria-prompts.tex
```

## Building the documentation

Requires a LaTeX distribution (TeX Live or MiKTeX). Build from each document's folder, since `\input` paths are relative:

```bash
cd docs/memoria-prompts && latexmk -pdf memoria-prompts.tex
```

## Context

Course project for *Sistemas de Información de Gestión y Business Intelligence* (Management Information Systems and Business Intelligence), Computer Engineering degree, Universidad de León, 2026-2027.

Author: Iván Rodríguez Steuerberg.
