import { useEffect, useState } from "react";
import {
  describeError,
  getCategories,
  getHealth,
  interpretText,
  requestRecommendation,
  type Health,
  type LatLon,
  type Recommendation,
  type SearchResult,
  type SectionCategory,
} from "./api";
import { draftFromInterpreted, toRequestItem, type DraftItem } from "./draft";
import { createSavedList, loadLists, saveLists, upsertSavedList, type SavedList } from "./storage";
import { BasketStep } from "./components/BasketStep";
import { ListStep } from "./components/ListStep";
import { DEFAULT_OPTIONS, OriginStep, type RouteOptions } from "./components/OriginStep";
import { ReviewStep } from "./components/ReviewStep";

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
  const [step, setStep] = useState<Step>("list");

  const [text, setText] = useState("");
  const [addedItems, setAddedItems] = useState<DraftItem[]>([]);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [degraded, setDegraded] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  const [sections, setSections] = useState<SectionCategory[]>([]);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);

  const [lists, setLists] = useState<SavedList[]>(() => loadLists());

  const [origin, setOrigin] = useState<LatLon | null>(null);
  const [options, setOptions] = useState<RouteOptions>(DEFAULT_OPTIONS);
  const [calculating, setCalculating] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
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

  async function handleInterpret() {
    setInterpretError(null);
    const trimmed = text.trim();
    if (trimmed === "") {
      if (addedItems.length === 0) return;
      setItems(addedItems.map((item) => ({ ...item })));
      setDegraded(false);
      setStep("review");
      return;
    }
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
    if (!origin) return;
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

  return (
    <main className="page">
      <header className="hero">
        <img src="/favicon.svg" alt="" width={48} height={48} />
        <div>
          <h1>Smart Basket</h1>
          <p>Tu cesta de la compra más barata en León, con el menor tiempo de desplazamiento.</p>
        </div>
      </header>

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
}
