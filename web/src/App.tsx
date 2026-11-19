import { useEffect, useReducer, useRef, useState } from "react";
import {
  answerAgentRun,
  describeError,
  getHealth,
  getSections,
  interpretText,
  isChoiceRequired,
  requestRecommendation,
  startAgentRun,
  type Accept,
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
import {
  canonicalLine,
  cartItemCount,
  cartReducer,
  draftItemsFromCart,
  genericLine,
  specificLine,
} from "./cart";
import {
  allResolved,
  applyAnyBrand,
  draftFromInterpreted,
  markChoiceRequired,
  toRequestItem,
  type DraftItem,
} from "./draft";
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
import { CATALOG_HASH, LIST_HASH, navigate, useRoute } from "./router";
import {
  createSavedList,
  loadCart,
  loadLists,
  loadOptions,
  loadOrigin,
  saveCart,
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
import { CartDrawer } from "./components/CartDrawer";
import { CatalogPage } from "./components/CatalogPage";
import { CHAINS } from "./components/ChainLogo";
import { HomePage } from "./components/HomePage";
import { ListStep } from "./components/ListStep";
import { type RouteOptions } from "./components/OriginStep";
import { ProductPage } from "./components/ProductPage";
import { SiteHeader } from "./components/SiteHeader";

type Step = "list" | "basket";

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
    <footer className="py-4 text-center text-xs text-stone-500" aria-live="polite">
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

  const [cart, dispatch] = useReducer(cartReducer, null, () => loadCart());
  const [cartOpen, setCartOpen] = useState(false);
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

  const [step, setStep] = useState<Step>("list");

  const [text, setText] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]);
  const [degraded, setDegraded] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  const [lists, setLists] = useState<SavedList[]>(() => loadLists());

  const [origin, setOrigin] = useState<StoredOrigin | null>(() => loadOrigin());
  const [options, setOptions] = useState<RouteOptions>(() => loadOptions());
  const [originOpen, setOriginOpen] = useState(false);

  const [calculating, setCalculating] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [agentRun, setAgentRun] = useState<AgentRunResponse | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [withoutAgent, setWithoutAgent] = useState(false);
  const busyRef = useRef(false);
  const lastRecommendationRequestRef = useRef<RecommendationRequest | null>(null);
  const baseRecommendationRef = useRef<Recommendation | null>(null);
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
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    saveCart(cart);
  }, [cart]);

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
  }

  /** Applies a change on top of the loaded profile, saves it and shows its preferences. */
  function commitProfile(change: (profile: Profile) => Profile) {
    void profileLoaded.current.then(() => {
      const next = change(profileRef.current);
      profileRef.current = next;
      applyPreferences(next);
      return store.save(next);
    });
  }

  function handleAnyBrandChange(value: boolean) {
    setAnyBrand(value);
    if (value) dispatch({ type: "anyBrand" });
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

  function handleAcceptChange(id: string, accept: Accept) {
    dispatch({ type: "setAccept", id, accept });
  }

  function handleToggleLock(id: string) {
    const line = cart.find((candidate) => candidate.id === id);
    dispatch({ type: "toggleLock", id });
    if (!line || line.category_key === null) return;

    const now = new Date();
    const key = { scope_kind: "category", scope_key: line.category_key, kind: "brand_pin" } as const;
    if (line.locked) {
      commitProfile((profile) => removePreference(profile, key, now));
      return;
    }

    commitProfile((profile) =>
      appendEvent(
        setPreference(
          profile,
          { ...key, value: { product_id: line.product_id, brand: line.brand } },
          now,
        ),
        {
          id: uuidv7(now.getTime()),
          term: line.category_name ?? line.name,
          action: "pinned",
          canonical_id: null,
          product_id: line.product_id,
          brand: line.brand,
          chain: null,
          date: now.toISOString(),
        },
      ),
    );
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

  function handleImportProfile(json: string) {
    commitProfile((profile) => importProfile(json, profile));
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

  function handleRemoveItem(id: string) {
    setItems((current) => current.filter((item) => item.id !== id));
  }

  function handleUpdateItem(id: string, patch: Partial<DraftItem>) {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }

  function handleSaveList(name: string) {
    const next = upsertSavedList(lists, createSavedList(name, text, items));
    setLists(next);
    saveLists(next);
  }

  function handleSaveCartList(name: string) {
    const cartItems = draftItemsFromCart(cart);
    const cartText = cartItems.map((item) => item.text).join("\n");
    const next = upsertSavedList(lists, createSavedList(name, cartText, cartItems));
    setLists(next);
    saveLists(next);
  }

  function handleLoadList(id: string) {
    const list = lists.find((candidate) => candidate.id === id);
    if (!list) return;
    setText(list.text);
    setItems(list.items);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setStep("list");
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
    } catch {
      // Fail gracefully: never break the basket if the agent endpoint is unavailable.
    } finally {
      if (seq === agentSeqRef.current) {
        setAgentLoading(false);
      }
    }
  }

  async function executeRecommendation(
    targetItems: DraftItem[],
    targetOrigin: StoredOrigin,
    targetOptions: RouteOptions,
    isDegraded: boolean = degraded,
  ) {
    busyRef.current = true;
    setCalculating(true);
    setCalcError(null);
    cancelAgentRun();
    try {
      const requestPayload: RecommendationRequest = {
        items: targetItems.map(toRequestItem),
        origin: { lat: targetOrigin.lat, lon: targetOrigin.lon },
        mode: targetOptions.mode,
        max_stores: targetOptions.maxStores,
        priority_mode: targetOptions.priority,
        return_to_origin: targetOptions.returnToOrigin,
        degraded: isDegraded,
        chains: chainFilter,
      };
      const result = await requestRecommendation(requestPayload);
      lastRecommendationRequestRef.current = requestPayload;
      baseRecommendationRef.current = result;
      setRecommendation(result);
      setStep("basket");
      void runAgentForPlan(requestPayload, result, withoutAgent);
    } catch (error) {
      if (isChoiceRequired(error)) {
        const { line_id: lineId, code, message } = error.detail;
        setItems((current) =>
          current.map((item, index) => (index === lineId ? markChoiceRequired(item, code) : item)),
        );
        setCalcError(message);
        setStep("list");
      } else {
        setCalcError(describeError(error));
      }
    } finally {
      busyRef.current = false;
      setCalculating(false);
    }
  }

  async function recalculateWithItems(
    nextItems: DraftItem[],
    isDegraded: boolean = degraded,
  ) {
    if (busyRef.current || !origin) return;
    setItems(nextItems);
    await executeRecommendation(nextItems, origin, options, isDegraded);
  }

  async function handleCalculate() {
    if (busyRef.current) return;
    setCalcError(null);
    setInterpretError(null);

    let currentItems = items;
    let currentDegraded = degraded;
    const trimmed = text.trim();

    if (trimmed !== "") {
      busyRef.current = true;
      setInterpreting(true);
      try {
        const response = await interpretText(trimmed);
        const newItems = response.items.map(draftFromInterpreted);
        currentItems = [...items, ...newItems];
        currentDegraded = response.degraded;
        setItems(currentItems);
        setText("");
        setDegraded(response.degraded);
      } catch (error) {
        setInterpretError(describeError(error));
        busyRef.current = false;
        setInterpreting(false);
        return;
      } finally {
        busyRef.current = false;
        setInterpreting(false);
      }
    }

    if (currentItems.length === 0) return;

    if (!origin) {
      setOriginOpen(true);
    }

    if (allResolved(currentItems) && origin) {
      await recalculateWithItems(currentItems, currentDegraded);
    }
  }

  function handleNewList() {
    cancelAgentRun();
    lastRecommendationRequestRef.current = null;
    baseRecommendationRef.current = null;
    setText("");
    setItems([]);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setRecommendation(null);
    setStep("list");
  }

  function handleSearch(query: string) {
    setCatalogQuery(query);
    setCartOpen(false);
    navigate(CATALOG_HASH);
  }

  function handleAddSpecific(product: Product) {
    dispatch({ type: "add", line: specificLine(product, anyBrand) });
  }

  function handleAddCanonical(card: CanonicalCard) {
    dispatch({ type: "add", line: canonicalLine(card) });
  }

  function handleAddGeneric(product: Product) {
    const line = genericLine(product);
    if (line) dispatch({ type: "add", line });
  }

  function handleCalculateFromCart() {
    const cartItems = draftItemsFromCart(cart);
    if (cartItems.length === 0) return;
    cancelAgentRun();
    lastRecommendationRequestRef.current = null;
    baseRecommendationRef.current = null;
    setText("");
    setItems(cartItems);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setRecommendation(null);
    setStep("list");
    setCartOpen(false);
    navigate(LIST_HASH);

    if (origin && allResolved(cartItems)) {
      void recalculateWithItems(cartItems, false);
    } else {
      if (!origin) {
        setOriginOpen(true);
      }
    }
  }

  async function handleChangeProduct(lineId: number, productId: number) {
    const nextItems = items.map((item, index) =>
      index === lineId
        ? { ...item, productId, accept: "exact" as const }
        : item,
    );
    await recalculateWithItems(nextItems);
  }

  async function handleApplyAnyBrand() {
    await recalculateWithItems(applyAnyBrand(items));
  }

  function handleToggleWithoutAgent(next: boolean) {
    setWithoutAgent(next);
    setAgentError(null);
    if (lastRecommendationRequestRef.current && baseRecommendationRef.current) {
      void runAgentForPlan(
        lastRecommendationRequestRef.current,
        baseRecommendationRef.current,
        next,
      );
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

  /**
   * Asks the agent for a change in plain language («¿y si voy en coche?», «sin Lidl»…).
   * Resolves to true when the agent accepted the request, so the form clears its input.
   */
  async function handleRequestAgentChange(message: string): Promise<boolean> {
    const trimmed = message.trim();
    const requestPayload = lastRecommendationRequestRef.current;
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

  const flow = (
    <main className="mx-auto grid max-w-xl gap-4 px-4 pt-4 pb-12 text-slate-900">
      {step === "list" && (
        <ListStep
          items={items}
          onRemoveItem={handleRemoveItem}
          onUpdateItem={handleUpdateItem}
          onChooseInCatalog={handleSearch}
          text={text}
          onTextChange={setText}
          onCalculate={handleCalculate}
          calculating={calculating}
          interpreting={interpreting}
          interpretError={interpretError}
          calcError={calcError}
          degraded={degraded}
          lists={lists}
          onSaveList={handleSaveList}
          onLoadList={handleLoadList}
          origin={origin}
          onOriginChange={handleOriginChange}
          options={options}
          onOptionsChange={handleOptionsChange}
          originOpen={originOpen}
          onToggleOriginOpen={() => setOriginOpen((prev) => !prev)}
        />
      )}

      {step === "basket" && displayedRecommendation && (
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
          onBack={() => setStep("list")}
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
        cartCount={cartItemCount(cart)}
        query={catalogQuery}
        onSearch={handleSearch}
        onOpenCart={() => setCartOpen(true)}
      />

      {route.name === "home" && (
        <div className="min-h-screen bg-stone-50 text-slate-900">
          <HomePage
            sections={catalogSections}
            sectionsError={catalogSectionsError}
            onSearch={handleSearch}
            onWriteList={() => setStep("list")}
          />
        </div>
      )}

      {route.name === "catalog" && (
        <div className="min-h-screen bg-stone-50 text-slate-900">
          <CatalogPage
            section={route.section}
            view={route.view}
            sections={catalogSections}
            sectionsError={catalogSectionsError}
            query={catalogQuery}
            onQueryChange={setCatalogQuery}
            onAdd={handleAddSpecific}
            onAddCanonical={handleAddCanonical}
          />
        </div>
      )}

      {route.name === "canonical" && (
        <div className="min-h-screen bg-stone-50 text-slate-900">
          <CanonicalPage
            id={route.id}
            onAddGeneric={handleAddCanonical}
            onAddSpecific={handleAddSpecific}
          />
        </div>
      )}

      {route.name === "product" && (
        <div className="min-h-screen bg-stone-50 text-slate-900">
          <ProductPage
            id={route.id}
            onAddSpecific={handleAddSpecific}
            onAddGeneric={handleAddGeneric}
          />
        </div>
      )}

      {route.name === "list" && flow}

      <CartDrawer
        open={cartOpen}
        lines={cart}
        anyBrand={anyBrand}
        chainFilter={chainFilter}
        onClose={() => setCartOpen(false)}
        onQuantityChange={(id, quantity) => dispatch({ type: "setQuantity", id, quantity })}
        onAcceptChange={handleAcceptChange}
        onToggleLock={handleToggleLock}
        onAnyBrandChange={handleAnyBrandChange}
        onChainFilterChange={handleChainFilterChange}
        onRemove={(id) => dispatch({ type: "remove", id })}
        onSaveList={handleSaveCartList}
        onCalculate={handleCalculateFromCart}
        onExportProfile={handleExportProfile}
        onImportProfile={handleImportProfile}
      />
    </>
  );
}
