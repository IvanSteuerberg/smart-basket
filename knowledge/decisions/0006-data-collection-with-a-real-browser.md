---
type: Architecture Decision
title: "0006 Data collection with a real browser"
description: Every chain with an online catalog, collected periodically with a real browser or the site's own public API, with catalog, prices and promotions stored apart.
tags: [decision, data, ingestion, scraping]
status: draft
generated:
  by: deepseek-harness/glm-5.3
  at: 2026-11-20T21:32:00+01:00
sources:
  - id: st6
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 6
---
# Context

Good recommendations need prices and promotions from as many chains in León as possible, collected with no manual steps ([NFR-13](/requirements/non-functional.md)). The [data-source viability study](/data/source-viability.md) found that plain HTTP clients are blocked by Dia, Lupa and El Corte Inglés and that Mercadona keeps prices in an API its robots.txt disallows, while Mercadona, Gadis, Alimerka, Froiz, Aldi (via its public Algolia index `an_prd_es_es_pen_products2`), Lidl (`endpoints.leaflets.schwarz`) and E.Leclerc (`folletos.e-leclerc.es`) can be collected over plain HTTP and Dia, Lupa and El Corte Inglés work in a headed Chromium session (`with-xvfb` in the `worker` container, [0024](/decisions/0024-dia-ingestion-and-catalog-agent.md)). Carrefour and Alcampo currently serve Cloudflare Turnstile (`403`) and AWS WAF (`405 Human Verification`) challenges to automated container runs and stay paused while gated. A conservative reading (DeepSeek in Señal de Tiempo 6) would keep only 4-5 chains and a few hundred products each.[^st6] The author chose to go further, for personal, non-commercial academic use with the data kept private, under the research exception of art. 135 TRLPI.

# Decision

1. **Chains:** every accessible chain that serves León: Mercadona (`4,307`), Gadis (`10,732`), Lupa (`8,479`), Alimerka (`7,308`), Froiz (`7,106`), Dia (`5,438`), El Corte Inglés / Supercor (`~8,000+`) and Aldi (`2,856` priced products across its full fixed assortment and offers in Algolia `an_prd_es_es_pen_products2` + `/api/offer/es/*`). Lidl (`endpoints.leaflets.schwarz/v4/flyer`) and E.Leclerc (`folletos.e-leclerc.es` `window.staticSettings.pageTexts`) contribute their digital food flyers. Carrefour and Alcampo are paused while gated by anti-bot challenges; Eroski stays out because it has no store in León capital and choosing a zone needs a login.
2. **Method:** where a chain's own JSON/HTML endpoint works over plain HTTP once the León zone (`24001`) or store header is set, it is called directly with `httpx` (Mercadona, Gadis, Alimerka, Froiz, Aldi, Lidl, E.Leclerc). Where a browser session is required (Dia, Lupa, El Corte Inglés), a headed Chromium session under `with-xvfb` sets León's postal code, keeps the session and walks the categories via same-origin `fetch()` or DOM extraction. Credentials, when needed, live in `.env` or the author's vault, never in the repository. A chain paused by an anti-bot gate resumes through a **supervised unlock**, never through automated circumvention: the browser runs with a persistent profile, which keeps the anti-bot session token between runs (AWS WAF's `aws-waf-token`; the silent challenge usually renews it with no interaction), and when an interactive puzzle appears the run enters an unlock state — the browser stays open on the worker's Xvfb display, the worker posts a single Telegram Bot API notification with a link, the author solves the puzzle once through noVNC (published by the same Cloudflare Tunnel as the domain, behind Cloudflare Access limited to the author), and the run resumes when the token cookie appears; an unsolved run times out gracefully and leaves the chain at its last successful snapshot. The unlock helper is provider-generic (AWS WAF: `405` + `x-amzn-waf-action`; Cloudflare interstitial detection), and before any unlock the blocked chain is retried with warm persistent-profile navigation that lets the site issue its own requests.
3. **Scope:** the full catalog of each chain. Rate and frequency are set after the first runs, with prices no older than 48 h as the target ([NFR-02](/requirements/non-functional.md)).
4. **Storage, collected periodically and not when a basket is requested:**
   * **Raw snapshots** of every response, with date and hash, for auditing and reprocessing.
   * **Chain products:** name, brand, format, category, EAN when known and the link to the canonical product ([0004](/decisions/0004-canonical-product-model.md)). They change slowly.
   * **Price observations** per product and zone (warehouse or postal code), kept as history ([0003](/decisions/0003-postgresql-single-database.md)).
   * **Promotions** apart, each with its type (price cut, NxM, second unit, volume, loyalty, coupon), parameters, validity period and source (web or flyer).
   * **Stores** from OpenStreetMap, linked to their chain and zone.

   At request time the recommender reads the latest price and the promotions valid on the shopping date to get the effective price.
5. **Enrichment:** Open Food Facts for EAN and attributes.
6. **Flyers and controlled staple retention (Lidl and E.Leclerc):** embedded text layers (`keyWords` in Schwarz Leaflets v4; `window.staticSettings.pageTexts` in iPaper) are extracted first, paired with structured LLM/vision extraction over page images where needed. To avoid recommending expired discounts or out-of-stock *in-and-out* campaign items:
   * While a flyer is within its validity window (`offerStartDate <= today <= offerEndDate`), its promotional price is active (`is_active = True`).
   * When the flyer expires, seasonal or limited-stock items (`*Artículos limitados`, *Deluxe*, bazar, or variable-weight fresh produce without a reference regular price) are deactivated (`is_active = False`).
   * Permanent private-label staples (*Milbona*, *Bellarom*, *Baresa*, *Alesto*, *Chef Select*, *Kania*, *Combino*, *Formil*, *Cien*, *W5*, *Marca Guía*, *Eco+*) that carry an explicit regular non-promotional price (`strike_price` / `Antes X,XX €`) revert automatically to their regular price upon promo expiry, with a bounded 21-day TTL since last observation.

# Consequences

* Coverage is much wider than the reference TFG: the full catalog of 7-8 chains, unit prices and price cuts, with no hand-kept URLs.
* Collecting ahead of time keeps the 5 s target ([NFR-01](/requirements/non-functional.md)) and feeds the BI price history; separate promotions handle validity periods and flyer sources.
* One adapter per chain ([NFR-12](/requirements/non-functional.md)); site changes will break adapters, so each one has contract tests on saved snapshots and its own failure handling ([NFR-09](/requirements/non-functional.md)).
* Risks: the chains' terms of use, the data-mining reservation in Mercadona's robots.txt, and blocks if a site tightens its protection. Mitigations: personal use, no publication of the data, moderate rate.
* **Supervised unlock is a documented, scoped exception to [NFR-13](/requirements/non-functional.md):** a gated chain is automatic on most runs, and the manual step is kept rare by the persistent profile, warm-up navigation, moderate rate, a residential connection for production (a friend's home server) and scheduling those runs at hours when the author is reachable. Automated circumvention is ruled out also on legal grounds: the text-and-data-mining exception (Directive (EU) 2019/790) covers only lawfully accessible content, and defeating a technical access control would taint the access.

# Revisit when

* A chain blocks the real browser or changes its site substantially.
* The app is published or used by more people.
* The first runs set the rate and frequency.
* A supervised chain's manual step becomes too frequent to justify its coverage (frequency measured over the first weeks of runs).

[^st6]: Prompt log, Señal de Tiempo 6 (Claude and DeepSeek V4.1 Flash with web search).
