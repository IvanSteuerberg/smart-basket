# Log

## 2026-11-09

* **Create** Decision 0015 (seed taxonomy: 13 sections, 56 groups, 327 leaves of interchangeable products, every Mercadona level 3 section mapped) and decision 0016 (ingestion adapters). Iteration 10 built the seed loader, the Mercadona adapter and the lexicon builder; first real runs stored 4,307 products of Mercadona León with change-only prices. Decision 0007 and the data model point to 0015; the system overview lists the new parts.
* **Update** Decision 0013: the separate-stop rule is implemented (engine 1.1.0). A line left out is priced at its cheapest comparable cost plus the coverage margin, so the margin is compared with the detour, not with the item's whole price; `store_limit` is replaced by `separate_stop` and `unreachable`. Decision 0014: numbers inside names and slash or "o" alternatives fixed; the second real list goes from F1 0.82 to 0.88. 712 backend tests pass.
* **Create** Course evaluation (deliverables and report structure from the class of 2026-11-04) and Competitors (QuéFalta, Soysuper, Carritus, Tiendeo, OkLista; gap and SWOT inputs).
* **Update** Decision 0013 after the author's review: coverage with a separate-stop option and a configurable coverage margin replaces strict coverage first (code still pending). Decision 0014: known issues with numbers inside product names and slash alternatives, found with a second real list (F1 0.82 rules only, added to the AI model benchmark).

## 2026-11-03

* **Fix** Local review of the three deliveries on the author's laptop: `.gitattributes` forces LF for shell scripts, since a CRLF checkout broke the database's first start (0011). Verified there: 601 tests and migrations, the whole Compose stack, `bi_reader` limited to `bi`, Metabase, and Valhalla with the real Castilla y León extract (walking and driving matrices). Rules-only result on the local real list added to the AI model benchmark.
* **Create** Decision 0014 (rule-based preprocessor v1), from the third delivery: `smart_basket.preprocessor` (normalization, quantities, brands, variants, lexicon interface, synthetic fixture lexicon) and `smart_basket.llm` (Ollama and Gemini behind one protocol).
* **Update** AI model benchmark with the rules-only pass on the 8 example lists (mean F1 0.967, 92 % of lines resolved, optimistic because the fixture lexicon knows the lists). System overview: preprocessor status and pending parts.
* **Create** Decision 0013 (basket optimizer rules), from the second delivery: `smart_basket.optimizer` (effective price, pack covering of 0010, exhaustive search) and `smart_basket.routing` (interface and Valhalla client).
* **Update** Recommender evaluation plan: the lambda sweep checks minutes and cost monotonicity; the store count is not monotone in general (counter-example in 0013). Data model: effective price points to the implementation and to 0013. System overview: optimizer status.
* **Create** Decision 0011 (skeleton layout and tooling) and decision 0012 (schema implementation details), from the first implementation delivery: `backend/`, `web/`, `infra/`, `compose.yaml`, Alembic migrations of the transactional and `bi` schemas, CI.
* **Update** Data model: `canonical_product.default_quantity`, `promotion.priority` and `daterange` validity, `recommendation_item.part`, reference basket tables and dimension, base unit in the category price fact. System overview: BI module, deployment with the `migrate` service and an implementation status table.

* **Create** Decision 0009 (Valhalla as routing engine, OSRM to be compared later) and decision 0010 (covering quantities with packs: 80-150 % band, lowest price per base unit, near ties to the one reaching the quantity). 0002, 0008 and the system overview point to 0009.
* **Update** FR-02: list built by browsing or searching the catalog, generic item by default. NFR-11 and 0005: the paid Gemini tier is required if the app is published to users in the EEA.
* **Update** FR-09 with starting lambda values (0.05, 0.15 and 0.40 €/min). 0008: latest stable versions, pinned.

## 2026-11-02

* **Create** Decision 0008 (application structure and stack): one repository, Python/FastAPI backend shared by the `api` and `worker` services, React + Vite + TypeScript PWA served by Caddy, PostgreSQL, routing engine and Metabase in Docker Compose, Ollama native on the host, scraping with Playwright in the worker. System overview and NFR-10 updated.
* **Update** AI model benchmark: Qwen3.5 0.8B added (fastest, same accuracy as 2B on the example lists); a real household list shows that example lists overestimate accuracy and that the preprocessor must normalize abbreviations and joined words. 0005 candidates updated.

## 2026-11-01

* **Update** Scope: path to user accounts (personal data to its own PostgreSQL tables, shared data unchanged, browser data migrated on first login, authentication and GDPR work). Data model: browser storage as versioned JSON with the shape of the future tables. Recommender evaluation plan: in-store markdowns excluded from price checks.
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
