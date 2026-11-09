---
type: Market Analysis
title: Competitors
description: Grocery list and price-comparison apps in Spain, what each one does and the gap Smart Basket fills.
tags: [product, market, swot]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-09T18:30:00+01:00
sources:
  - id: quefalta
    resource: https://x.com/ingenierotelco/status/2117703955618595266
    title: QuéFalta announcement on X (2026-11-03)
  - id: quefalta-thread
    resource: https://x.com/N1TR08202/status/2118023992208486881
    title: QuéFalta thread on price comparison (2026-11-04)
  - id: apps-es
    resource: https://androidphoria.com/aplicaciones/apps-para-comparar-precios-de-supermercados-espana
    title: Apps to compare supermarket prices in Spain
---
Input for the gap and the SWOT analysis of the final report ([course evaluation](/requirements/course-evaluation.md)). Checked on 2026-11-09 from public posts and articles, without using the apps.

# Apps

| App | What it does | Price comparison | Multi-store basket and time |
| --- | --- | --- | --- |
| **QuéFalta** | Shared shopping list built from each supermarket's products and pictures; 20 supermarkets; offers and price changes updated weekly and automatically; iOS and Android; 40,000 registered users in November 2026, launched in 2026 | Per product only: a button inside each product finds similar products in other chains. Its author calls doing it for every product "a bit lazy"; a user replies that comparing prices is what matters most to him | No |
| **Soysuper** | Shopping list across online supermarkets | Shows which single supermarket is cheapest for the whole basket | No: one store, online |
| **Carritus** | Compares the basket price among supermarkets that deliver to the user's area | Whole basket, home delivery | No: delivery, not store visits |
| **Tiendeo** | Flyers and offers by location, with lists | Offers per product | No |
| **OkLista** | iOS app comparing prices at Mercadona, Carrefour, Lidl and others | Per product | Not described |

# Gap

The status quo is to shop at one usual store, or to compare by hand product by product (QuéFalta) or by single store (Soysuper, Carritus). None splits a basket across several **physical stores** weighing money against **travel time**, with a route, for a mid-size city with local chains (Gadis, Lupa, Alimerka in León). Smart Basket does that ([0001](/decisions/0001-agent-as-orchestrator.md), [0002](/decisions/0002-routing-in-three-layers.md), [0013](/decisions/0013-basket-optimizer-rules.md)), takes the list in natural language ([0014](/decisions/0014-rule-based-preprocessor.md)) and adds a BI layer on prices and promotions ([0007](/decisions/0007-data-model.md)).

# For the SWOT

* **Threat:** QuéFalta already has users, native apps, 20 chains updated weekly and product equivalences ("similar products"), the hard part of comparing a whole basket. Adding "where is my list cheapest" is a short step for it.
* **Validation:** there is demand for comparing and saving (its own users ask for it), weekly collection from many chains works at commercial scale, and building the list by picking products ([FR-02](/requirements/functional.md)) and sharing it (FR-06) are what users expect.
* **Opportunity:** the multi-store, time-aware basket and local chains are not covered by any of them.
