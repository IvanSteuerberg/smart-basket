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
Checked on 2026-10-31 (pending checks completed the same evening) with plain HTTP requests, with a real browser (Claude Code's built-in browser, non-essential cookies rejected) and with a second source (DeepSeek V4.1 Flash with web search).[^st6] The decision taken from it is [0006](/decisions/0006-data-collection-with-a-real-browser.md).

# Starting point

A 2023 TFG[^tfg] scraped prices with `requests` and BeautifulSoup, one product page at a time, from URLs stored by hand per EAN. It worked for Dia and Carrefour, was blocked by Alcampo and Hipercor, skipped Mercadona because its site asked for a session, and collected no promotions. Lessons: hand-kept URLs do not scale ([NFR-13](/requirements/non-functional.md)), promotions are essential, and Open Food Facts is useful to complete products by EAN.

# Findings per chain

"Plain HTTP" is a request from a non-browser client; "real browser" is a full Chromium session.

| Chain | Plain HTTP | Real browser | Data and source | Notes |
| --- | --- | --- | --- | --- |
| Mercadona | robots.txt allows only `/product` pages and the sitemap; product pages carry no price | Works without login | Public JSON API used by the site: `/api/categories/{id}/?wh=<warehouse>`. Postal code 24001 maps to warehouse `3683`. Fields: name, packaging, unit price, price per kg/L, size and format, previous price, price decreased. About 4,560 product entries in 152 subcategories for León | No EAN; brand is part of the name. robots.txt disallows `/api`. Only price cuts are flagged; none were active on the day |
| Carrefour | 403 | Works without login | Prices and unit prices in the HTML, JSON-LD offers per category with product counts, `cloud-api` endpoints. About 25,800 products for León across nine grocery categories | Defaults to postal code 28232 (Madrid). Setting 24001 stores a `salepoint` cookie (`0000GV`) and changes the assortment (La Despensa goes from 7,014 to 9,287 products) but not the sampled price. Promotions shown: 2nd unit -50 %, 3x2, Club Carrefour |
| Dia | 403 (even robots.txt) | Works without login | Price and price per kg in the listing, `/api/v1/plp-insight/...` endpoints, dietary tags (gluten-free, lactose-free) and out-of-stock marks | Setting 24001 changes the assortment shown |
| Alcampo | Normal | Works without login | Price and price per litre in search and listings, `/api/...` endpoints. A promotions page lists each promotion with type and validity, e.g. `2ª unidad -50% (22/10/26_04/11/26)`, `3x2 (...)`, Club Alcampo | Defaults to postal code 28029 (Madrid); León is set through a delivery address (a public address in 24003 works). Sampled price unchanged |
| Eroski | Normal | Works without login | Prices and discounts in search results | Choosing a delivery zone requires a login, and OSM shows no Eroski store in León capital: low priority |
| Gadis | Normal | Works without login | Price and price per kg on Gadisline | Delivers to León (24001-24006 in its postal code list); prices shown with 24001 set. Flyer promotions may not apply online |
| Lupa | Normal | Works without login | Prices on `lupaonline.com` | Delivers to León capital (24001-24010) and its area, among 639 postal codes. robots.txt disallows the store locator |
| Alimerka | 403 | Works as a guest with a postal code | Online shop on `alimerkaonline.es` (Salesforce Commerce Cloud): name, format and price in search and listings | The login screen offers "Entrar como invitado"; with 24001 it delivers to León. Flyers on `folletos.alimerka.es` |
| Lidl | Normal | Works | No online grocery shop. Weekly flyers from `endpoints.leaflets.schwarz/v4/flyer`: validity dates, downloadable PDF, keywords per page | Products are not structured; they must be extracted from the PDF |
| Aldi | Normal | Works | No online grocery shop. The offers page lists each offer in HTML: name, discount, current and previous price, size, price per kg and validity ("Del 26 de octubre al 1 de noviembre"). Weekly flyers at `/folleto/semanal-<week>-<year>.html` | Offers are better read from the HTML than from the flyer |
| E.Leclerc | Normal | Works | No online grocery shop. Local León flyer on `folletos.e-leclerc.es` (e.g. 19-31 October) with a text layer, plus national flyers; store hours on its page (09:00-21:30) | Prices come split in the text ("8 € ,95") and need parsing; restrictive legal notice |

# Store locations

OpenStreetMap through Overpass, under ODbL with attribution, as the base. In León capital it lists, among others, Alimerka 8, Dia 7, Lidl 4, Mercadona 3, Alcampo 2, Lupa 2, E.Leclerc 1 plus an E.Leclerc Express, and Aldi 1; no Eroski. Opening hours in OSM are incomplete; chain store locators are used to fill and check them.

# Complementary sources

| Source | Use | License |
| --- | --- | --- |
| Open Food Facts | EAN, brand, format and attributes to enrich and match products ([0004](/decisions/0004-canonical-product-model.md)) | ODbL (database), CC BY-SA (images) |
| Open Prices | Crowdsourced prices; coverage in León expected to be sparse | To check |
| Community projects (e.g. `datania/mercadona-catalog`) | Reference for endpoints and fields | Code under MIT; data from the chains |

# Promotions

* **On the web:** price cuts with previous price (Mercadona, Aldi, Eroski) and per-unit prices everywhere. Carrefour and Alcampo show NxM, second unit at -50 % and loyalty-club offers; Alcampo writes the validity next to each promotion. Exact fields per chain are mapped when each adapter is built.
* **Flyers:** the main source for Lidl and E.Leclerc and a complement elsewhere. Both checked flyers carry text (Lidl as PDF, E.Leclerc in its viewer), so text extraction comes first; OCR or a local vision model only where there is no text, with a confidence threshold and discarding doubtful items.

# Legal frame

Personal, non-commercial academic use with the data kept private. The basis is the research exception of art. 135 of the Spanish copyright law (TRLPI) for the database right. Remaining risks are the chains' terms of use and the text-and-data-mining reservation that a robots.txt `Disallow` expresses under Directive (EU) 2019/790. Case law on 2023-2026 and the exact TRLPI article on data mining are still to verify.

# Pending checks

* Whether prices (not only assortment) differ by zone: the samples in Carrefour and Alcampo did not change between Madrid and León; to confirm on a larger sample in the first runs.
* Catalog size of Dia, Alcampo, Gadis, Lupa and Alimerka, to size ingestion time and rate (Mercadona about 4,560, Carrefour about 25,800 for León).
* Field mapping of promotions per chain while building each adapter.

[^st6]: Prompt log, Señal de Tiempo 6.
[^tfg]: Reference TFG stored in the author's OSF project, folder 04-referencias.
