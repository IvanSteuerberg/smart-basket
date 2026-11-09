---
type: Architecture Decision
title: "0013 Basket optimizer rules"
description: How the MVP optimizer compares stores, covers quantities, applies promotions, orders the route, reports missing lines and breaks ties, and why the store count can rise with lambda.
tags: [decision, optimizer, pricing, routing, implementation]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T01:40:00+01:00
---
# Context

Decisions [0002](/decisions/0002-routing-in-three-layers.md), [0007](/decisions/0007-data-model.md) (point 6) and [0010](/decisions/0010-covering-quantities-with-packs.md) and requirements [FR-09](/requirements/functional.md), FR-13, FR-15, FR-16 and FR-21 define the optimizer: exhaustive search over at most 3 of about 10 stores, objective cost + lambda x minutes, one mechanic per line, the pack-covering rule. Writing it (module `smart_basket.optimizer`) left several questions open; the author was not available, so they were decided here following `knowledge/` and are open to review.

# Decision

## Comparing stores

1. **Comparable cost.** When a line is covered with the rule of 0010, stores are compared by the chosen combination's price per base unit times the requested quantity, not by the amount paid. Otherwise a store whose packs fall short (800 g for a 1 kg request) would always look cheaper than one that reaches the quantity. The amount paid and the quantity bought are reported for every line, and `total_cost` is what the shopper pays. The objective is the sum of comparable costs plus lambda x minutes.
2. **Lines with exact brand or format, pack counts and fallbacks** (rules below) compare by the amount paid, since the quantity bought is not chosen within a band.

## Covering a line in one store

3. **Base units:** g and ml convert to kg and l. A line counting units ("ud") of a product sold by weight or volume uses the canonical's `default_quantity` ([0012](/decisions/0012-schema-implementation-details.md)): "6 bricks de leche" with 1 l per unit asks for 6 l. Without a default quantity it buys that many packs of the product with the lowest total cost (`pack_count`).
4. **Mixing formats:** a combination may mix up to **2 distinct products** (configurable), such as a 1 kg and a 500 g pack; each product is priced with its own promotions. Promotions are counted per product, not across products ("3x2 mixing flavours" is not modelled yet).
5. **Ties of the 0010 rule** that remain after least excess (or least shortfall) go to the lower cost, then the lowest product ids. Price per base unit is compared exactly (integer cents and thousandths of the base unit).
6. **No combination in the band** (only a 3 kg sack for a 1 kg request): the store buys the single product with the lowest cost that reaches the quantity (`fallback`).
7. **Exact brand or format** (FR-04, 0010 point 5): only matching products, each with the fewest packs that reach the quantity; the cheapest wins (`exact`). A refused private label removes those products.

## Effective price

8. **Mechanics:** promo price and loyalty price per pack; percent off; buy N pay M as `pay = qty - floor(qty / N) * (N - M)`; second unit at X % off on every pair (X is the discount); volume tiers where the highest tier reached prices every unit (by unit price or percent); coupons take an amount (once per line, never below zero) or a percent off the line. Each line cost is rounded to cents half up.
9. **Conditions:** validity is checked on the shopping date (end exclusive); zone-restricted promotions need the store's zone; `requires_loyalty` (any mechanic) needs the chain's card among the buyer's cards; a coupon applies only if its code is among the buyer's coupons (the request builder can pass every public coupon); promotions marked as included in the observed price are skipped; targets are the product, its canonical, its category or any ancestor, or its brand.
10. **No stacking; tie-break:** a promotion must be strictly cheaper than the plain price to be applied, so equal costs are reported without promotion. Among promotions, higher `priority` wins, then lower id.

## Search and route

11. **Coverage with a separate-stop option** (the author's review, 2026-11-09). A line that some candidate store sells but no store of the subset does is left out at the price of its **lowest comparable cost in any candidate store plus a coverage margin** (`coverage_margin`, 3 € per line to start, never negative). Subsets are ranked by (objective + that price of the lines left out, lines left out, number of stores, minutes, store ids). So the full plan wins when the extra paid for the item at the added store, compared with its cheapest store, plus lambda x the extra minutes stays under the margin, as when the only store with the item is nearly on the way; otherwise the shorter plan wins and the line becomes a **separate stop**. A margin of 0 compares objectives only; a very large margin gives the old coverage-first rule. Lines that no candidate store sells add nothing.
    * The separate stop names the store where the line is cheapest to add (lowest comparable cost + lambda x extra minutes, ties to the lowest store id), the purchase there (amount paid, comparable cost, quantity, packs), the extra minutes of adding that store to today's route (every permutation re-routed, respecting the return to the origin) and whether it would exceed the maximum number of stores.
    * Each stop is computed for its line alone: two lines sent to the same store do not add up their extra minutes, and lines the plan already buys are not moved there. A line sold by a store already on the route is always bought there (point 12), and a plan always visits at least one reachable store.
12. **Within a subset** each line goes to its store with the lowest comparable cost (ties to the lowest store id). A subset in which some store would buy nothing is skipped.
13. **Route:** the trip **returns to the origin** by default (a shopping trip ends at home or at the car); requests can set `return_to_origin = false`. Every permutation of the subset is checked (at most 6); ties go to the smallest order of store ids. A leg the routing engine marks unreachable discards the route.
14. **Missing lines** (FR-21) are listed with a reason: `not_available` (no candidate store sells a product satisfying the line), `separate_stop` (left out by point 11, with the stop details) or `unreachable` (some store sells it, but none can be added to today's route because the travel matrix marks a leg unreachable). They are excluded from the totals and never dropped silently.
15. **Lambda:** an explicit value in €/min, or the preset of the priority mode: savings 0.05, balanced 0.15, time 0.40 (FR-09).
16. **Determinism and version:** inputs are sorted by id before the search, money is `Decimal` and every tie has a rule, so the same request gives byte-identical JSON. The result carries `engine_version` (`basket-engine/1.1.0` since the separate-stop rule), to be bumped whenever the same input could give a different basket.

## Store count and lambda

17. With exact optimization, raising lambda never increases the minutes and never lowers the comparable cost. **The number of stores, however, can rise**: with one cheap store far away and two complementary stores near the origin, lambda 0 picks the far store, a medium lambda the two near ones and a high lambda one near store. The test plan therefore checks minutes and cost monotonicity on random instances, the extremes (cheapest basket at lambda 0, nearest single store at a very high lambda when every store sells every line), the store count on a typical case, and this counter-example.

# Consequences

* Store choice no longer favours buying less than asked, and the result still shows what is paid and bought.
* The optimizer needs no database or network: the request carries prices, promotions and the travel-time matrix, so tests replay it exactly (NFR-03, NFR-05).
* Measured on the development container: 30 lines x 10 stores with up to 5 formats per line and store in about 0.02 s; a dense catalog with 8 formats per line and store and a promotion on every product in about 0.35 s, within the 1 s of NFR-01.

# Revisit when

* The coverage margin (3 € per line) is calibrated with real baskets in the [recommender evaluation](/evaluation/recommender-evaluation.md); the author does not consider it final (2026-11-09).
* The interface lets a shopper end the trip somewhere other than the origin (one-way routes, point 13).
* Mixed-product promotions ("3x2 across the range") appear in the collected data.
* Users find the comparable cost or the quantities surprising.
* More than 3 stores or more than about 10 candidates are needed (mixed-integer programming, 0002).
