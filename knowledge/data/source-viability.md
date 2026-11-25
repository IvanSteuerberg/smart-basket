---
type: Assessment
title: Data-source viability study
description: What each chain in León publishes, how it can be collected automatically, and what is still to check.
tags: [data, ingestion, scraping, legal]
status: draft
generated:
  by: antigravity/gemini-4-neon-high
  at: 2026-11-21T14:00:00+01:00
sources:
  - id: st6
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 6
  - id: tfg
    resource: https://osf.io/ysmkz/
    title: "TFG (UPM, 2023): app de ahorro en la compra de alimentos mediante web scraping (OSF, 04-referencias)"
---
Checked initially on 2026-10-31 with plain HTTP requests, a real browser and DeepSeek V4.1 Flash,[^st6] and updated on 2026-11-20 after building and running the production ingestion adapters in iterations 10, 14, 15 and 16. The decision taken from it is [0006](/decisions/0006-data-collection-with-a-real-browser.md).

# Starting point

A 2023 TFG[^tfg] scraped prices with `requests` and BeautifulSoup, one product page at a time, from URLs stored by hand per EAN. It worked for Dia and Carrefour, was blocked by Alcampo and Hipercor, skipped Mercadona because its site asked for a session, and collected no promotions. Lessons: hand-kept URLs do not scale ([NFR-13](/requirements/non-functional.md)), promotions are essential, and Open Food Facts is useful to complete products by EAN.

# Findings per chain

"Plain HTTP" is a request from a non-browser client (`httpx` with desktop `User-Agent`); "real browser" is a headed Chromium session under `with-xvfb` inside the `worker` container ([0024](/decisions/0024-dia-ingestion-and-catalog-agent.md)).

| Chain | Plain HTTP | Real browser | Data and source | Notes |
| --- | --- | --- | --- | --- |
| Mercadona | Works on `/api/categories/{id}/?wh=3683` | Works without login | Public JSON API: `/api/categories/{id}/?wh=<warehouse>`. Postal code `24001` maps to warehouse `3683`. **4,307** active products in 152 subcategories for León (ingested & 100 % classified) | No EAN; brand is part of the name. `robots.txt` disallows `/api`. Price cuts carry `previous_unit_price` |
| Gadis | Works (`200 OK`) | Works without login | Public REST API v3: `POST https://api.gadisline.com/api/v3/catalog/products/search` with header `store-id: 94ae5a01-5b46-4fac-a859-b6470c22078b` (resolved for `24001` via `/api/v3/checkpoints/zipcode/24001`) and `site-id: 56df88f9-479f-4361-891e-e1864dba1ca3`. **10,732** active products for León (ingested, 100 % classified & exhaustively audited) | Full brand, price, price per kg/L, unit size and category hierarchy in JSON |
| Lupa | 403 on raw `httpx` | Works without login (same-origin `fetch()`) | Magento 2 catalog at `https://www.lupaonline.com/santander/<category>?p=<page>`. **8,479** active products across 170 leaf categories for León (ingested, 100 % classified & exhaustively audited) | Delivers to León capital (`24001–24010`). Prices, unit prices and promotions parsed from server-rendered product cards |
| Alimerka | Works (`200 OK` with session cookies) | Works without login | Salesforce Commerce Cloud on `https://www.alimerkaonline.es`: `Stores-FindByZipcode?consent=true&zipcode=24001` sets the León store cookie, then `Search-UpdateGrid?cgid=<5digit>&start=<offset>&sz=100` paginates all leaf categories. **7,308** active products for León (ingested, 100 % classified & exhaustively audited) | No browser needed once the guest session cookie is established for `24001` |
| Froiz | Works (`200 OK`) | Works without login | Hydra JSON-LD API at `https://servicios.froiz.com/api/products?page=<n>&size=100` and `/api/categories` (`storescoverage/coverage/24001` resolves `cod_ent: 1, cod_subent: 198` for León). **7,106** active products | Structured JSON with `name`, `brand_name`, `base_price`, `order_price`, `offer` (`price`, `date_from`, `date_to`), `per_unit_weight`, `measurement_unit`, and dietary flags (`is_glutenfree`, `is_lactosefree`, `is_bio`, `is_eco`, `is_frozen`) |
| Dia | 403 | Works without login (same-origin `fetch()`) | `/api/v1/plp-insight/initial_analytics` for the 31-L1 / 267-L2 category tree after `GET /api/v1/away-from-home/save-shipping-address?new_postal_code=24001`, then `/api/v1/plp-back/reduced` (`plp_items`) per category page. **5,438** active products for León (ingested, 100 % classified & exhaustively audited) | Zero price difference found across 18 sampled categories between `24001` and `24008` |
| El Corte Inglés / Supercor | 403 on raw `httpx` | Works without login (`200 OK` in Playwright) | Category listings across all 11 supermarket sections under `https://www.elcorteingles.es/supermercado/<category>/`. **20,304** active products for León (`24001`, ingested, 100 % classified & exhaustively audited) | Physical supermarket in León (C/ Fray Luis de León 29). Cards include price, unit price, format, brand and multi-unit promotions (`2ª unidad`) |
| Aldi | Works (`200 OK`) | Works without login | Public Algolia catalog index `an_prd_es_es_pen_products2` (`POST https://L9KNU74IO7-dsn.algolia.net/1/indexes/an_prd_es_es_pen_products2/query` with public search key from `aldi.es` Next.js bundle) plus `GET https://www.aldi.es/api/offer/es/current`. **2,698** active priced products for Peninsula (ingested, 100 % classified & exhaustively audited) | Not limited to weekly flyers: the Algolia index exposes Aldi Spain's full fixed assortment (`surtido-fijo-alimentacion`) and active promotions with `name`, `brandName`, `salesUnit`, `currentPrice.priceValue`, `strikePriceValue`, `basePriceValue` (€/kg, €/L), `validFrom`/`validUntil` and `hierarchicalCategories` |
| Lidl | Works (`200 OK`) | Works | No online grocery catalog; `lidl.es/q/search` only lists non-food bazar. Digital flyers API `GET https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=<slug>&region_id=0&region_code=0` returns active food flyers with per-page `keyWords` (OCR text), `altText`, high-res page images (`imgproxy.leaflets.schwarz`) and `pdfUrl`. **463** active products ingested (100 % classified & exhaustively audited) | Uses controlled staple retention (Option B, see below) so promotional prices never outlive `offerEndDate` while permanent private-label staples revert to their regular price with a 21-day TTL |
| E.Leclerc | Works (`200 OK`) | Works | No online grocery catalog (`compraonline.e-leclerc.es` is an empty stub). `https://www.e-leclerc.es/leon/folletos` links to active iPaper flyers on `https://folletos.e-leclerc.es/eleclerc-spain/2026/...` (local León flyer + national grocery flyers) with `window.staticSettings.pageTexts` and iPaper CDN page images (`cdn.ipaper.io`). **178** active products ingested (100 % classified & exhaustively audited) | Prices in `pageTexts` come split alongside brand, weight and unit price, plus `ANTES: / AHORA:` and controlled staple retention |
| Carrefour | 403 on `carrefour.es` (Cloudflare); **Works (`200 OK`) via RadarSuper** | Blocked on `carrefour.es` (`Attention Required!`) | Direct `carrefour.es/supermercado` stays paused after T1 (2026-11-21) verified a persistent Cloudflare `403` with no solvable challenge (NFR-07 / NFR-13). Collected cleanly over plain HTTP via RadarSuper (`https://radarsuper.com/carrefour`, 152 leaf categories, `robots.txt` explicitly `Allow: /`, daily refreshed). **10,222** active products ingested (`0000GV`, 100 % classified, `0` errors) | Zero anti-bot evasion: `CarrefourAdapter` parses server-rendered Next.js RSC product objects (`price`, `size`, `unit`, `brand`, `image`, `url`) with polite rate-limiting |
| Alcampo | 405 on `compraonline.alcampo.es` (AWS WAF); **Works (`200 OK`) via RadarSuper** | AWS WAF re-challenged at `T+1h` in T2 | Supervised unlock T1 (2026-11-21) passed with one manual CAPTCHA solve (`aws-waf-token` issued), but T2 (`warm(T+1h)`) re-triggered the interactive CAPTCHA after 1 hour, failing NFR-13 (`<= 1 puzzle/week`). Collected cleanly over plain HTTP via RadarSuper (`https://radarsuper.com/alcampo`, 152 leaf categories, `robots.txt` `Allow: /`, daily refreshed; official Publitas flyers `view.publitas.com/21552/...` as secondary fallback). **18,962** active products ingested (`24003`, 100 % classified, `0` errors) | Shared `RadarSuperAdapter` plain-HTTP engine with zero CAPTCHAs or browser dependency |
| Eroski | Works (`200 OK`) | Works without login | `supermercado.eroski.es/es/` | Choosing a delivery zone requires a login, and OSM shows no Eroski store in León capital: excluded from León scope |

# Store locations

OpenStreetMap through Overpass, under ODbL with attribution, as the base. In León capital it lists, among others, Alimerka 8, Dia 7, Lidl 4, Mercadona 3, Alcampo 2, Lupa 2, E.Leclerc 1 plus an E.Leclerc Express, and Aldi 1; no Eroski. Opening hours in OSM are incomplete; chain store locators are used to fill and check them.

# Complementary sources

| Source | Use | License |
| --- | --- | --- |
| Open Food Facts | EAN, brand, format and attributes to enrich and match products ([0004](/decisions/0004-canonical-product-model.md)) | ODbL (database), CC BY-SA (images) |
| Open Prices | Crowdsourced prices; coverage in León expected to be sparse | To check |
| Community projects (e.g. `datania/mercadona-catalog`) | Reference for endpoints and fields | Code under MIT; data from the chains |
| RadarSuper (`radarsuper.com`) | Ungated plain-HTTP route for Carrefour promotions: the chain's official folletos served page by page (server-rendered HTML, downloadable PDFs, per-page product transcriptions, validity dates) plus daily online-store price drops with unit prices; robots.txt explicitly allows folletos and product pages (disallows only `/api/`, accounts, search) and publishes a folletos sitemap. Also carries **Alcampo** folletos (19 live, refreshed daily), whose PDFs resolve to the chain's own ungated **Publitas** publications (`view.publitas.com`) — the same flyer-platform pattern as Lidl (Schwarz) and E.Leclerc (iPaper), and a first-party fallback for Alcampo offers. Candidate to cover the Carrefour offers use case without the gated catalog | Independent editorial comparator, unaffiliated with the chains; León/regional editions, transcription coverage, Publitas text layers and freshness to probe before use |

# Promotions and flyer retention

* **On the web:** price cuts with previous price (Mercadona, Aldi, Froiz, Gadis, Lupa, Alimerka, Dia, El Corte Inglés) and per-unit prices everywhere. Froiz exposes explicit `offer` objects (`price`, `date_from`, `date_to`); Aldi's Algolia index exposes `currentPrice.priceValue`, `strikePriceValue` and `validFrom`/`validUntil`.
* **Flyer-only chains (Lidl and E.Leclerc) — controlled staple retention:** both checked flyer platforms carry an embedded text layer (`keyWords` + page images in Schwarz Leaflets v4 for Lidl; `window.staticSettings.pageTexts` in iPaper for E.Leclerc). Because naive historical accumulation across weekly flyers risks recommending expired promotional prices or out-of-stock *in-and-out* campaign items:
  1. While a flyer is within its validity window (`offerStartDate <= today <= offerEndDate`), the promotional price is active (`is_active = True`).
  2. When a flyer expires, temporary or seasonal items (`*Artículos limitados`, *Deluxe*, bazar, or variable-weight fresh produce without a reference regular price) are deactivated (`is_active = False`).
  3. Permanent private-label staples (*Milbona*, *Bellarom*, *Baresa*, *Alesto*, *Chef Select*, *Kania*, *Combino*, *Formil*, *Cien*, *W5*, *Marca Guía*, *Eco+*) that carry an explicit regular non-promotional price (`strike_price` / `Antes X,XX €`) revert automatically to their regular price upon promo expiry, with a bounded 21-day TTL since last observation.

# Legal frame

Personal, non-commercial academic use with the data kept private. The basis is the research exception of art. 135 of the Spanish copyright law (TRLPI) for the database right. Remaining risks are the chains' terms of use and the text-and-data-mining reservation that a robots.txt `Disallow` expresses under Directive (EU) 2019/790. Case law on 2023-2026 and the exact TRLPI article on data mining are still to verify.

# Verified checks (I10–I16)

* **Zone price invariance within León:** checked on Dia across 18 categories between `24001` and `24008` (`0 / 18` price differences, [0024](/decisions/0024-dia-ingestion-and-catalog-agent.md)).
* **Exact León (`24001`) live catalog sizes (12 / 12 active chains, `96,197` products total, 100.0 % classified):** El Corte Inglés `20,304`, Alcampo `18,962`, Gadis `10,732`, Carrefour `10,222`, Lupa `8,479`, Alimerka `7,308`, Froiz `7,106`, Dia `5,438`, Mercadona `4,307`, Aldi `2,698`, Lidl `463`, E.Leclerc `178`.
* **Supervised unlock T1/T2 (2026-11-21, `experiments/supervised-unlock/results.jsonl`):** Carrefour's Cloudflare `403` persisted on T1 with no solvable challenge; Alcampo passed T1 (`36.3 s`, `aws-waf-token` issued) but re-triggered an interactive CAPTCHA at T2 (`warm(T+1h)`), failing NFR-13's `<= 1 puzzle/week` threshold. Both chains moved cleanly to the ungated plain-HTTP `RadarSuperAdapter` (`robots.txt` `Allow: /`, daily refreshed), eliminating manual unlocks and anti-bot friction entirely.

[^st6]: Prompt log, Señal de Tiempo 6.
[^tfg]: Reference TFG stored in the author's OSF project, folder 04-referencias.
