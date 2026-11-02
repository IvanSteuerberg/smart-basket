---
type: Test Plan
title: Recommender evaluation plan
description: How the MVP shows that its baskets are correct, save money against simple baselines, rest on good data and meet the quality targets.
tags: [evaluation, recommender, optimizer, data-quality, bi]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-01T23:55:00+01:00
---
Complements the [AI model benchmark](/evaluation/ai-model-benchmark.md), which picks the models. This plan evaluates the recommender as a whole: the optimizer, the data behind it, the value of its recommendations and the quality targets in the [non-functional requirements](/requirements/non-functional.md). Every recommendation can be recomputed from its stored inputs and data date ([NFR-05](/requirements/non-functional.md)), so all offline tests replay saved snapshots.

# What is evaluated

| Area | Question | Main requirements |
| --- | --- | --- |
| Optimizer | Is the basket the best one for the given prices, times and lambda, every time? | [FR-13](/requirements/functional.md), NFR-03 |
| Data | Are prices fresh, complete and correctly matched across chains? | FR-23, FR-27, NFR-02, NFR-04, NFR-14 |
| Value | How much does a recommendation save, and at what cost in time, compared with what a shopper would do without it? | FR-17, FR-19, FR-29 |
| Robustness | What happens when a product is missing, a chain's data is stale or the LLM is down? | FR-21, FR-38, FR-39, FR-41, NFR-09 |
| Performance and usability | Is it fast enough and easy enough for a first-time user? | NFR-01, NFR-08 |
| BI | Do the dashboards answer the analyst's questions? | FR-31 to FR-35 |

# Datasets

* **Benchmark lists:** the same 30 real shopping lists as the AI model benchmark, with the hand-labelled interpretation. They cover small (5 items), typical (15) and large (30) lists, with and without brand constraints.
* **Origins:** 5 starting points spread over León (centre, two neighbourhoods, two edges of the city), each with walking and car.
* **Data snapshots:** at least four weekly snapshots of prices and promotions, so results are compared across weeks and promotion cycles.
* **Receipts:** the author's own shopping receipts from León stores during the evaluation weeks, used to spot-check prices with no extra visits.

# Optimizer correctness

* **Exhaustive check:** with at most 3 stores among about 10 candidates there are at most 175 store combinations, so for every benchmark case a brute-force solver enumerates them all and the optimizer must return a basket of the same cost (objective `cost + lambda * minutes`, tolerance one cent).
* **Determinism:** the same list, origin, lambda and snapshot always give the same basket ([NFR-03](/requirements/non-functional.md)); checked by running every case twice and comparing results byte for byte.
* **Effective price:** unit tests for each promotion mechanic and quantity (for example 3x2 with 2, 3, 4 and 7 units; second unit at -50 % with odd quantities), for loyalty prices with and without the card, and for promotions already included in the price.
* **Lambda sweep:** for a few lists, lambda from 0 (savings only) to a high value (time only); the number of stores must not increase as lambda grows, and the extremes must match the cheapest basket and the nearest single store.

# Data quality

| Metric | Target | How |
| --- | --- | --- |
| Freshness | 95 % of prices less than 48 h old on any day | Ingestion runs and `last_seen` ([NFR-02](/requirements/non-functional.md)) |
| Coverage | Share of benchmark items with a price in at least 3 chains | Replay of the benchmark lists |
| Matching precision | At least 90 % of canonical assignments correct ([NFR-04](/requirements/non-functional.md)); hard-negative confusion at most 3 % (NFR-14) | Labelled sample of 300 assignments, stratified by chain and category |
| Price accuracy | Online price equals shelf price for at least 90 % of spot-checked items | Receipts, plus the zone samples of the viability study. In-store markdowns that no website publishes (for example -30 % on fresh meat close to its use-by date) are excluded, and loyalty discounts shown as separate lines on the receipt are compared with the online loyalty price |
| Promotion parsing | At least 95 % of promotions with the right mechanic, parameters and dates | Sample of 100 promotions checked against the source page or flyer |

# Value of the recommendations

Each benchmark case is compared with three baselines a shopper could follow without the app:

1. **Cheapest single store:** the store among those nearby with the lowest total for the whole list (also the savings reference of [FR-17](/requirements/functional.md)).
2. **Nearest store:** the closest store that carries most of the list.
3. **Usual chain:** the author's usual chain, buying the cheapest equivalent of each item there.

Metrics per case and in aggregate:

* Savings in euros and percent against each baseline.
* Extra travel minutes against the nearest-store baseline, and euros saved per extra minute.
* Number of stores visited and share of items substituted by an equivalent.
* The cost-time front of [FR-19](/requirements/functional.md): whether the alternatives offered (one, two and three stores) are each the best for their number of stores.

The expected result is not a single number but a pattern to discuss: when visiting a second or third store pays off in León, for which list sizes and for walking versus car.

# Robustness

* **Missing products:** remove the recommended product from a store and check that the fallback of [FR-39](/requirements/functional.md) is an equivalent in the same store or the next store on the route, and that items with no match are reported ([FR-21](/requirements/functional.md)).
* **Stale chain:** mark one chain's data as older than 48 h and check that the system keeps working with the others and flags it ([NFR-09](/requirements/non-functional.md)).
* **No LLM:** run the benchmark with the LLM disabled and compare interpretation F1 and basket cost with the normal run ([FR-41](/requirements/functional.md)).

# Performance and usability

* **Latency:** plan p50 and p95 for the benchmark lists on the author's laptop, against the 5 s target of [NFR-01](/requirements/non-functional.md), split into interpretation, candidate search, travel-time matrix and optimization.
* **Usability:** 5 people who have not used the app get a list and must obtain a recommendation on a phone. Measures: time to the first recommendation (target under 2 minutes, [NFR-08](/requirements/non-functional.md)), errors and a short System Usability Scale questionnaire.

# BI

For each analyst requirement (FR-31 to FR-35) a dashboard in Metabase answers one concrete question, such as how a reference basket's price evolved per chain over the evaluation weeks, or which chain runs the deepest promotions in dairy. The check is that every question is answered from the `bi` schema alone and that the figures match a direct query on the transactional tables for a sample of days.

# Reporting

Results go to a short report with the tables above, the cost-time front for a few representative lists and the limitations found (coverage gaps, chains with stale data, matching errors). Targets that are not met are reported as such, with their cause.
