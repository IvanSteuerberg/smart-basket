---
type: Assessment
title: Data-source viability study
description: What each chain in León publishes, how it can be collected automatically, and what is still to check.
tags: [data, ingestion, scraping, legal]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-10-31T22:00:00+01:00
sources:
  - id: st6
    resource: ../../docs/memoria-prompts/entradas/octubre.tex
    title: Señal de Tiempo 6
  - id: tfg
    resource: https://osf.io/ysmkz/
    title: "TFG (UPM, 2023): app de ahorro en la compra de alimentos mediante web scraping (OSF, 04-referencias)"
---
Checked on 2026-10-31 with plain HTTP requests, with a real browser (Claude Code's built-in browser, non-essential cookies rejected) and with a second source (DeepSeek V4.1 Flash with web search).[^st6] The decision taken from it is [0006](/decisions/0006-data-collection-with-a-real-browser.md).

# Starting point

A 2023 TFG[^tfg] scraped prices with `requests` and BeautifulSoup, one product page at a time, from URLs stored by hand per EAN. It worked for Dia and Carrefour, was blocked by Alcampo and Hipercor, skipped Mercadona because its site asked for a session, and collected no promotions. Lessons: hand-kept URLs do not scale ([NFR-13](/requirements/non-functional.md)), promotions are essential, and Open Food Facts is useful to complete products by EAN.

# Findings per chain

"Plain HTTP" is a request from a non-browser client; "real browser" is a full Chromium session.

| Chain | Plain HTTP | Real browser | Data and source | Notes |
| --- | --- | --- | --- | --- |
| Mercadona | robots.txt allows only `/product` pages and the sitemap; product pages carry no price | Works without login | Public JSON API used by the site: `/api/categories/{id}/?wh=<warehouse>`. Postal code 24001 maps to warehouse `3683`. Fields: name, packaging, unit price, price per kg/L, size and format, previous price, price decreased | No EAN; brand is part of the name. robots.txt disallows `/api` |
| Carrefour | 403 | Works without login | Prices and unit prices in the HTML, JSON-LD offers per category (7,014 products in La Despensa), `cloud-api` endpoints | Defaults to postal code 28232 (Madrid); León must be set |
| Dia | 403 (even robots.txt) | Works without login | Price and price per kg in the listing, `/api/v1/plp-insight/...` endpoints | Postal code to be set |
| Alcampo | Normal | Works without login | Price and price per litre in search and listings, `/api/...` endpoints | Defaults to postal code 28029 (Madrid) |
| Eroski | Normal | Works without login | Prices and discounts in search results | Store in León capital to confirm |
| Gadis | Normal | Works without login | Price and price per kg on Gadisline | Coverage of León and postal code to confirm; flyer promotions may not apply online |
| Lupa | Normal | Works without login | Prices on `lupaonline.com` | Catalog is per city; León coverage to confirm. robots.txt disallows the store locator |
| Alimerka | 403 | Login wall (DNI) | Online shop on `alimerkaonline.es` | Needs the author's account; flyers on `folletos.alimerka.es` |
| Lidl | Normal | Works | No online grocery shop. Weekly flyers from `endpoints.leaflets.schwarz/v4/flyer`: validity dates, downloadable PDF, keywords per page | Products are not structured; they must be extracted from the PDF |
| Aldi | Normal | Not checked | No online grocery shop; weekly offers and flyers | To check |
| E.Leclerc | Normal | Not checked | No online grocery shop; flyers per store, including León | To check; restrictive legal notice |

# Store locations

OpenStreetMap through Overpass, under ODbL with attribution, as the base. In León capital it lists, among others, Alimerka 8, Dia 7, Lidl 4, Mercadona 3, Alcampo 2 and Lupa 2. Opening hours in OSM are incomplete; chain store locators are used to fill and check them.

# Complementary sources

| Source | Use | License |
| --- | --- | --- |
| Open Food Facts | EAN, brand, format and attributes to enrich and match products ([0004](/decisions/0004-canonical-product-model.md)) | ODbL (database), CC BY-SA (images) |
| Open Prices | Crowdsourced prices; coverage in León expected to be sparse | To check |
| Community projects (e.g. `datania/mercadona-catalog`) | Reference for endpoints and fields | Code under MIT; data from the chains |

# Promotions

* **Structured on the web:** price cuts with previous price (Mercadona, Alcampo, Eroski), per-unit prices everywhere. NxM, second unit and loyalty prices to be mapped per chain during implementation.
* **Flyers:** the only source for Lidl, Aldi and E.Leclerc, and a complement elsewhere. Text extraction from PDF first; OCR or a local vision model only where the PDF has no text layer, with a confidence threshold and discarding doubtful items.

# Legal frame

Personal, non-commercial academic use with the data kept private. The basis is the research exception of art. 135 of the Spanish copyright law (TRLPI) for the database right. Remaining risks are the chains' terms of use and the text-and-data-mining reservation that a robots.txt `Disallow` expresses under Directive (EU) 2019/790. Case law on 2023-2026 and the exact TRLPI article on data mining are still to verify.

# Pending checks

* Set León's postal code in Carrefour, Dia, Alcampo and Gadis and confirm prices change accordingly.
* Lupa, Gadis and Eroski: coverage of León capital.
* Alimerka: catalog after login with the author's account.
* Aldi and E.Leclerc: flyer format and whether their PDFs carry a text layer.
* Field mapping of promotions per chain (NxM, second unit, loyalty prices).
* Catalog size per chain, to size ingestion time and rate.

[^st6]: Prompt log, Señal de Tiempo 6.
[^tfg]: Reference TFG stored in the author's OSF project, folder 04-referencias.
