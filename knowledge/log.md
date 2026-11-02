# Log

## 2026-11-01

* **Update** AI model benchmark with a first pass on the laptop (Ollama 0.40.13, CPU and Arc): no candidate interprets a whole list within 5 s; Qwen3.5 2B and Gemma 4 E4B on the Arc lead; Granite 4.2 3B discarded. Gemma 4 added to the candidates in 0005. Script and data in `experiments/llm-benchmark/`.
* **Create** Recommender evaluation plan: optimizer checked against brute force, determinism and promotion unit tests; data-quality targets; savings against three baselines; robustness, latency, usability and BI checks.
* **Create** Decision 0007 (data model) and the data model document: canonical products without brand or size, prices as change-only intervals with a current-price table, typed promotions with targets, anonymous recommendations, and an aggregated star schema in a `bi` schema. From Señal de Tiempo 7 (Claude and DeepSeek V4.1 Flash), the first entry of November, kept because the OLTP/OLAP split is central to the course.
* **Update** Decision 0004 open questions now point to 0007; system overview OLTP/OLAP point resolved.

## 2026-10-31

* **Update** Data-source viability study with the pending checks: León set in Carrefour, Dia, Alcampo and Gadis; Lupa and Gadis serve León; Eroski has no store in León capital and needs a login to set a zone; Aldi offers in HTML; E.Leclerc León flyer with text; catalog sizes of Mercadona and Carrefour; promotion types. Decision 0006 and scope drop Eroski for now.
* **Update** Alimerka works as a guest with a postal code (no login needed): study, decision 0006 and scope.
* **Create** Data-source viability study in a new `data/` section, from Señal de Tiempo 6 (Claude and DeepSeek) and checks of every chain with plain HTTP and a real browser.
* **Create** Decision 0006 (data collection with a real browser): every chain with an online catalog, full catalogs, catalog, prices and promotions stored apart, collected periodically. Status `draft` until the first runs.
* **Update** Scope (chains, data constraint and availability risk), NFR-07 (responsible scraping) and the ingestion module in the system overview.
* **Create** Decision 0005 (local-first AI models) from Señal de Tiempo 5, with three sources (Claude, Gemini and DeepSeek). Status `draft` until the AI model benchmark runs.
* **Create** AI model benchmark plan in a new `evaluation/` section: candidates, datasets, metrics and the decision rule of 0005.
* **Update** Requirements: the MVP runs on the author's laptop (scope, NFR-10); NFR-01 measures the 5 s target on the plan and streams the explanation; NFR-06 keeps data on the machine by default; new NFR-14 (AI quality) and FR-41 (degraded mode without LLM); FR-18 takes explanation figures from templates.
* **Update** System overview: rule-based preprocessor in the recommender; embedding model open point now points to 0005.

## 2026-10-19

* **Update** Requirements review with the author: personal use without publication or authentication, shopping date and promotion validity (FR-36, FR-37), store assortment mitigations (FR-38 to FR-40), automatic-only data collection (NFR-13), no recurring cost with local or free-tier models.
* **Update** Prompt log renumbered after recovering Señal de Tiempo 2 (2026-09-21) from OSF: routing is now ST3 and the persistence revalidation ST4. Decision sources updated; 0003 now cites the original decision of 2026-09-21.
* **Create** MVP scope, functional requirements (FR-01 to FR-35) and non-functional requirements (NFR-01 to NFR-12), from scope answers given by the author. Vision updated to point to the scope.
* **Create** Bundle initialized with the product vision, glossary, system overview and decisions 0001-0004, distilled from the concept document v1.1 and prompt log entries ST1-ST4.
