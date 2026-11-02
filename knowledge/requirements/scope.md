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
| Chains | Every chain with an online catalog that serves León: Mercadona, Carrefour, Dia, Alcampo, Gadis, Lupa and Alimerka. Aldi through its weekly offers page, Lidl and E.Leclerc through their flyers. Eroski only if it opens a store in León capital. See the [data-source viability study](/data/source-viability.md) and [0006](/decisions/0006-data-collection-with-a-real-browser.md). |
| Platform | Responsive web app, mobile first. The MVP runs on the author's laptop ([0005](/decisions/0005-local-first-ai-models.md)). |
| Users | Personal use by the author and people they share it with; the app is not published. No accounts and no authentication. Lists and personal history live in the user's browser. |
| Travel | The user chooses walking or car and the shopping date for each request; at most 3 stores per trip. |
| Promotions | Discounted prices, multi-unit offers (NxM, second unit at X %), volume discounts, loyalty-card prices and public coupons, each with its validity period. Collected automatically: flyers (PDF or images) are only used if they can be downloaded without manual steps. |
| List input | Free text interpreted by the agent, plus catalog search to pick specific products or categories. |
| AI models | Local first ([0005](/decisions/0005-local-first-ai-models.md)): local embeddings and a small local LLM in Ollama, with Gemini Flash-Lite on the free API tier as fallback. Final models chosen with the [AI model benchmark](/evaluation/ai-model-benchmark.md). |
| BI | Consumer view (savings per recommendation, local history) and analyst panel (market price evolution). |

# Out of scope

* Native mobile app.
* Publishing the app, user accounts, access control and server-side personal data. To be revisited if the app is ever published; see [Path to user accounts](#path-to-user-accounts).
* Personalized coupons tied to the user's account at a chain (e.g. app-only offers): they cannot be obtained without the user's chain credentials.
* Any manual data collection, such as searching for or scanning flyers.
* Online ordering or checkout at the chains.
* Real-time stock and live traffic.
* Cities other than León.

# Constraints

* Academic project for the course *Sistemas de Información de Gestión y Business Intelligence*, 2026-2027, for personal and non-commercial use.
* Data comes from each chain's website and flyers, collected for personal, non-commercial academic use under the research exception of art. 135 TRLPI; the collected data is not published ([0006](/decisions/0006-data-collection-with-a-real-browser.md)).
* No recurring costs: open-source components, local models or free API tiers.
* Architecture decisions [0001](/decisions/0001-agent-as-orchestrator.md) to [0006](/decisions/0006-data-collection-with-a-real-browser.md) apply.

# Assumptions and risks

* **Data availability** was checked in the [data-source viability study](/data/source-viability.md): a real browser reaches every chain checked, with no login. The remaining risks are site changes and tighter blocks. Lidl, Aldi and E.Leclerc only publish offers in weekly flyers.
* **Store assortment.** A chain's online catalog is not what every store carries: small neighbourhood stores have a reduced range, so a recommended product may not be on the shelf. Mitigations, from most to least reliable: per-store catalogs where a chain publishes them (to check in the viability study), the user marking products as not found ([FR-38](/requirements/functional.md)), a fallback per item ([FR-39](/requirements/functional.md)) and estimates by store format ([FR-40](/requirements/functional.md)).
* Online prices are assumed to match prices in León stores. Chains that price by postal code or warehouse need the León zone selected.
* Without accounts, consumer savings history is lost if the user clears the browser data.

# Path to user accounts

Accounts may be added later. The MVP keeps that path open:

* **Personal data moves to the server** in its own tables of the same PostgreSQL, keyed by a user id: lists, accepted baskets, loyalty cards owned, products reported as not found and, if they are ever built, "lo de siempre" and personal aliases. No other database is needed.
* **Shared data does not change:** catalog, prices, promotions, stores, canonical products, the optimizer and the `bi` schema. Recommendations gain an optional user id, so BI can also report savings per user.
* **Browser data is migrated** on the first login. To make that a copy rather than a transformation, what the MVP stores in the browser follows the same structure as those future tables, as versioned JSON ([data model](/architecture/data-model.md)).
* **New work at that point:** a free, simple authentication (email magic link or an open-source identity server such as Keycloak), GDPR obligations for server-side personal data (consent, account deletion, data export) and a revision of [NFR-06](/requirements/non-functional.md).

# Related

* [Functional requirements](/requirements/functional.md)
* [Non-functional requirements](/requirements/non-functional.md)
* [Vision](/product/vision.md)
