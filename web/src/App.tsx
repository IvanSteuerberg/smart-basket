import { useEffect, useReducer, useRef, useState } from "react";
import {
  describeError,
  getHealth,
  getSections,
  interpretText,
  isVagueLine,
  requestRecommendation,
  type Accept,
  type CanonicalCard,
  type CatalogSection,
  type Health,
  type Product,
  type Recommendation,
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
  const busyRef = useRef(false);

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

  function handleQuantityChange(id: string, quantity: string) {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, quantity } : item)),
    );
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

  async function executeRecommendation(
    targetItems: DraftItem[],
    targetOrigin: StoredOrigin,
    targetOptions: RouteOptions,
  ) {
    busyRef.current = true;
    setCalculating(true);
    setCalcError(null);
    try {
      const result = await requestRecommendation({
        items: targetItems.map(toRequestItem),
        origin: { lat: targetOrigin.lat, lon: targetOrigin.lon },
        mode: targetOptions.mode,
        max_stores: targetOptions.maxStores,
        priority_mode: targetOptions.priority,
        return_to_origin: targetOptions.returnToOrigin,
        degraded,
        chains: chainFilter,
      });
      setRecommendation(result);
      setStep("basket");
    } catch (error) {
      if (isVagueLine(error)) {
        const lineId = error.detail.line_id;
        setItems((current) =>
          current.map((item, index) =>
            index === lineId
              ? { ...item, categoryKey: null, productId: null, options: [] }
              : item,
          ),
        );
        setCalcError(error.detail.message);
        setStep("list");
      } else {
        setCalcError(describeError(error));
      }
    } finally {
      busyRef.current = false;
      setCalculating(false);
    }
  }

  async function handleCalculate() {
    if (busyRef.current) return;
    setCalcError(null);
    setInterpretError(null);

    let currentItems = items;
    const trimmed = text.trim();

    if (trimmed !== "") {
      busyRef.current = true;
      setInterpreting(true);
      try {
        const response = await interpretText(trimmed);
        const newItems = response.items.map(draftFromInterpreted);
        currentItems = [...items, ...newItems];
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
      await executeRecommendation(currentItems, origin, options);
    }
  }

  function handleNewList() {
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
    setText("");
    setItems(cartItems);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setRecommendation(null);
    setCartOpen(false);
    navigate(LIST_HASH);

    if (origin && allResolved(cartItems)) {
      executeRecommendation(cartItems, origin, options);
    } else {
      setStep("list");
      if (!origin) {
        setOriginOpen(true);
      }
    }
  }

  async function handleChangeProduct(lineId: number, productId: number) {
    if (!origin) return;
    const nextItems = items.map((item, index) =>
      index === lineId
        ? { ...item, productId, accept: "exact" as const }
        : item,
    );
    setItems(nextItems);
    await executeRecommendation(nextItems, origin, options);
  }

  async function handleApplyAnyBrand() {
    if (!origin) return;
    const nextItems = applyAnyBrand(items);
    setItems(nextItems);
    await executeRecommendation(nextItems, origin, options);
  }

  const flow = (
    <main className="mx-auto grid max-w-xl gap-4 px-4 pt-4 pb-12 text-slate-900">
      {step === "list" && (
        <ListStep
          items={items}
          onQuantityChange={handleQuantityChange}
          onRemoveItem={handleRemoveItem}
          onUpdateItem={handleUpdateItem}
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

      {step === "basket" && recommendation && (
        <BasketStep
          recommendation={recommendation}
          origin={origin}
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
