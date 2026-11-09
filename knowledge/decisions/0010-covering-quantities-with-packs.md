---
type: Architecture Decision
title: "0010 Covering quantities with packs"
description: Pack combinations between 80 % and 150 % of the requested quantity compete on price per base unit; near ties go to the one that reaches the quantity with the least excess.
tags: [decision, optimizer, pricing]
status: stable
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T12:00:00+01:00
---
# Context

Canonical products have no size ([0007](/decisions/0007-data-model.md)): the user asks for a quantity ("1 kg of yogurt") and each store sells packs of fixed sizes. Packs rarely add up to the exact quantity. For packs of 400 g and a request of 1 kg, 2 packs fall short and 3 overshoot. With the same pack the price per kilogram is the same, so the choice only matters when promotions or different formats change the price per unit. The author's criterion: reach the requested quantity unless falling short is clearly cheaper in relative terms.

# Decision

For each line and store, the effective-price step chooses the pack combination as follows:

1. **Candidates:** combinations of the store's packs for that canonical product whose total is between **80 %** and **150 %** of the requested quantity, with promotions applied ([0007](/decisions/0007-data-model.md), point 6).
2. **The lowest price per base unit wins** (per kilogram, litre or unit).
3. **Near ties** (within **5 %** of the best price per base unit) go to the combination that reaches the requested quantity with the least excess; if none reaches it, the one closest to it.
4. The three thresholds are configuration values.
5. The result shows the quantity bought for each line. A line with an exact format or brand ([FR-04](/requirements/functional.md)) skips this rule.

Examples for 1 kg in 400 g packs: without promotions, 2 and 3 packs tie on price per kilogram and 3 packs are bought; with "second unit at -50 %", 2 packs cost 1.88 €/kg and 3 packs 2.08 €/kg, so 2 packs (800 g) are bought.

# Consequences

* Baskets can differ slightly in quantity from the list, so the savings report compares the quantities actually bought.
* The rule gets unit tests together with the promotion mechanics ([recommender evaluation](/evaluation/recommender-evaluation.md)).

# Revisit when

* Users find the quantities surprising, or the thresholds prove too loose or too strict on real baskets.
