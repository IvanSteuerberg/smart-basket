import { useEffect, useReducer, useRef, useState } from "react";
import {
  describeError,
  getHealth,
  getSections,
  interpretText,
  isVagueLine,
  requestRecommendation,
  type CatalogSection,
  type Health,
  type Product,
  type Recommendation,
} from "./api";
import {
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
import { CartDrawer } from "./components/CartDrawer";
import { CatalogPage } from "./components/CatalogPage";
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

  const [chainFilter, setChainFilter] = useState<string[] | null>(null);
  // Set by the cart's chain filter.
  void setChainFilter;

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
    dispatch({ type: "add", line: specificLine(product) });
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
            sections={catalogSections}
            sectionsError={catalogSectionsError}
            query={catalogQuery}
            onQueryChange={setCatalogQuery}
            onAdd={handleAddSpecific}
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
        onClose={() => setCartOpen(false)}
        onQuantityChange={(id, quantity) => dispatch({ type: "setQuantity", id, quantity })}
        onRemove={(id) => dispatch({ type: "remove", id })}
        onSaveList={handleSaveCartList}
        onCalculate={handleCalculateFromCart}
      />
    </>
  );
}
