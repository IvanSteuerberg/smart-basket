---
type: Architecture Decision
title: "0019 Shopper preferences"
description: One profile model in three layers, in the browser for the MVP and in PostgreSQL once accounts exist; preferences constrain the basket but never enter the objective; no graph store until thresholds are met.
tags: [decision, persistence, privacy, personalization]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-14T23:00:00+01:00
sources:
  - id: st8
    resource: ../../docs/memoria-prompts/entradas/noviembre.tex
    title: Señal de Tiempo 8
---
# Context

The list is interpreted and the basket computed with defaults that come from the shopper: the usual choice for an ambiguous term («fruta» → plátanos y mandarinas, or «la de temporada»), pinned brands («leche» → Pascual), preferred or excluded chains and rules such as «sin lactosa siempre». The author's interface criteria set how they behave: browse by store or by generic product, one gesture switches the whole list to "any brand" without touching pinned brands, a brand is pinned with one tap, anything ambiguous is asked inline, and the fewer steps the better.

Two scenarios: **(A)** the academic MVP, with no accounts and personal data only in the browser ([scope](/requirements/scope.md), [NFR-06](/requirements/non-functional.md)); **(B)** a later product with accounts, paid subscriptions, preferences on the server and recommendations across users. Decision [0003](/decisions/0003-postgresql-single-database.md) keeps a single PostgreSQL and adds Neo4j only if multi-hop queries or graph algorithms become core. The author asked whether a graph store should hold preferences. Claude (with project context) and DeepSeek V4.1 Flash (without it, with web search) compared a browser profile, PostgreSQL tables, Apache AGE and Neo4j; the author approved the combined proposal on 2026-11-14.[^st8]

# Decision

1. **One profile model for both scenarios, in three layers.** The same entities and fields live in the browser (A) and in PostgreSQL (B); only the storage changes.
   - **Explicit facts** (`preference`): what the shopper set. Synced per item, never recomputed.
   - **Events** (`choice_event`): append-only history of what was accepted, replaced, removed or pinned. Synced as a union by id, so devices never conflict.
   - **Derived** (learned defaults): a cache recomputed from events and explicit facts. Never synced and never exported as truth.
2. **Entities:**
   - `preference`: id (uuidv7, generated on the client), `scope_kind` (`term`, `category`, `chain`, `global`), `scope_key`, `kind` (`brand_pin`, `term_choice`, `chain_include`, `chain_exclude`, `dietary_rule`, `seasonal_rule`), `value` (JSON), `origin` (`explicit` or `imported`), `consent_ref` (dietary rules in B), `created_at`, `updated_at`, `deleted_at` (tombstone). One live row per (`scope_kind`, `scope_key`, `kind`).
   - `choice_event`: id (uuidv7), list term, action (`accepted`, `replaced`, `removed`, `pinned`), canonical id, chain product, brand, chain, date. It stores canonical and product ids, not receipt text.
   - The profile carries a `schema_version` and the canonical ids it refers to are remapped through `merged_into` ([0007](/decisions/0007-data-model.md)) on import and sync. One JSON Schema is the source of the browser types and the server models.
   - The existing browser entities (`list`, `accepted_basket`, `loyalty_card`, `not_found`) keep their place ([data model](/architecture/data-model.md#browser-storage)).
3. **Learning is weighted counting, not a model.** For each term, events are counted with recency decay (half-life about 90 days for term choices, 60 for brands, 120 for chains; none for explicit facts); a replacement weighs more than a plain acceptance, and a pattern needs at least two different lists. The result sets the behaviour:
   - **High confidence** (about 5 effective uses and the top choice at 70 % or more, well ahead of the second): applied without asking, with a visible chip ("asumido: plátanos · cambiar").
   - **Medium confidence:** pre-selected in the inline question, accepted with one tap.
   - **Low confidence or no history:** no default; two or three options inline.
   These thresholds are starting values to calibrate with real use. A strong learned pattern never overrides an explicit fact; at most it suggests reviewing it.
4. **Dietary rules are only explicit.** The app never infers them from history and never suggests them from patterns. «La de temporada» is an explicit rule resolved against a season calendar, not a learned preference.
5. **Preferences never enter the objective.** The optimizer still minimizes cost + lambda × minutes ([0013](/decisions/0013-basket-optimizer-rules.md)). Preferences restrict the candidates (pinned brand, dietary variant, chain filter of [FR-10](/requirements/functional.md)), break near ties, and feed the explanation ("1,20 € más porque fijaste Pascual"). Precedence: the line's own choice > explicit preferences > learned defaults > the global "any brand" switch, which overrides learned brands but not pinned ones.
6. **(A) In the browser:** IndexedDB, with `navigator.storage.persist()` requested after the first completed list, a visible export and import of the profile as a JSON file, and a warning that clearing browser data loses it (Safari may delete site data after 7 days without a visit). Learning runs in the browser. The request sends only the defaults and constraints for the lines of that list, never the history, and the anonymous recommendation keeps only those. A profile hit resolves a vague term before the LLM is called, which also saves interpretation time ([NFR-01](/requirements/non-functional.md)).
7. **(B) On the server:** the same entities as tables in the same PostgreSQL, keyed by user id with `ON DELETE CASCADE` and row-level security. The first login is an idempotent import with granular consent (preferences, history, dietary rules); later syncs merge explicit facts per item by last writer (a hybrid logical clock if several devices edit offline) and events by union. Export uses the same JSON as the browser file.
8. **Recommendations across users (B) start in PostgreSQL:** "people who buy X also buy Y" from co-occurrence counts over accepted baskets in a materialized view refreshed at night; similar profiles with pgvector over per-user vectors; substitutions across several hops with a recursive CTE of at most 3 hops. All of it opt-in.
9. **No graph store now.** Apache AGE (openCypher inside the same PostgreSQL; release 1.7.0 supports PostgreSQL 18 since January 2026) is the first step if graph queries are needed, because it keeps one database and one deletion path. Neo4j only for graph algorithms, as an offline analytical copy of anonymized data, as 0003 already allows.

# Consequences

* The MVP needs no server changes beyond accepting per-line defaults and constraints; accounts later are an import of data that already has the server's shape.
* The optimizer stays deterministic and every cost of a preference can be explained.
* Dietary rules may be health data under art. 9 GDPR: the CJEU treated order data for pharmacy products as health data (C-21/23, Lindenapotheke, 2024). In B they need explicit, separate consent, are stored apart with access auditing and can stay local-only on request; in A they never leave the browser beyond the per-request filter.
* Scenario B makes the operator a controller of profiles: a legal basis per purpose (contract for the account and explicit preferences, consent for profiling beyond the current list and for cross-user recommendations), records of processing, retention limits and a data protection impact assessment before launch. Recommendations the shopper can ignore are not automated decisions under art. 22.
* A graph store would add a second copy of personal data to sync, export and delete; staying in PostgreSQL keeps those obligations in one place.
* Learning by counts is explainable ("lo eliges 4 de cada 5 veces") and testable with fixed event fixtures, but cannot discover tastes the shopper never showed.

# Revisit when

* **Asking less:** asking about an ambiguous term only when its interpretations change the basket (more than about 0.50 € or 2 minutes, at most two questions per list), once interpretation meets NFR-01 and the extra optimizer runs fit in it.
* **Apache AGE:** substitution or recommendation queries need more than 3 hops or variable-length paths in the request path, and the recursive CTE exceeds about 150-200 ms (p95) on real data.
* **Neo4j (analytical copy):** graph algorithms (communities of shoppers, node similarity) become a product feature; DeepSeek's orientative threshold is above 200,000 active users or 500 million interaction edges.
* **A learned model:** with thousands of active accounts, if count-based defaults are changed by the shopper more than about 30 % of the time.
* **Scenario B starts:** authentication, consent records, a revised NFR-06 and the impact assessment.

[^st8]: Prompt log, Señal de Tiempo 8 (Claude with project context and DeepSeek V4.1 Flash with web search). DeepSeek contributed the three layers, keeping preferences out of the objective, applying confident defaults with a visible chip, remapping canonicals on import and the Safari eviction risk; its random exploration and server-side learning in the MVP were not adopted, and its claim that Apache AGE has no stable release for PostgreSQL 18 is wrong (AGE names its published releases `-rc0`).
