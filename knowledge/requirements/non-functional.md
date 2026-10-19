---
type: Requirements
title: Non-functional requirements
description: Quality targets for the MVP; numeric values are proposals to confirm.
tags: [requirements, non-functional, mvp]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-19T19:30:00+02:00
---
Numeric targets are initial proposals and must be confirmed or adjusted once real data exists. Scope is defined in [MVP scope](/requirements/scope.md).

| ID | Area | Requirement |
| --- | --- | --- |
| NFR-01 | Performance | A recommendation for a list of up to 30 items is returned in under 5 s (p95), including the agent's interpretation and explanation. The optimizer alone takes under 1 s. To be reviewed if a local LLM is chosen. |
| NFR-02 | Data freshness | Prices are at most 48 h old; older prices are flagged to the user. |
| NFR-03 | Correctness | The optimizer is deterministic: the same list, location and data snapshot always give the same basket. Prices and totals are never produced by the LLM. |
| NFR-04 | Equivalence quality | At least 90 % of canonical product assignments are correct on a manually validated sample. |
| NFR-05 | Reproducibility | Every recommendation records its inputs and the data snapshot date, so it can be recomputed. |
| NFR-06 | Privacy | No accounts and no personal data stored on the server. The user's location is used for the request and not stored, or stored only rounded for anonymous analytics. If a cloud LLM is used, it receives only the shopping list text, never the location. |
| NFR-07 | Responsible scraping | Ingestion respects each chain's robots.txt and terms, limits request rate and runs off-peak. Details depend on the legal constraints study. |
| NFR-08 | Usability | Mobile-first responsive interface in Spanish; a recommendation can be obtained in under 2 minutes by a first-time user. |
| NFR-09 | Resilience | If one chain's ingestion fails, the system keeps working with the other chains and with that chain's last valid data, flagged as stale. |
| NFR-10 | Deployment | The whole system runs with Docker Compose on a single modest server. |
| NFR-11 | Cost | No recurring cost: open-source components, local models or free API tiers. API usage per recommendation is measured to stay within free-tier limits. |
| NFR-12 | Maintainability | Each chain's scraper is an independent module; the optimizer and the equivalence logic have automated tests. The LLM provider sits behind an interface so a local model and a cloud one are interchangeable. |
| NFR-13 | Automation | Weekly operation needs no manual steps: catalog, prices, promotions and flyers are collected automatically, or not at all. |
