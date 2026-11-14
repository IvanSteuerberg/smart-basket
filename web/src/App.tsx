import { useEffect, useReducer, useRef, useState } from "react";
import {
  describeError,
  getCategories,
  getHealth,
  getSections,
  interpretText,
  requestRecommendation,
  type CatalogSection,
  type Health,
  type LatLon,
  type Product,
  type Recommendation,
  type SearchResult,
  type SectionCategory,
} from "./api";
import {
  cartItemCount,
  cartReducer,
  draftItemsFromCart,
  genericLine,
  specificLine,
} from "./cart";
import { draftFromInterpreted, toRequestItem, type DraftItem } from "./draft";
import { CATALOG_HASH, LIST_HASH, navigate, useRoute } from "./router";
import {
  createSavedList,
  loadCart,
  loadLists,
  saveCart,
  saveLists,
  upsertSavedList,
  type SavedList,
} from "./storage";
import { BasketStep } from "./components/BasketStep";
import { CartDrawer } from "./components/CartDrawer";
import { CatalogPage } from "./components/CatalogPage";
import { HomePage } from "./components/HomePage";
import { ListStep } from "./components/ListStep";
import { DEFAULT_OPTIONS, OriginStep, type RouteOptions } from "./components/OriginStep";
import { ProductPage } from "./components/ProductPage";
import { ReviewStep } from "./components/ReviewStep";
import { SiteHeader } from "./components/SiteHeader";

type Step = "list" | "review" | "origin" | "basket";

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
    <footer className="footer-status" aria-live="polite">
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
  const [addedItems, setAddedItems] = useState<DraftItem[]>([]);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [degraded, setDegraded] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const interpretingRef = useRef(false);

  const [sections, setSections] = useState<SectionCategory[]>([]);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);

  const [lists, setLists] = useState<SavedList[]>(() => loadLists());

  const [origin, setOrigin] = useState<LatLon | null>(null);
  const [options, setOptions] = useState<RouteOptions>(DEFAULT_OPTIONS);
  const [calculating, setCalculating] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  const calculatingRef = useRef(false);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getCategories(controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setSections(response.sections);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCategoriesError(describeError(error));
      });
    return () => controller.abort();
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

  async function handleInterpret() {
    if (interpretingRef.current) return;
    setInterpretError(null);
    const trimmed = text.trim();
    if (trimmed === "") {
      if (addedItems.length === 0) return;
      setItems(addedItems.map((item) => ({ ...item })));
      setDegraded(false);
      setStep("review");
      return;
    }
    interpretingRef.current = true;
    setInterpreting(true);
    try {
      const response = await interpretText(trimmed);
      setItems([
        ...response.items.map(draftFromInterpreted),
        ...addedItems.map((item) => ({ ...item })),
      ]);
      setDegraded(response.degraded);
      setStep("review");
    } catch (error) {
      setInterpretError(describeError(error));
    } finally {
      interpretingRef.current = false;
      setInterpreting(false);
    }
  }

  function handleAddItem(item: DraftItem) {
    setAddedItems((current) => [...current, item]);
  }

  function handleRemoveAddedItem(id: string) {
    setAddedItems((current) => current.filter((item) => item.id !== id));
  }

  function handleChangeItem(id: string, patch: Partial<DraftItem>) {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }

  function handlePickCategory(id: string, result: SearchResult) {
    handleChangeItem(id, { categoryKey: result.key, categoryName: result.name });
  }

  function handleRemoveItem(id: string) {
    setItems((current) => current.filter((item) => item.id !== id));
  }

  function handleSaveList(name: string) {
    const next = upsertSavedList(lists, createSavedList(name, text, addedItems));
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
    setAddedItems(list.items);
    setItems([]);
    setDegraded(false);
    setInterpretError(null);
    setStep("list");
  }

  function handleOriginChange(next: LatLon) {
    setOrigin(next);
    setCalcError(null);
  }

  function handleOptionsChange(patch: Partial<RouteOptions>) {
    setOptions((current) => ({ ...current, ...patch }));
    setCalcError(null);
  }

  async function handleCalculate() {
    if (calculatingRef.current) return;
    if (!origin) return;
    calculatingRef.current = true;
    setCalculating(true);
    setCalcError(null);
    try {
      const result = await requestRecommendation({
        items: items.map(toRequestItem),
        origin,
        mode: options.mode,
        max_stores: options.maxStores,
        priority_mode: options.priority,
        return_to_origin: options.returnToOrigin,
        degraded,
      });
      setRecommendation(result);
      setStep("basket");
    } catch (error) {
      setCalcError(describeError(error));
    } finally {
      calculatingRef.current = false;
      setCalculating(false);
    }
  }

  function handleNewList() {
    setText("");
    setAddedItems([]);
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

  /** The cart becomes the list: straight to the origin step, no review. */
  function handleCalculateFromCart() {
    const cartItems = draftItemsFromCart(cart);
    if (cartItems.length === 0) return;
    setText("");
    setAddedItems([]);
    setItems(cartItems);
    setDegraded(false);
    setInterpretError(null);
    setCalcError(null);
    setRecommendation(null);
    setStep("origin");
    setCartOpen(false);
    navigate(LIST_HASH);
  }

  const flow = (
    <main className="page">
      {step === "list" && (
        <ListStep
          text={text}
          onTextChange={setText}
          addedItems={addedItems}
          onAddItem={handleAddItem}
          onRemoveItem={handleRemoveAddedItem}
          sections={sections}
          categoriesError={categoriesError}
          onInterpret={handleInterpret}
          interpreting={interpreting}
          interpretError={interpretError}
          lists={lists}
          onSaveList={handleSaveList}
          onLoadList={handleLoadList}
        />
      )}

      {step === "review" && (
        <ReviewStep
          items={items}
          degraded={degraded}
          onChange={handleChangeItem}
          onPickCategory={handlePickCategory}
          onRemove={handleRemoveItem}
          onBack={() => setStep("list")}
          onContinue={() => setStep("origin")}
        />
      )}

      {step === "origin" && (
        <OriginStep
          origin={origin}
          onOriginChange={handleOriginChange}
          options={options}
          onOptionsChange={handleOptionsChange}
          onCalculate={handleCalculate}
          onBack={() => setStep("review")}
          calculating={calculating}
          error={calcError}
        />
      )}

      {step === "basket" && recommendation && (
        <BasketStep
          recommendation={recommendation}
          origin={origin}
          onBack={() => setStep("origin")}
          onNewList={handleNewList}
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
