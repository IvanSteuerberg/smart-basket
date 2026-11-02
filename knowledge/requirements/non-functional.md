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
| NFR-01 | Performance | For a list of up to 30 items, the plan (items, stores, cost and minutes) is shown in under 5 s (p95), including the agent's interpretation. The explanation follows in streaming: first words in under 1.5 s and complete in under 10 s. The optimizer alone takes under 1 s. Measured on the author's laptop ([0005](/decisions/0005-local-first-ai-models.md)). |
| NFR-02 | Data freshness | Prices are at most 48 h old; older prices are flagged to the user. |
| NFR-03 | Correctness | The optimizer is deterministic: the same list, location and data snapshot always give the same basket. Prices and totals are never produced by the LLM. |
| NFR-04 | Equivalence quality | At least 90 % of canonical product assignments are correct on a manually validated sample. |
| NFR-05 | Reproducibility | Every recommendation records its inputs and the data snapshot date, so it can be recomputed. |
| NFR-06 | Privacy | No accounts and no personal data stored on the server. The user's location is used for the request and not stored, or stored only rounded for anonymous analytics. By default no data leaves the machine. If the cloud fallback LLM is used, it receives only the shopping list text, never the location, stores or travel times; the Gemini API terms for the European Economic Area apply the paid-service data terms to the free tier, so prompts are not used to train models. |
| NFR-07 | Responsible scraping | Ingestion behaves like a user with a real browser (or the site's own public API), with the author's account where a login is needed. It runs at a moderate rate, set after the first runs, and the collected data stays private ([0006](/decisions/0006-data-collection-with-a-real-browser.md)). |
| NFR-08 | Usability | Mobile-first responsive interface in Spanish; a recommendation can be obtained in under 2 minutes by a first-time user. |
| NFR-09 | Resilience | If one chain's ingestion fails, the system keeps working with the other chains and with that chain's last valid data, flagged as stale. |
| NFR-10 | Deployment | The whole system runs with Docker Compose on a single machine, the author's laptop for the MVP. Ollama may run natively on the host to use the integrated GPU. The same images must run on a server, with configuration only through environment variables ([0008](/decisions/0008-application-structure-and-stack.md)). |
| NFR-11 | Cost | No recurring cost: open-source components, local models or free API tiers. API usage per recommendation is measured to stay within free-tier limits. Publishing the app to users in the EEA, Switzerland or the UK requires the paid Gemini API tier (Gemini API terms): about 1-4 € per 1,000 recommendations at November 2026 prices, so the cost appears only if the app is published. |
| NFR-12 | Maintainability | Each chain's scraper is an independent module; the optimizer and the equivalence logic have automated tests. The LLM provider sits behind an interface so a local model and a cloud one are interchangeable. |
| NFR-13 | Automation | Weekly operation needs no manual steps: catalog, prices, promotions and flyers are collected automatically, or not at all. |
| NFR-14 | AI quality | On the [AI model benchmark](/evaluation/ai-model-benchmark.md): list interpretation F1 of at least 0.90; tool calls with valid JSON in at least 95 % of first attempts and 99.5 % after schema validation and one retry; at most 3 % of hard negatives (same family, different format or variant) taken as equivalents. |
