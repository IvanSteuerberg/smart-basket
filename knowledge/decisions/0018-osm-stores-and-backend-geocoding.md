---
type: Architecture Decision
title: "0018 Stores from OpenStreetMap and geocoding through the backend"
description: Supermarkets of the ten chains imported from Overpass each month, and typed addresses geocoded with Nominatim through the backend so the user's address and IP never reach third parties or the logs.
tags: [decision, geo, privacy, data]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-14T02:00:00+01:00
sources:
  - /decisions/0007-data-model.md
  - /decisions/0009-valhalla-routing-engine.md
---
# Context

The `store` table ([0007](/decisions/0007-data-model.md)) was empty, and chains publish their store lists in different ways, some only through store locators. The user's starting point can come from GPS, a click on the map or a typed address. Turning an address into coordinates needs a geocoder. Calling a public one from the browser would send the user's IP and address to a third party.

# Decision

1. **Stores from OpenStreetMap.** `smart_basket.stores` queries Overpass for `shop=supermarket|hypermarket` inside a configurable box around León (`STORES_BBOX`).
   - **Buildings named after a chain:** buildings without a `shop` tag whose brand or name maps to a chain are imported too. The Mercadona next to the University of León is mapped only as a building.
   - **Chain mapping:** OSM `brand`, then `name`, are mapped to the ten chains through case- and accent-insensitive aliases. Other shops are ignored, and so are the unverified `brand:wikidata` values.
   - **Upsert:** by `osm_id`, with name, address, location, opening hours and format.
   - **Zone:** the chain's León zone when it has one (Mercadona: warehouse 3683), otherwise the chain-wide zone.
   - **Deactivation:** only stores inside the queried box that are no longer seen. An empty answer, or one with fewer than half of the active stores in the box, deactivates nothing.
   - **Runs:** each run is recorded in `ingest_run` (`kind = 'stores'`).
   - **Schedule:** the worker runs it monthly; `smart-basket-stores import [--dry-run]` runs it by hand.
2. **Geocoding through the backend.** `GET /api/geocode?q=` calls Nominatim from the server, so the user's IP never reaches OpenStreetMap:
   - **Limits:** results bounded to León, at most 5.
   - **Rate:** 1 request per second, with an in-memory cache keyed by the accent-folded text.
   - **Identification:** a generic application `User-Agent`, with no personal data.
   - **Searches:** they run only when the user asks, not while typing, as Nominatim's usage policy requires.
3. **Nothing personal in logs.** The `httpx` logger stays at WARNING, and the API's access log drops query strings, so typed addresses never reach the container logs. Map tiles come from OpenStreetMap's tile server with attribution.

# Consequences

- **First import (2026-11-14):** 41 stores in the León box.
  - Alimerka 13, Dia 11, Mercadona 4, Lidl 4, Lupa 3, Alcampo 2, E.Leclerc 2, Aldi 1, Gadis 1.
  - No Carrefour is tagged inside the box.
  - Overpass answered 502 once and the retry succeeded.
- **Store names:** OSM names are often just the chain name, so the answer also carries the store's address to tell stores apart. Only 17 of the 41 stores have address tags in OSM, and none of the 4 Mercadona stores do; reverse geocoding them is pending.
- **Data quality** depends on OSM tagging; a missing or mistagged store is fixed upstream in OSM.

# Revisit when

- A chain's own store locator proves more complete than OSM for León.
- The app is published beyond personal use: Nominatim's public service is then not enough, and a self-hosted geocoder or a commercial one is needed. Tiles likewise.
