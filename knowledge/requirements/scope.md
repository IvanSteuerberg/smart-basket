---
type: Scope
title: MVP scope
description: What the MVP covers and excludes, constraints and assumptions agreed with the author.
tags: [requirements, scope, mvp]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T19:30:00+02:00
---
# In scope

| Area | MVP scope |
| --- | --- |
| Geography | City of León only. |
| Chains | **Required:** Mercadona, Carrefour, Dia, Lidl. **If data allows:** Alcampo, E.Leclerc, Lupa, Aldi. Final list depends on the data-source viability study. |
| Platform | Responsive web app, mobile first. |
| Users | No accounts. Lists and personal history live in the user's browser. |
| Travel | The user chooses walking or car for each request; at most 3 stores per trip. |
| Promotions | Discounted prices, multi-unit offers (NxM, second unit at X %), volume discounts, loyalty-card prices and public coupons. |
| List input | Free text interpreted by the agent, plus catalog search to pick specific products or categories. |
| BI | Consumer view (savings per recommendation, local history) and analyst panel (market price evolution). |

# Out of scope

* Native mobile app.
* User accounts and server-side personal data.
* Personalized coupons tied to the user's account at a chain (e.g. app-only offers): they cannot be obtained without the user's chain credentials.
* Online ordering or checkout at the chains.
* Real-time stock and live traffic.
* Cities other than León.

# Constraints

* Academic project for the course *Sistemas de Información de Gestión y Business Intelligence*, 2026-2027.
* Data comes from public sources of each chain; scraping must respect their terms and the legal constraints still to be studied.
* Architecture decisions [0001](/decisions/0001-agent-as-orchestrator.md) to [0004](/decisions/0004-canonical-product-model.md) apply.

# Assumptions and risks

* **Data availability is the main risk.** Without good price and promotion data there is no good recommender. Lidl, for example, publishes few grocery prices online. The data-source viability study must confirm which chains, fields and promotions can be obtained.
* Online prices are assumed to match prices in León stores. Chains that price by postal code or warehouse need the León zone selected.
* Without accounts, consumer savings history is lost if the user clears the browser data.

# Related

* [Functional requirements](/requirements/functional.md)
* [Non-functional requirements](/requirements/non-functional.md)
* [Vision](/product/vision.md)
