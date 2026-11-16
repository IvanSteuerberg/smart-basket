import {
  searchProducts,
  type InterpretOption,
  type SearchResult,
} from "../api";
import {
  chooseOption,
  isResolved,
  type DraftItem,
} from "../draft";
import { formatUnitPrice } from "../format";
import { askListName } from "../listName";
import { CATALOG_HASH } from "../router";
import type { SavedList, StoredOrigin } from "../storage";
import { OriginStep, type RouteOptions } from "./OriginStep";
import { EXACT_ONLY_PICK, exactOnlyLine } from "../texts";
import { ProductImage } from "./ProductImage";
import { SearchBox } from "./SearchBox";

const TEXTAREA_PLACEHOLDER =
  "Escribe tu lista, una cosa por línea: 2 l de leche, pan de molde, pollo…";

export interface ListStepProps {
  items: DraftItem[];
  onRemoveItem: (id: string) => void;
  onUpdateItem: (id: string, patch: Partial<DraftItem>) => void;
  /** Opens the catalog searching for the text of a line that needs a concrete product. */
  onChooseInCatalog: (query: string) => void;

  text: string;
  onTextChange: (value: string) => void;
  onCalculate: () => void;
  calculating: boolean;
  interpreting: boolean;
  interpretError: string | null;
  calcError: string | null;
  degraded: boolean;

  lists: SavedList[];
  onSaveList: (name: string) => void;
  onLoadList: (id: string) => void;

  origin: StoredOrigin | null;
  onOriginChange: (origin: StoredOrigin) => void;
  options: RouteOptions;
  onOptionsChange: (patch: Partial<RouteOptions>) => void;
  originOpen: boolean;
  onToggleOriginOpen: () => void;
}

export function ListStep({
  items,
  onRemoveItem,
  onUpdateItem,
  onChooseInCatalog,
  text,
  onTextChange,
  onCalculate,
  calculating,
  interpreting,
  interpretError,
  calcError,
  degraded,
  lists,
  onSaveList,
  onLoadList,
  origin,
  onOriginChange,
  options,
  onOptionsChange,
  originOpen,
  onToggleOriginOpen,
}: ListStepProps) {
  function saveList() {
    const name = askListName();
    if (name !== null) onSaveList(name);
  }

  function handleChooseOption(item: DraftItem, option: InterpretOption) {
    const updated = chooseOption(item, option);
    onUpdateItem(item.id, updated);
  }

  function handleResolveUnknown(id: string, result: SearchResult) {
    onUpdateItem(id, {
      categoryKey: result.key,
      categoryName: result.name,
      options: [],
    });
  }

  const resolvedItems = items.filter(isResolved);
  const unresolvedItems = items.filter((item) => !isResolved(item));
  const busy = calculating || interpreting;

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 pb-3">
          <h2 className="text-xl font-bold tracking-tight text-slate-900">Tu lista</h2>
          <div className="flex items-center gap-2">
            <a
              href={CATALOG_HASH}
              className="text-xs font-semibold text-brand hover:text-brand-dark hover:underline"
            >
              Añadir desde el catálogo
            </a>
            <span className="text-stone-300">·</span>
            <button
              type="button"
              onClick={saveList}
              className="text-xs font-semibold text-stone-600 hover:text-brand"
            >
              Guardar lista
            </button>
            <select
              aria-label="Mis listas"
              value=""
              disabled={lists.length === 0}
              onChange={(event) => {
                const id = event.target.value;
                if (id) onLoadList(id);
              }}
              className="rounded-lg border border-stone-200 bg-stone-50 px-2 py-1 text-xs font-medium text-slate-700 outline-none focus:border-brand disabled:opacity-40"
            >
              <option value="">Mis listas</option>
              {lists.map((list) => (
                <option key={list.id} value={list.id}>
                  {list.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {degraded && (
          <p className="mb-3 rounded-xl border-l-4 border-amber-600 bg-amber-50 p-2.5 text-xs text-amber-900" role="status">
            Hemos interpretado la lista sin el modelo de lenguaje: revisa las líneas marcadas.
          </p>
        )}

        {/* Resolved lines at the top */}
        {resolvedItems.length > 0 && (
          <ul className="mb-4 flex flex-col divide-y divide-stone-100 rounded-xl border border-stone-100 bg-stone-50/50">
            {resolvedItems.map((item) => {
              const label =
                item.productId !== null && item.accept === "exact"
                  ? "Este producto"
                  : `Cualquier ${(item.categoryName || item.text).toLowerCase()}`;
              return (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-3 p-3 transition-colors hover:bg-stone-50"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <ProductImage
                      src={item.imageUrl}
                      alt={item.text}
                      className="h-12 w-12 shrink-0 rounded-xl border border-stone-200"
                    />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">{item.text}</p>
                      <p className="text-xs text-stone-500">{label}</p>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={item.quantity}
                        aria-label={`Cantidad de ${item.text}`}
                        onChange={(event) => onUpdateItem(item.id, { quantity: event.target.value })}
                        className="w-14 rounded-lg border border-stone-200 bg-white px-2 py-1 text-center text-sm font-semibold text-slate-900 outline-none focus:border-brand"
                      />
                      <span className="text-xs font-medium text-stone-500">{item.unit}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item.id)}
                      className="rounded-lg px-2 py-1 text-xs font-semibold text-stone-400 hover:text-price"
                    >
                      Quitar
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {/* Unresolved lines: vague or unknown */}
        {unresolvedItems.length > 0 && (
          <div className="mb-4 flex flex-col gap-3">
            {unresolvedItems.map((item) => {
              if (item.exactOnly) {
                // Shades: only a concrete product can be bought.
                return (
                  <div
                    key={item.id}
                    className="flex flex-col gap-2.5 rounded-2xl border border-stone-200 bg-stone-50/70 p-3.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-sm font-bold text-slate-900">{exactOnlyLine(item.text)}</h3>
                      <button
                        type="button"
                        onClick={() => onRemoveItem(item.id)}
                        className="shrink-0 text-xs font-semibold text-stone-400 hover:text-price"
                      >
                        Quitar
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => onChooseInCatalog(item.text)}
                      className="self-start rounded-full bg-brand px-4 py-2 text-xs font-semibold text-white hover:bg-brand-dark"
                    >
                      {EXACT_ONLY_PICK}
                    </button>
                  </div>
                );
              }
              if (item.options.length > 0) {
                // Vague line
                const term = (item.categoryName || item.text).toLowerCase();
                return (
                  <div
                    key={item.id}
                    className="flex flex-col gap-2.5 rounded-2xl border border-stone-200 bg-stone-50/70 p-3.5"
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-bold text-slate-900">¿Qué {term}?</h3>
                      <button
                        type="button"
                        onClick={() => onRemoveItem(item.id)}
                        className="text-xs font-semibold text-stone-400 hover:text-price"
                      >
                        Quitar
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {item.options.map((option) => (
                        <button
                          key={option.category_key}
                          type="button"
                          onClick={() => handleChooseOption(item, option)}
                          className="flex items-center gap-2.5 rounded-xl border border-stone-200 bg-white p-2 text-left shadow-xs transition-all hover:border-brand hover:shadow-sm"
                        >
                          <ProductImage
                            src={option.image_url}
                            alt={option.name}
                            className="h-10 w-10 shrink-0 rounded-lg border border-stone-100"
                          />
                          <div>
                            <p className="text-xs font-bold text-slate-900">{option.name}</p>
                            {option.from_unit_price !== null && (
                              <p className="text-[0.7rem] text-stone-500">
                                desde {formatUnitPrice(option.from_unit_price, option.base_unit)}
                              </p>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              }

              // Unknown line
              return (
                <div
                  key={item.id}
                  className="flex flex-col gap-2 rounded-2xl border border-amber-200 bg-amber-50/50 p-3.5"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold text-slate-900">
                      No sabemos qué es «{item.text}».
                    </p>
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item.id)}
                      className="text-xs font-semibold text-stone-400 hover:text-price"
                    >
                      Quitar
                    </button>
                  </div>
                  <SearchBox<SearchResult>
                    placeholder="Busca el producto"
                    search={searchProducts}
                    labelOf={(result) => result.name}
                    keyOf={(result) => result.key}
                    hintOf={(result) => result.path}
                    onSelect={(result) => handleResolveUnknown(item.id, result)}
                    minLength={2}
                  />
                </div>
              );
            })}
          </div>
        )}

        {/* Textarea and Calcular button */}
        <div className="flex flex-col gap-3">
          <textarea
            value={text}
            placeholder={TEXTAREA_PLACEHOLDER}
            aria-label="Tu lista"
            rows={4}
            onChange={(event) => onTextChange(event.target.value)}
            className="w-full resize-y rounded-xl border border-stone-200 bg-white p-3 text-sm text-slate-900 placeholder:text-stone-400 outline-none focus:border-brand focus:ring-1 focus:ring-brand"
          />

          <button
            type="button"
            onClick={onCalculate}
            disabled={busy || (text.trim() === "" && items.length === 0)}
            className="w-full rounded-2xl bg-brand py-3 text-center text-sm font-bold text-white shadow-sm transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Calculando…" : "Calcular"}
          </button>
        </div>

        {interpretError && (
          <p className="mt-2 text-xs font-semibold text-price" role="alert">
            {interpretError}
          </p>
        )}
        {calcError && (
          <p className="mt-2 text-xs font-semibold text-price" role="alert">
            {calcError}
          </p>
        )}
      </section>

      {/* Origin folded row or unfolded section */}
      <OriginStep
        origin={origin}
        onOriginChange={onOriginChange}
        options={options}
        onOptionsChange={onOptionsChange}
        open={originOpen}
        onToggleOpen={onToggleOriginOpen}
      />
    </div>
  );
}
