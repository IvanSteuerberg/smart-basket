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
| Users | Personal use by the author and people they share it with; the app is not published. No accounts and no authentication. Lists and personal history live in the user's browser. |
| Travel | The user chooses walking or car and the shopping date for each request; at most 3 stores per trip. |
| Promotions | Discounted prices, multi-unit offers (NxM, second unit at X %), volume discounts, loyalty-card prices and public coupons, each with its validity period. Collected automatically: flyers (PDF or images) are only used if they can be downloaded without manual steps. |
| List input | Free text interpreted by the agent, plus catalog search to pick specific products or categories. |
| AI models | Lightweight local models preferred, especially for product embeddings. A cloud LLM with no recurring cost (e.g. Gemini Flash on the free API tier) is acceptable where a light local model is not good enough. Final choice pending (prompt log, next signal). |
| BI | Consumer view (savings per recommendation, local history) and analyst panel (market price evolution). |

# Out of scope

* Native mobile app.
* Publishing the app, user accounts, access control and server-side personal data. To be revisited if the app is ever published.
* Personalized coupons tied to the user's account at a chain (e.g. app-only offers): they cannot be obtained without the user's chain credentials.
* Any manual data collection, such as searching for or scanning flyers.
* Online ordering or checkout at the chains.
* Real-time stock and live traffic.
* Cities other than León.

# Constraints

* Academic project for the course *Sistemas de Información de Gestión y Business Intelligence*, 2026-2027, for personal and non-commercial use.
* Data comes from public sources of each chain; scraping must respect their terms and the legal constraints still to be studied.
* No recurring costs: open-source components, local models or free API tiers.
* Architecture decisions [0001](/decisions/0001-agent-as-orchestrator.md) to [0004](/decisions/0004-canonical-product-model.md) apply.

# Assumptions and risks

* **Data availability is the main risk.** Without good price and promotion data there is no good recommender. Lidl and Aldi publish many offers in weekly flyers rather than in an online catalog. The data-source viability study must confirm which chains, fields and promotions can be obtained automatically.
* **Store assortment.** A chain's online catalog is not what every store carries: small neighbourhood stores have a reduced range, so a recommended product may not be on the shelf. Mitigations, from most to least reliable: per-store catalogs where a chain publishes them (to check in the viability study), the user marking products as not found ([FR-38](/requirements/functional.md)), a fallback per item ([FR-39](/requirements/functional.md)) and estimates by store format ([FR-40](/requirements/functional.md)).
* Online prices are assumed to match prices in León stores. Chains that price by postal code or warehouse need the León zone selected.
* Without accounts, consumer savings history is lost if the user clears the browser data.

# Related

* [Functional requirements](/requirements/functional.md)
* [Non-functional requirements](/requirements/non-functional.md)
* [Vision](/product/vision.md)
