---
type: Architecture Decision
title: "0021 Supermarket-style web and low-friction list"
description: Catalog with chain photos, generic and concrete products, Tailwind, chain logos, a cart whose lines say what they accept, a one-screen typed list with inline choices, and a minimal browser profile with the shape of decision 0019.
tags: [decision, web, ux, privacy]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-15T00:30:00+01:00
sources:
  - /decisions/0008-application-structure-and-stack.md
  - /decisions/0019-shopper-preferences.md
  - /decisions/0020-rule-based-canonical-matching.md
---
# Context

After iteration 11 the web had no photos, no product catalog and four steps (list, review, origin, basket) with hand-written CSS. The author compared it with QuéFalta and set the interface criteria on 2026-11-14: browse by store or by generic product; each list line says what it accepts; one gesture switches the whole list to any brand without touching pinned products; a pin is one tap; "shop only in…" with logos; a typed list is written and calculated with one button, with anything ambiguous asked inline with photos; the origin is remembered.

# Decision

1. **Photos from the chain's CDN**, loaded lazily with `referrerpolicy="no-referrer"` and a generic image when they fail; the URL is stored per product (`chain_product.image_url`), never the image.
2. **Tailwind CSS 4** for every page; `styles.css` keeps only what Leaflet needs. Official chain logos from Wikimedia Commons in `web/public/logos/`, with a coloured badge when one is missing.
3. **Two ways to browse.** "Por producto" (default) shows canonical cards with photo and "desde X €/kg" (`GET /api/canonicals`, `#/generico/<id>` lists its concrete products); "Por supermercado" shows the chain's products. Search ranks the category or the start of the name first.
4. **Cart lines say what they accept.** A product added from a store is «Este producto» (`exact`), a generic one «Cualquier X» (`equivalent`). «Me da igual la marca» turns every unpinned line to equivalent and new concrete lines enter as equivalent while it is on; the padlock keeps a line exact. «Comprar solo en…» sends `chains`. Cards without a brand show the chain logo, not the chain as a brand.
5. **One screen for a typed list.** Write and press «Calcular»: vague lines show «¿Qué X?» with photo chips, unknown ones a search box, and a missing origin opens the folded origin row; there is no review step. The basket shows each product's photo, «Cambiar» for another product of the same canonical, the `flex_savings` notice with «Aplicar a toda la lista», store cards with logo, address and straight-line distance, and the map.
6. **Minimal browser profile with the shape of 0019.** `preference` rows (`brand_pin` per category, `chain_include` per chain, and a global `any_brand` kind added for the switch) and `choice_event` (`pinned`) in IndexedDB, with a memory fallback, JSON export and import, uuidv7 ids and `navigator.storage.persist()` after the first basket. The origin and route options are remembered in the versioned local storage (schema 3). Only the constraints of the current lines travel with a request.

7. **Concrete-only products.** A product of a leaf with shades (dyes, make-up) is always «Este producto»: no accept selector, no padlock, untouched by the any-brand switch, no «Cambiar» in the basket and no generic «Añadir»; a typed line for it asks the user to pick the product in the catalog.

# Consequences

* The flow from a typed list to a basket is two taps when the origin is remembered and nothing is vague.
* Web checks: 104 unit tests and 15 mocked Playwright tests; the live-stack test covers a vague line resolved inline.
* Learned defaults, `term_choice` and dietary rules of 0019 are not implemented yet; the any-brand switch needed a kind that 0019 did not list.
* Batch 3 added the photo of typed lines (`image_url` in `/api/interpret`) and left a single calculate button. Known gap: no automated test yet for a failed recalculation from the cart or for closing the «Cambiar» dialog with Escape.

# Revisit when

* Accounts exist (0019, scenario B): the profile moves to PostgreSQL with the same entities.
* A second chain has data: «Comprar solo en…» should list only chains with stores and prices near the origin.
