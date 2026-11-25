# Supervised unlock test plan — Carrefour and Alcampo

Goal: measure, with data, whether the two chains paused by anti-bot gates
([decision 0006](../../knowledge/decisions/0006-data-collection-with-a-real-browser.md))
can re-enter the weekly ingestion through the **supervised unlock** recorded there,
and at what manual-step frequency. The frequency measured here is what justifies —
or rejects — the scoped exception to NFR-13.

Both chains serve anti-bot gates to fresh automated contexts
([data-source viability](../../knowledge/data/source-viability.md)):

* **Alcampo** (`compraonline.alcampo.es`): AWS WAF, `405` + `Human Verification`
  interstitial at top-level navigation; the `aws-waf-token` cookie only exists after
  the gate passes in a real browser session.
* **Carrefour** (`carrefour.es/supermercado`): Cloudflare, `403` block page
  (`Attention Required!`) on a clean context; unknown yet whether a warm
  profile passes, whether it degrades to a solvable Turnstile
  (`Just a moment...`), or whether it stays a hard block.

## Principles (non-negotiable)

1. **No automated circumvention** ([NFR-07](../../knowledge/requirements/non-functional.md)):
   no CAPTCHA-solving services, no stealth/anti-detection hardening, no token
   replay outside the browser. An interactive puzzle is solved by the author,
   once, in the session's own browser window.
2. **The instrument is navigation, not synthetic requests.** Never measure the
   gate with a hand-rolled `fetch()`/`httpx` call. Open the site, let the page
   issue its own requests, and capture those responses with a
   `page.on("response")` listener. A `fetch()` returns the interstitial as a
   dry `405` even when the session is valid, so it proves nothing.
3. **One persistent profile per chain** (`experiments/supervised-unlock/profiles/alcampo`,
   `.../carrefour`), created with `launch_persistent_context(user_data_dir=...)`,
   never `browser.new_context()`. The profile is the state under test.
4. **Everything is measured and logged.** Every run appends one record to
   `results.jsonl` (schema at the end) before the browser closes.

## T1 — Baseline unlock (local, visible browser window)

Run on the author's machine with a visible window (not inside the `worker`
container): the first interactive puzzle needs a human in front of the screen.

Per chain, same procedure:

1. Launch `launch_persistent_context(user_data_dir=profiles/<chain>, headless=False)`.
2. Register a response listener that records every request the site itself
   makes (`status`, URL) while browsing.
3. Navigate to the chain's entry page (Alcampo:
   `https://www.compraonline.alcampo.es/categories/frescos/OC2112`;
   Carrefour: `https://www.carrefour.es/supermercado/`), then walk to one
   category page naturally (clicks/scroll, no shortcuts).
4. **If an interactive puzzle appears**, leave the browser open and have the
   author solve it once. Record `gate_type` and who solved it
   (`silent` / `interactive_author`).
5. After the gate passes, verify:
   * page title is no longer `Human Verification` / `Just a moment...`;
   * the session carries the anti-bot cookie (`aws-waf-token` for Alcampo;
     `cf_clearance` for Carrefour if challenged);
   * the listener captured the site's own API/product requests, and product
     data (names, prices) is present in those payloads.
6. Save 2-3 captured responses per chain as **contract samples**
   (`samples/<chain>-*.json`): the future adapter's contract tests will
   replay them ([NFR-09](../../knowledge/requirements/non-functional.md)).
7. Close the browser. The profile must not be deleted between runs.

Carrefour outcomes and what they mean:

* (a) Navigation is clean from a warm profile → the earlier `403` was a
  cold-context artifact; proceed with T2.
* (b) A Turnstile interstitial appears and passes (alone or via the author) →
  same supervised-unlock pattern as Alcampo; proceed with T2.
* (c) `403 Attention Required!` persists → go to T4.

**Finding (2026-11-21):** Carrefour's Cloudflare has been observed blocking on
the automation markers themselves (`--enable-automation` /
`navigator.webdriver` present), not only on a cold context. Masking those
markers (dropping default args, patching the runtime, spoofing fingerprints)
is out of scope per principle 1 — it is defeating the detection, not behaving
like a user. Expected outcomes are therefore (b) or (c): if the warm profile
is served Turnstile, the supervised unlock applies and `cf_clearance` takes
the role `aws-waf-token` plays for Alcampo; if the block stays hard, T4
closes the chain as paused.

## T2 — Token persistence (the metric that decides NFR-13)

Relaunch the **same profile** — no cleanups, no new context — and repeat a
short browsing pass at:

* **T+1h**, **T+24h**, **T+72h**, **T+7d** after the T1 unlock.

Per run, record: whether the silent challenge renewed with no interaction,
whether an interactive puzzle reappeared, wall-clock time of the pass, and
whether the site's API responses still carry product data.

**Pass criteria (both chains, over the 7-day window):**

* interactive puzzles ≤ 1 per week per chain;
* manual flow, when needed, ≤ 2 minutes end to end;
* API payloads parse with product name + price on every passing run.

If a chain exceeds the criteria, that chain triggers the *Revisit when* clause
of decision 0006 and its coverage is reconsidered instead of scaled. The
reconsideration has a defined landing: the chain degrades to **flyer-only
offers** (RadarSuper's ungated folletos, or the chain's own Publitas
publication for Alcampo) with the catalog frozen at its last snapshot and
flagged stale ([NFR-09](../../knowledge/requirements/non-functional.md)) —
it is not dropped outright.

## T3 — Production flow end to end (worker container)

Repeat inside the real ingestion environment, on the server:

1. Move the warm profile into the `worker` volume; run Chromium headed under
   `with-xvfb` exactly like the Dia/Lupa adapters.
2. Attach `x11vnc` to the Chromium Xvfb display and serve noVNC
   (`websockify`) on `localhost:6080`.
3. Publish that port through the **same Cloudflare Tunnel** the domain already
   uses, as a separate hostname (e.g. `unlock.<domain>`), and protect it with
   a **Cloudflare Access** application whose only policy is the author's
   email. The hostname must never be reachable without the Access login.
4. Wire the notification: when the adapter detects the gate
   (`405` + `x-amzn-waf-action` for AWS WAF; interstitial title for
   Cloudflare) and it does not clear silently within 60 s, the worker posts
   one Telegram Bot API `sendMessage` with the noVNC link. Bot token and
   chat id live in `.env`, never in the repository.
5. **Forced-puzzle drill:** delete the anti-bot cookie from the profile and
   start a run. Measure the full chain: detection → notification → author
   opens the Access-protected noVNC page → puzzle solved in the server's
   browser → run resumes on its own. Target: under 3 minutes, author-side
   effort under 2 minutes.
6. **Degradation drill:** start a forced-puzzle run and do not respond.
   Verify the run times out cleanly (suggested 30 min), the chain keeps its
   last valid snapshot, nothing is half-written, and the event is recorded
   for the Watcher.

## T4 — Carrefour decision rule

If T1/T2 show outcome (c) — `403 Attention Required!` persisting with a warm
profile and natural navigation — then the site does not serve automated
clients and there is no solvable challenge to unlock: Carrefour stays
**paused** (NFR-13's "or not at all") and the
[data-source viability study](../../knowledge/data/source-viability.md)
records the block as verified with a warm profile, closing the question.

## Results

One JSON line per run in `results.jsonl`:

```json
{"ts": "...", "chain": "alcampo", "phase": "T1", "profile": "fresh|warm(T+1h|T+24h|T+72h|T+7d)",
 "gate_type": "none|silent|interactive_author|hard_block", "pass_seconds": 0,
 "api_calls": 0, "products_seen": 0, "notes": "..."}
```

Summaries land where the bundle reads them: measured frequencies and the
pass/fail verdict per chain go to *Verified checks* in the
[data-source viability study](../../knowledge/data/source-viability.md), and
the contract samples feed the adapters' snapshot-based contract tests.
