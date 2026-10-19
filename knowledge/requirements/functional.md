---
type: Requirements
title: Functional requirements
description: Functional requirements of the MVP with MoSCoW priorities.
tags: [requirements, functional, mvp]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T19:30:00+02:00
---
Priorities follow MoSCoW: **M** must, **S** should, **C** could. Scope is defined in [MVP scope](/requirements/scope.md).

# Shopping list

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-01 | M | The user writes the list in free text ("leche, pan, algo para desayunar") and the agent turns it into items, generic or specific, with quantities. |
| FR-02 | M | The user searches the catalog and adds specific products or categories to the list. |
| FR-03 | M | The user reviews and corrects the agent's interpretation before the recommendation is computed. |
| FR-04 | S | Per item, the user states preferences: exact brand only, private label accepted, dietary restrictions (gluten-free, lactose-free). |
| FR-05 | S | Lists are saved in the browser and can be reused. |
| FR-06 | C | A list can be shared as a link. |

# Location and travel

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-07 | M | The user sets the starting point with the browser's geolocation or an address in León. |
| FR-08 | M | The user chooses walking or car and the maximum number of stores (1 to 3). |
| FR-09 | S | The user chooses how to trade money against time: prioritize savings, balanced, or prioritize time (sets the time value lambda). |
| FR-10 | S | The user excludes chains or specific stores. |
| FR-11 | C | The user forces a store to be included in the route. |
| FR-12 | S | The user states which loyalty cards they have, so only usable loyalty prices are applied. |
| FR-36 | M | The user chooses the shopping date (today by default). Only prices and promotions valid on that date, and stores open then, are considered. |

# Recommendation

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-13 | M | The system computes the best basket: what to buy in each store, total cost, travel time and visiting order ([0002](/decisions/0002-routing-in-three-layers.md)). |
| FR-14 | M | Equivalent products are proposed through the canonical product model, showing why they are equivalent (format, unit price) ([0004](/decisions/0004-canonical-product-model.md)). |
| FR-15 | M | Promotions valid on the shopping date are applied according to the quantity bought (NxM, second unit, volume discounts). |
| FR-16 | S | Loyalty-card prices and public coupons are applied when the user has the card, and are labeled as such. |
| FR-17 | M | Savings are shown against a reference: buying the whole list at the cheapest single nearby store. |
| FR-18 | M | The agent explains the result in natural language: savings, extra time, substitutions made ([0001](/decisions/0001-agent-as-orchestrator.md)). |
| FR-19 | S | Two or three alternatives along the cost-time trade-off are offered (e.g. one store vs. three stores). |
| FR-20 | M | The route is shown on a map. |
| FR-21 | M | Items with no match or no equivalent are reported, not silently dropped. |
| FR-22 | M | Each price shows the date it was last updated. |
| FR-38 | S | The user marks a recommended product as not found at a store. The system remembers it and penalizes or excludes that product at that store in later recommendations. |
| FR-39 | S | Each item in the recommendation shows a fallback in case it is not on the shelf: another equivalent in the same store or the next best store on the route. |
| FR-40 | C | When a chain gives no per-store catalog, the store format (e.g. Dia, Dia Market, Carrefour Express) is used to estimate which products a store is likely to carry. |

# Data ingestion and catalog

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-23 | M | Catalog, prices and promotions of each chain are ingested at least daily. |
| FR-24 | M | Price and promotion history is kept for every product. |
| FR-37 | M | Each promotion is stored with its validity period (start and end dates) when the chain publishes it. |
| FR-25 | M | Store locations in León are stored for every included chain. |
| FR-26 | S | Store opening hours are stored and closed stores are excluded from the route. |
| FR-27 | M | Each scraped product is assigned to a canonical product; low-confidence assignments go to a manual review queue. |
| FR-28 | M | An admin view shows ingestion status per chain: last run, products updated, errors. |

# BI: consumer

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-29 | M | Each recommendation shows a savings summary. |
| FR-30 | S | The browser keeps a local history of accepted recommendations and shows accumulated savings and spending per category. |

# BI: analyst

| ID | Pri. | Requirement |
| --- | --- | --- |
| FR-31 | M | Price evolution by canonical product, category and chain. |
| FR-32 | M | Private label vs. national brand comparison by category and chain. |
| FR-33 | S | Price index of a reference basket per chain over time (grocery inflation). |
| FR-34 | S | Frequency and depth of promotions per chain and category. |
| FR-35 | C | Anonymous usage analytics: most requested items, average recommended savings. |
