import { useEffect, useReducer, useRef, useState } from "react";
import {
  answerAgentRun,
  describeError,
  getChains,
  getHealth,
  getSections,
  interpretText,
  isChoiceRequired,
  requestRecommendation,
  startAgentRun,
  type ActiveChain,
  type AgentAnswerRequest,
  type AgentRunRequest,
  type AgentRunResponse,
  type CanonicalCard,
  type CatalogSection,
  type HabitInput,
  type Health,
  type Product,
  type Recommendation,
  type RecommendationRequest,
} from "./api";
import { canonicalLine, genericLine, specificLine, type CartLine } from "./cart";
import { draftFromInterpreted, markChoiceRequired, toRequestItem } from "./draft";
import {
  listReducer,
  migrateCartToUnified,
  toDraftItems,
  unifiedLineCount,
  type UnifiedLine,
} from "./listStore";
import {
  appendEvent,
  emptyProfile,
  exportProfile,
  importProfile,
  indexedDbProfileStore,
  livePreferences,
  removePreference,
  setPreference,
  uuidv7,
  type Profile,
  type ProfileStore,
} from "./profile";
import {
  BASKET_HASH,
  catalogHash,
  LIST_HASH,
  navigate,
  parseRoute,
  replaceHash,
  useRoute,
  type Route,
} from "./router";
import {
  clearLastPlan,
  createSavedList,
  deleteSavedList,
  loadCart,
  loadDraft,
  loadLastPlan,
  loadLists,
  loadOptions,
  loadOrigin,
  renameSavedList,
  saveCart,
  saveDraft,
  saveLastPlan,
  saveLists,
  saveOptions,
  saveOrigin,
  upsertSavedList,
  type SavedList,
  type StoredOrigin,
} from "./storage";
import { AgentActions } from "./components/AgentActions";
import { BasketStep } from "./components/BasketStep";
import { CanonicalPage } from "./components/CanonicalPage";
import { CartDrawer, isLineResolved } from "./components/CartDrawer";
import { CatalogPage } from "./components/CatalogPage";
import { CHAINS } from "./components/ChainLogo";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { HomePage } from "./components/HomePage";
import { ListStep, type ListNotice } from "./components/ListStep";
import { type RouteOptions } from "./components/OriginStep";
import { PreferencesDialog } from "./components/PreferencesDialog";
import { ProductPage } from "./components/ProductPage";
import { SiteHeader } from "./components/SiteHeader";

type Overlay = "preferences" | "cart";

/** Identity of a screen for scroll bookkeeping: catalog URLs keep their filters. */
function routeKey(route: Route): string {
  switch (route.name) {
    case "catalog":
      return catalogHash(route.section, route.view, route.filters);
    case "canonical":
    case "product":
      return `${route.name}/${route.id}`;
    default:
      return route.name;
  }
}

/** Navigates only when the hash differs, so a no-op never adds a history entry. */
function goTo(hash: string): void {
  if (window.location.hash !== hash) navigate(hash);
}

/** Derives per-term habit counts from the local browser profile for the agent. */
function deriveHabitsFromProfile(profile: Profile): Record<string, HabitInput> {
  const habits: Record<string, HabitInput> = {};
  const explicitByTerm = new Map<string, { canonicalId: number | null; canonicalName: string }>();

  for (const pref of livePreferences(profile)) {
    if (pref.kind !== "term_choice" || pref.scope_kind !== "term") continue;
    const key = pref.scope_key.trim().toLowerCase();
    if (!key) continue;
    let canonicalId: number | null = null;
    let canonicalName = "";
    if (typeof pref.value === "string") {
      canonicalName = pref.value.trim();
    } else if (pref.value !== null && typeof pref.value === "object") {
      const record = pref.value as Record<string, unknown>;
      if (typeof record.canonical_id === "number") canonicalId = record.canonical_id;
      if (typeof record.canonical_name === "string") canonicalName = record.canonical_name.trim();
      else if (typeof record.name === "string") canonicalName = record.name.trim();
    }
    if (canonicalName) {
      explicitByTerm.set(key, { canonicalId, canonicalName });
    }
  }

  const grouped = new Map<
    string,
    {
      term: string;
      total: number;
      byCanonical: Map<number, { count: number; label: string }>;
    }
  >();

  for (const event of profile.events) {
    if (event.action === "removed" || event.canonical_id === null) continue;
    const key = event.term.trim().toLowerCase();
    if (!key) continue;
    let bucket = grouped.get(key);
    if (!bucket) {
      bucket = { term: event.term.trim(), total: 0, byCanonical: new Map() };
      grouped.set(key, bucket);
    }
    bucket.total += 1;
    const prev = bucket.byCanonical.get(event.canonical_id);
    const label =
      explicitByTerm.get(key)?.canonicalName ??
      (event.brand ? `${event.term.trim()} (${event.brand})` : event.term.trim());
    bucket.byCanonical.set(event.canonical_id, {
      count: (prev?.count ?? 0) + 1,
      label: prev?.label ?? label,
    });
  }

  for (const [key, bucket] of grouped.entries()) {
    let topId: number | null = null;
    let topCount = 0;
    let topLabel = bucket.term;
    for (const [canonicalId, info] of bucket.byCanonical.entries()) {
      if (info.count > topCount) {
        topId = canonicalId;
        topCount = info.count;
        topLabel = info.label;
      }
    }
    if (topId !== null && topCount > 0) {
      habits[key] = {
        term: bucket.term,
        canonical_id: topId,
        canonical_name: topLabel,
        count: topCount,
        total: bucket.total,
      };
    }
  }

  for (const [key, pref] of explicitByTerm.entries()) {
    if (!habits[key]) {
      habits[key] = {
        term: key,
        canonical_id: pref.canonicalId,
        canonical_name: pref.canonicalName,
        count: 1,
        total: 1,
      };
    }
  }

  return habits;
}

/** Extracts active dietary rule keys from the local browser profile. */
function deriveDietaryRulesFromProfile(profile: Profile): string[] {
  const rules: string[] = [];
  for (const pref of livePreferences(profile)) {
    if (pref.kind !== "dietary_rule") continue;
    const rule =
      typeof pref.value === "string" && pref.value.trim()
        ? pref.value.trim()
        : pref.scope_key.trim();
    if (rule && !rules.includes(rule)) rules.push(rule);
  }
  return rules;
}

function HealthFooter() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setHealth(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  return (
    <footer className="py-4 text-center text-[0.8125rem] text-[var(--ink-secondary)]" aria-live="polite">
      {failed
        ? "No se puede contactar con el servidor"
        : health
          ? `Servidor: ${health.status === "ok" ? "Funcionando" : "Con problemas"}`
          : "Comprobando…"}
    </footer>
  );
}

export default function App() {
  const route = useRoute();

  // One list for the catalog, the drawer and the list screen (M1). It starts from the saved
  // draft; a cart left by an older session is merged in once (see the effect that clears it).
  const [lines, dispatchList] = useReducer(listReducer, null, () =>
    migrateCartToUnified(loadCart(), loadDraft().draftItems),
  );
  // At most one overlay (cart drawer or preferences dialog) is open; it owns one history entry
  // so the browser Back button closes it instead of leaving the app.
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const overlayPushedRef = useRef(false);
  const cartOpen = overlay === "cart";
  const [dietaryRules, setDietaryRules] = useState<string[]>([]);
  // Shopper preferences (decision 0019): the chains to shop in (null = all) and the global
  // "Me da igual la marca" switch. The profile keeps them in the browser between sessions.
  const [chainFilter, setChainFilter] = useState<string[] | null>(null);
  const [anyBrand, setAnyBrand] = useState(false);
  const [store] = useState<ProfileStore>(() => indexedDbProfileStore());
  const profileRef = useRef<Profile>(emptyProfile());
  // Resolves once the saved profile is in `profileRef`; every change waits for it, so a tap
  // made while IndexedDB is still loading neither overwrites nor is overwritten by the load.
  const profileLoaded = useRef<Promise<void>>(Promise.resolve());
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogSections, setCatalogSections] = useState<CatalogSection[]>([]);
  const [catalogSectionsError, setCatalogSectionsError] = useState<string | null>(null);
  const [sectionsLoading, setSectionsLoading] = useState(true);
  const [activeChains, setActiveChains] = useState<ActiveChain[]>([]);
  const [chainsLoading, setChainsLoading] = useState(true);

  const [text, setText] = useState(() => loadDraft().draftText);
  const [listNotice, setListNotice] = useState<ListNotice | null>(null);
  const [degraded, setDegraded] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  const [lists, setLists] = useState<SavedList[]>(() => loadLists());

  const [origin, setOrigin] = useState<StoredOrigin | null>(() => loadOrigin());
  const [options, setOptions] = useState<RouteOptions>(() => loadOptions());
  const [originOpen, setOriginOpen] = useState(false);

  const [calculating, setCalculating] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  // The last plan survives a reload of the tab (F5 on #/cesta).
  const [initialPlan] = useState(() => loadLastPlan());
  const [recommendation, setRecommendation] = useState<Recommendation | null>(
    initialPlan?.recommendation ?? null,
  );
  const [agentRun, setAgentRun] = useState<AgentRunResponse | null>(initialPlan?.agentRun ?? null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [withoutAgent, setWithoutAgent] = useState(false);
  const busyRef = useRef(false);
  const lastRecommendationRequestRef = useRef<RecommendationRequest | null>(null);
  const baseRecommendationRef = useRef<Recommendation | null>(initialPlan?.recommendation ?? null);
  const agentAbortRef = useRef<AbortController | null>(null);
  const agentSeqRef = useRef(0);

  useEffect(() => {
    return () => {
      agentAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getSections(controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setCatalogSections(response.sections);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCatalogSectionsError(describeError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSectionsLoading(false);
      });
    getChains(controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setActiveChains(response.chains);
      })
      .catch(() => {
        // The home page falls back to the static chain list.
      })
      .finally(() => {
        if (!controller.signal.aborted) setChainsLoading(false);
      });
    return () => controller.abort();
  }, []);

  // Back button closes the open overlay: popstate without our overlay state means we left it.
  useEffect(() => {
    function onPopState() {
      if (window.history.state?.overlay) return;
      overlayPushedRef.current = false;
      setOverlay(null);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Scroll: a new screen starts at the top; coming back to a catalog URL restores its position.
  const scrollPositionsRef = useRef(new Map<string, number>());
  const lastCatalogHashRef = useRef<string | null>(null);
  const committedKeyRef = useRef<string | null>(null);
  const previousRouteNameRef = useRef<string | null>(null);
  const currentKey = routeKey(route);

  useEffect(() => {
    function onScroll() {
      const live = parseRoute(window.location.hash);
      const key = routeKey(live);
      // Ignore scrolls caused by the screen swap itself (hash already new, effect not yet run).
      if (live.name === "catalog" && key === committedKeyRef.current) {
        scrollPositionsRef.current.set(key, window.scrollY);
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const previousName = previousRouteNameRef.current;
    previousRouteNameRef.current = route.name;
    committedKeyRef.current = currentKey;
    if (route.name === "catalog") lastCatalogHashRef.current = currentKey;
    if (previousName === null) return;
    if (previousName === route.name) {
      // A new search or filter inside the catalog starts at the top of the new results.
      if (route.name === "catalog") window.scrollTo(0, 0);
      return;
    }
    const savedY = route.name === "catalog" ? scrollPositionsRef.current.get(currentKey) : undefined;
    if (savedY !== undefined) {
      requestAnimationFrame(() => window.scrollTo(0, savedY));
    } else {
      window.scrollTo(0, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKey]);

  // A reload never loses the list or the text being written (M12). The old cart was merged into
  // the draft on start, so it is emptied to avoid loading its lines twice.
  useEffect(() => {
    saveDraft({ draftText: text, draftItems: toDraftItems(lines) });
  }, [lines, text]);

  useEffect(() => {
    saveCart([]);
  }, []);

  // Load the saved profile once: the padlocks already travel with the cart, this restores
  // the switch and the chains.
  useEffect(() => {
    let cancelled = false;
    profileLoaded.current = store
      .load()
      .then((loaded) => {
        if (cancelled) return;
        profileRef.current = loaded;
        applyPreferences(loaded);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [store]);

  function applyPreferences(profile: Profile) {
    const live = livePreferences(profile);
    const chains = live
      .filter((preference) => preference.kind === "chain_include")
      .map((preference) => preference.scope_key);
    setChainFilter(chains.length === 0 ? null : chains);
    setAnyBrand(
      live.some((preference) => preference.kind === "any_brand" && preference.value === true),
    );
    setDietaryRules(deriveDietaryRulesFromProfile(profile));
  }

  /** Applies a change on top of the loaded profile, saves it and shows its preferences. */
  function commitProfile(change: (profile: Profile) => Profile): Promise<void> {
    return profileLoaded.current.then(() => {
      const next = change(profileRef.current);
      profileRef.current = next;
      applyPreferences(next);
      return store.save(next);
    });
  }

  function handleAnyBrandChange(value: boolean) {
    setAnyBrand(value);
    // The global switch lets every line that is not of shades accept any brand.
    if (value) {
      dispatchList({
        type: "replace",
        lines: lines.map((line) => (line.exactOnly ? line : { ...line, pinBrand: false })),
      });
    }
    const now = new Date();
    const key = { scope_kind: "global", scope_key: "any_brand", kind: "any_brand" } as const;
    commitProfile((profile) =>
      value
        ? setPreference(profile, { ...key, value: true }, now)
        : removePreference(profile, key, now),
    );
  }

  function handleChainFilterChange(chains: string[] | null) {
    setChainFilter(chains);
    const now = new Date();
    commitProfile((current) => {
      let profile = current;
      for (const { code } of CHAINS) {
        const key = { scope_kind: "chain", scope_key: code, kind: "chain_include" } as const;
        profile =
          chains !== null && chains.includes(code)
            ? setPreference(profile, { ...key, value: true }, now)
            : removePreference(profile, key, now);
      }
      return profile;
    });
  }

  /** The single brand control of a line (M2): pins its product or lets any brand do. */
  function handleSetPinBrand(id: string, pinBrand: boolean) {
    const line = lines.find((candidate) => candidate.id === id);
    dispatchList({ type: "setPinBrand", id, pinBrand });
    if (!line || line.exactOnly || line.categoryKey === null) return;

    const now = new Date();
    const key = { scope_kind: "category", scope_key: line.categoryKey, kind: "brand_pin" } as const;
    if (!pinBrand) {
      commitProfile((profile) => removePreference(profile, key, now));
      return;
    }

    commitProfile((profile) =>
      appendEvent(
        setPreference(
          profile,
          { ...key, value: { product_id: line.productId, brand: line.brand } },
          now,
        ),
        {
          id: uuidv7(now.getTime()),
          term: line.categoryName || line.text,
          action: "pinned",
          canonical_id: null,
          product_id: line.productId,
          brand: line.brand,
          chain: null,
          date: now.toISOString(),
        },
      ),
    );
  }

  function handleToggleDietaryRule(rule: string) {
    const now = new Date();
    const key = { scope_kind: "global", scope_key: rule, kind: "dietary_rule" } as const;
    const active = dietaryRules.includes(rule);
    void commitProfile((profile) =>
      active
        ? removePreference(profile, key, now)
        : setPreference(profile, { ...key, value: rule }, now),
    );
  }

  function openOverlay(kind: Overlay) {
    if (!overlayPushedRef.current) {
      window.history.pushState({ overlay: kind }, "");
      overlayPushedRef.current = true;
    }
    setOverlay(kind);
  }

  /** Closes through history.back() so the pushed entry is consumed (popstate then clears it). */
  function closeOverlay() {
    if (overlayPushedRef.current) {
      overlayPushedRef.current = false;
      window.history.back();
    } else {
      setOverlay(null);
    }
  }

  /** Closes the overlay because the app navigates anyway: no history.back(). */
  function dismissOverlayForNavigation() {
    overlayPushedRef.current = false;
    setOverlay(null);
  }

  function handleExportProfile() {
    const blob = new Blob([exportProfile(profileRef.current)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "smart-basket-preferencias.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function handleImportProfile(json: string): Promise<void> {
    return commitProfile((profile) => importProfile(json, profile));
  }

  function handleOriginChange(next: StoredOrigin) {
    setOrigin(next);
    saveOrigin(next);
    setCalcError(null);
  }

  function handleOptionsChange(patch: Partial<RouteOptions>) {
    setOptions((current) => {
      const updated = { ...current, ...patch };
      saveOptions(updated);
      return updated;
    });
    setCalcError(null);
  }

  function handleRemoveLine(id: string) {
    dispatchList({ type: "remove", id });
  }

  function handleUpdateLine(id: string, patch: Partial<Omit<UnifiedLine, "id">>) {
    dispatchList({ type: "update", id, patch });
  }

  function persistLists(next: SavedList[]) {
    setLists(next);
    saveLists(next);
  }

  function handleSaveList(name: string) {
    persistLists(upsertSavedList(lists, createSavedList(name, text, toDraftItems(lines))));
  }

  function handleRenameList(id: string, name: string) {
    persistLists(renameSavedList(lists, id, name));
  }

  function handleDeleteList(id: string) {
    persistLists(deleteSavedList(lists, id));
  }

  function handleLoadList(id: string) {
    const list = lists.find((candidate) => candidate.id === id);
    if (!list) return;
    dispatchList({ type: "replace", lines: migrateCartToUnified([], list.items) });
    setText(list.text);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setListNotice(null);
    dismissOverlayForNavigation();
    goTo(LIST_HASH);
  }

  /** Asks the list screen to scroll to what is missing before a plan can be calculated. */
  function raiseNotice(kind: ListNotice["kind"]) {
    setListNotice((previous) => ({ kind, tick: (previous?.tick ?? 0) + 1 }));
  }

  function cancelAgentRun() {
    agentSeqRef.current += 1;
    agentAbortRef.current?.abort();
    agentAbortRef.current = null;
    setAgentRun(null);
    setAgentLoading(false);
    setAgentError(null);
  }

  async function runAgentForPlan(
    requestPayload: RecommendationRequest,
    baseResult: Recommendation,
    useDefaultPolicy: boolean,
  ) {
    const seq = agentSeqRef.current + 1;
    agentSeqRef.current = seq;
    agentAbortRef.current?.abort();
    const controller = new AbortController();
    agentAbortRef.current = controller;
    setAgentLoading(true);
    try {
      await profileLoaded.current.catch(() => undefined);
      if (controller.signal.aborted || seq !== agentSeqRef.current) return;

      const habits = deriveHabitsFromProfile(profileRef.current);
      const dietaryRules = deriveDietaryRulesFromProfile(profileRef.current);
      const body: AgentRunRequest = {
        request: requestPayload,
        recommendation_id:
          baseResult.id !== null && baseResult.id !== undefined ? String(baseResult.id) : null,
        ...(Object.keys(habits).length > 0 ? { habits } : {}),
        ...(dietaryRules.length > 0 ? { dietary_rules: dietaryRules } : {}),
        ...(useDefaultPolicy ? { policy: "default" } : {}),
      };
      const run = await startAgentRun(body, controller.signal);
      if (controller.signal.aborted || seq !== agentSeqRef.current) return;
      setAgentRun(run);
      saveLastPlan({ recommendation: run.recommendation ?? baseResult, agentRun: run });
    } catch {
      // Fail gracefully: never break the basket if the agent endpoint is unavailable.
    } finally {
      if (seq === agentSeqRef.current) {
        setAgentLoading(false);
      }
    }
  }

  function buildRequest(
    targetLines: UnifiedLine[],
    targetOrigin: StoredOrigin,
    targetOptions: RouteOptions,
    isDegraded: boolean,
  ): RecommendationRequest {
    return {
      items: toDraftItems(targetLines).map(toRequestItem),
      origin: { lat: targetOrigin.lat, lon: targetOrigin.lon },
      mode: targetOptions.mode,
      max_stores: targetOptions.maxStores,
      priority_mode: targetOptions.priority,
      return_to_origin: targetOptions.returnToOrigin,
      degraded: isDegraded,
      chains: chainFilter,
    };
  }

  async function executeRecommendation(
    targetLines: UnifiedLine[],
    targetOrigin: StoredOrigin,
    targetOptions: RouteOptions,
    isDegraded: boolean = degraded,
  ) {
    busyRef.current = true;
    setCalculating(true);
    setCalcError(null);
    cancelAgentRun();
    try {
      const requestPayload = buildRequest(targetLines, targetOrigin, targetOptions, isDegraded);
      const result = await requestRecommendation(requestPayload);
      lastRecommendationRequestRef.current = requestPayload;
      baseRecommendationRef.current = result;
      setRecommendation(result);
      saveLastPlan({ recommendation: result, agentRun: null });
      dismissOverlayForNavigation();
      goTo(BASKET_HASH);
      void runAgentForPlan(requestPayload, result, withoutAgent);
    } catch (error) {
      if (isChoiceRequired(error)) {
        const { line_id: lineId, code, message } = error.detail;
        const marked = targetLines.map((line, index) => {
          if (index !== lineId) return line;
          const [changed] = migrateCartToUnified([], [markChoiceRequired(toDraftItems([line])[0], code)]);
          return { ...changed, packaging: line.packaging };
        });
        dispatchList({ type: "replace", lines: marked });
        setCalcError(message);
        raiseNotice("unresolved");
        dismissOverlayForNavigation();
        goTo(LIST_HASH);
      } else {
        setCalcError(describeError(error));
      }
    } finally {
      busyRef.current = false;
      setCalculating(false);
    }
  }

  async function recalculateWithLines(nextLines: UnifiedLine[], isDegraded: boolean = degraded) {
    if (busyRef.current || !origin) return;
    dispatchList({ type: "replace", lines: nextLines });
    await executeRecommendation(nextLines, origin, options, isDegraded);
  }

  /**
   * Interprets the free text and adds its lines to the list. Resolves to the list as it is
   * afterwards, or null when the text could not be interpreted.
   */
  async function addTextToList(): Promise<{ lines: UnifiedLine[]; degraded: boolean } | null> {
    const trimmed = text.trim();
    if (trimmed === "") return { lines, degraded };
    busyRef.current = true;
    setInterpreting(true);
    try {
      const response = await interpretText(trimmed);
      const added = migrateCartToUnified([], response.items.map(draftFromInterpreted));
      const next = added.reduce(
        (current, line) => listReducer(current, { type: "add", line }),
        lines,
      );
      dispatchList({ type: "replace", lines: next });
      setText("");
      setDegraded(response.degraded);
      return { lines: next, degraded: response.degraded };
    } catch (error) {
      setInterpretError(describeError(error));
      return null;
    } finally {
      busyRef.current = false;
      setInterpreting(false);
    }
  }

  async function handleAddText() {
    if (busyRef.current || text.trim() === "") return;
    setCalcError(null);
    setInterpretError(null);
    const result = await addTextToList();
    if (result && !result.lines.every(isLineResolved)) raiseNotice("unresolved");
  }

  async function handleCalculate() {
    if (busyRef.current) return;
    setCalcError(null);
    setInterpretError(null);

    const result = await addTextToList();
    if (!result || result.lines.length === 0) return;

    // Lines still vague or unknown: say so and take the user to the first one (A5).
    if (!result.lines.every(isLineResolved)) {
      raiseNotice("unresolved");
      return;
    }
    if (!origin) {
      setOriginOpen(true);
      raiseNotice("origin");
      return;
    }
    await recalculateWithLines(result.lines, result.degraded);
  }

  function handleNewList() {
    cancelAgentRun();
    lastRecommendationRequestRef.current = null;
    baseRecommendationRef.current = null;
    setText("");
    dispatchList({ type: "clear" });
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setListNotice(null);
    setRecommendation(null);
    clearLastPlan();
    goTo(LIST_HASH);
  }

  function handleSearch(query: string) {
    setCatalogQuery(query);
    dismissOverlayForNavigation();
    navigate(catalogHash(null, "product", { q: query }));
  }

  /** CatalogPage clears the query through here; the URL stays the source of truth. */
  function handleCatalogQueryChange(query: string) {
    setCatalogQuery(query);
    if (route.name === "catalog") {
      replaceHash(catalogHash(route.section, route.view, { ...route.filters, q: query }));
    }
  }

  /** A catalog line (specific or generic) in the shape of the unified list. */
  function addCatalogLine(cartLine: CartLine) {
    dispatchList({ type: "add", line: migrateCartToUnified([cartLine])[0] });
  }

  // With «Me da igual la marca» active, a product added from the catalog is not pinned.
  function handleAddSpecific(product: Product) {
    addCatalogLine(specificLine(product, anyBrand));
  }

  function handleAddCanonical(card: CanonicalCard) {
    addCatalogLine(canonicalLine(card));
  }

  function handleAddGeneric(product: Product) {
    const line = genericLine(product);
    if (line) addCatalogLine(line);
  }

  /** «Calcular plan» of the drawer: straight away when it can, otherwise to the list screen. */
  function handleCalculateFromDrawer() {
    if (lines.length === 0) return;
    dismissOverlayForNavigation();
    if (!lines.every(isLineResolved)) {
      raiseNotice("unresolved");
      goTo(LIST_HASH);
      return;
    }
    if (!origin) {
      setOriginOpen(true);
      raiseNotice("origin");
      goTo(LIST_HASH);
      return;
    }
    goTo(LIST_HASH);
    void recalculateWithLines(lines, false);
  }

  function handleEditList() {
    dismissOverlayForNavigation();
    goTo(LIST_HASH);
  }

  async function handleChangeProduct(lineId: number, productId: number) {
    const nextLines = lines.map((line, index) =>
      index === lineId ? { ...line, productId, pinBrand: true } : line,
    );
    await recalculateWithLines(nextLines);
  }

  async function handleApplyAnyBrand() {
    await recalculateWithLines(
      lines.map((line) =>
        line.productId !== null && !line.exactOnly ? { ...line, pinBrand: false } : line,
      ),
    );
  }

  /** The request of the plan on screen; after a reload it is rebuilt from the list. */
  function currentRequest(): RecommendationRequest | null {
    if (lastRecommendationRequestRef.current) return lastRecommendationRequestRef.current;
    if (!origin || lines.length === 0) return null;
    return buildRequest(lines, origin, options, degraded);
  }

  function handleToggleWithoutAgent(next: boolean) {
    setWithoutAgent(next);
    setAgentError(null);
    const requestPayload = currentRequest();
    if (requestPayload && baseRecommendationRef.current) {
      void runAgentForPlan(requestPayload, baseRecommendationRef.current, next);
    }
  }

  /** Sends the shopper's reply to the agent's pending question and shows the updated run. */
  async function handleAnswerAgentQuestion(answer: AgentAnswerRequest) {
    if (!agentRun) return;
    const runId = agentRun.run_id;

    const seq = agentSeqRef.current + 1;
    agentSeqRef.current = seq;
    agentAbortRef.current?.abort();
    const controller = new AbortController();
    agentAbortRef.current = controller;
    setAgentLoading(true);
    setAgentError(null);
    try {
      const run = await answerAgentRun(runId, answer, controller.signal);
      if (controller.signal.aborted || seq !== agentSeqRef.current) return;
      setAgentRun(run);
      if (run.recommendation) setRecommendation(run.recommendation);
      persistPlan(run);
    } catch (error) {
      if (!controller.signal.aborted && seq === agentSeqRef.current) {
        setAgentError(describeError(error));
      }
    } finally {
      if (seq === agentSeqRef.current) {
        setAgentLoading(false);
      }
    }
  }

  /** Keeps the plan the agent produced, so a reload of the tab shows it again. */
  function persistPlan(run: AgentRunResponse) {
    const plan = run.recommendation ?? baseRecommendationRef.current;
    if (plan) saveLastPlan({ recommendation: plan, agentRun: run });
  }

  /**
   * Asks the agent for a change in plain language («¿y si voy en coche?», «sin Lidl»…).
   * Resolves to true when the agent accepted the request, so the form clears its input.
   */
  async function handleRequestAgentChange(message: string): Promise<boolean> {
    const trimmed = message.trim();
    const requestPayload = currentRequest();
    const baseResult = baseRecommendationRef.current;
    if (trimmed === "" || agentLoading || !requestPayload || !baseResult) return false;

    const seq = agentSeqRef.current + 1;
    agentSeqRef.current = seq;
    agentAbortRef.current?.abort();
    const controller = new AbortController();
    agentAbortRef.current = controller;
    setAgentLoading(true);
    setAgentError(null);
    try {
      await profileLoaded.current.catch(() => undefined);
      if (controller.signal.aborted || seq !== agentSeqRef.current) return false;

      const habits = deriveHabitsFromProfile(profileRef.current);
      const dietaryRules = deriveDietaryRulesFromProfile(profileRef.current);
      const body: AgentRunRequest = {
        request: requestPayload,
        recommendation_id:
          baseResult.id !== null && baseResult.id !== undefined ? String(baseResult.id) : null,
        shopper_message: trimmed,
        ...(Object.keys(habits).length > 0 ? { habits } : {}),
        ...(dietaryRules.length > 0 ? { dietary_rules: dietaryRules } : {}),
        ...(withoutAgent ? { policy: "default" } : {}),
      };
      const run = await startAgentRun(body, controller.signal);
      if (controller.signal.aborted || seq !== agentSeqRef.current) return false;
      setAgentRun(run);
      if (run.recommendation) setRecommendation(run.recommendation);
      persistPlan(run);
      return true;
    } catch (error) {
      if (!controller.signal.aborted && seq === agentSeqRef.current) {
        setAgentError(describeError(error));
      }
      return false;
    } finally {
      if (seq === agentSeqRef.current) {
        setAgentLoading(false);
      }
    }
  }

  const displayedRecommendation = agentRun?.recommendation ?? recommendation;

  // On the catalog the URL owns the query; elsewhere the last submitted search is kept.
  const headerQuery = route.name === "catalog" ? route.filters.q : catalogQuery;

  const flow = (
    <main className="mx-auto grid min-w-0 max-w-xl gap-4 px-4 pt-4 pb-12 text-[var(--ink-primary)]">
      {route.name === "list" && (
        <ListStep
          lines={lines}
          anyBrand={anyBrand}
          onAnyBrandChange={handleAnyBrandChange}
          onRemoveLine={handleRemoveLine}
          onUpdateLine={handleUpdateLine}
          onSetPinBrand={handleSetPinBrand}
          onChooseInCatalog={handleSearch}
          text={text}
          onTextChange={setText}
          onAddText={handleAddText}
          onCalculate={handleCalculate}
          calculating={calculating}
          interpreting={interpreting}
          interpretError={interpretError}
          calcError={calcError}
          degraded={degraded}
          notice={listNotice}
          lists={lists}
          onSaveList={handleSaveList}
          onLoadList={handleLoadList}
          onRenameList={handleRenameList}
          onDeleteList={handleDeleteList}
          origin={origin}
          onOriginChange={handleOriginChange}
          options={options}
          onOptionsChange={handleOptionsChange}
          originOpen={originOpen}
          onToggleOriginOpen={() => setOriginOpen((prev) => !prev)}
        />
      )}

      {route.name === "basket" && !displayedRecommendation && (
        <section className="grid gap-3 py-8">
          <p className="text-[0.9375rem] text-[var(--ink-primary)]">
            Aún no has calculado un plan de compra. Ve a tu lista para calcularlo.
          </p>
          <div>
            <a
              href={LIST_HASH}
              className="inline-flex min-h-11 items-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)]"
            >
              Ir a tu lista
            </a>
          </div>
        </section>
      )}

      {route.name === "basket" && displayedRecommendation && (
        <BasketStep
          recommendation={displayedRecommendation}
          origin={origin}
          calculating={calculating}
          calcError={calcError}
          agentRun={agentRun}
          agentLoading={agentLoading}
          withoutAgent={withoutAgent}
          onToggleWithoutAgent={handleToggleWithoutAgent}
          agentSlot={
            <AgentActions
              agentRun={agentRun}
              loading={agentLoading}
              withoutAgent={withoutAgent}
              error={agentError}
              onAnswerQuestion={handleAnswerAgentQuestion}
              onRequestChange={handleRequestAgentChange}
            />
          }
          onBack={() => goTo(LIST_HASH)}
          onNewList={handleNewList}
          onApplyAnyBrand={handleApplyAnyBrand}
          onChangeProduct={handleChangeProduct}
        />
      )}

      <HealthFooter />
    </main>
  );

  return (
    <>
      <SiteHeader
        cartCount={unifiedLineCount(lines)}
        query={headerQuery}
        onSearch={handleSearch}
        onOpenCart={() => openOverlay("cart")}
        onOpenPreferences={() => openOverlay("preferences")}
      />

      <div className="min-h-screen bg-[var(--surface-canvas)] text-[var(--ink-primary)]">
        <ErrorBoundary key={route.name}>
          {route.name === "home" && (
            <HomePage
              sections={catalogSections}
              sectionsError={catalogSectionsError}
              sectionsLoading={sectionsLoading}
              chains={activeChains}
              chainsLoading={chainsLoading}
              onSearch={handleSearch}
              onWriteList={() => undefined}
            />
          )}

          {route.name === "catalog" && (
            <CatalogPage
              section={route.section}
              view={route.view}
              sections={catalogSections}
              sectionsError={catalogSectionsError}
              query={headerQuery}
              onQueryChange={handleCatalogQueryChange}
              onAdd={handleAddSpecific}
              onAddCanonical={handleAddCanonical}
            />
          )}

          {route.name === "canonical" && (
            <CanonicalPage
              id={route.id}
              onAddGeneric={handleAddCanonical}
              onAddSpecific={handleAddSpecific}
            />
          )}

          {route.name === "product" && (
            <ProductPage
              id={route.id}
              onAddSpecific={handleAddSpecific}
              onAddGeneric={handleAddGeneric}
            />
          )}

          {(route.name === "list" || route.name === "basket") && flow}
        </ErrorBoundary>
      </div>

      <PreferencesDialog
        open={overlay === "preferences"}
        onClose={closeOverlay}
        dietaryRules={dietaryRules}
        onToggleDietaryRule={handleToggleDietaryRule}
        onExportProfile={handleExportProfile}
        onImportProfile={handleImportProfile}
      />

      <CartDrawer
        open={cartOpen}
        lines={lines}
        anyBrand={anyBrand}
        chainFilter={chainFilter}
        onClose={closeOverlay}
        onQuantityChange={(id, quantity) => dispatchList({ type: "setQuantity", id, quantity })}
        onSetPinBrand={handleSetPinBrand}
        onAnyBrandChange={handleAnyBrandChange}
        onChainFilterChange={handleChainFilterChange}
        onRemove={handleRemoveLine}
        lists={lists}
        onSaveList={handleSaveList}
        onLoadList={handleLoadList}
        onRenameList={handleRenameList}
        onDeleteList={handleDeleteList}
        onEditList={handleEditList}
        onCalculate={handleCalculateFromDrawer}
      />
    </>
  );
}
