import { useEffect, useRef } from "react";
import type { Accept } from "../api";
import {
  draftItemsFromCart,
  isGenericLine,
  MAX_QUANTITY,
  MIN_QUANTITY,
  type CartLine,
} from "../cart";
import { askListName } from "../listName";
import {
  CART_ACCEPT_ANY_PREFIX,
  CART_ACCEPT_EXACT,
  CART_ACCEPT_LABEL,
  CART_ANY_BRAND,
  CART_ANY_BRAND_HELP,
  CART_CALCULATE,
  CART_CHAINS,
  CART_CHAINS_ALL,
  CART_EMPTY,
  CART_EXPORT_PROFILE,
  CART_IMPORT_PROFILE,
  CART_LOCK,
  CART_LOCK_HELP,
  CART_PROFILE_NOTICE,
  CART_SAVE,
  CART_TITLE,
  CART_UNCALCULABLE,
  CART_UNLOCK,
} from "../texts";
import { CHAINS, ChainLogo } from "./ChainLogo";
import { ProductImage } from "./ProductImage";

export interface CartDrawerProps {
  open: boolean;
  lines: CartLine[];
  anyBrand: boolean;
  /** Selected chains; null means every chain. */
  chainFilter: string[] | null;
  onClose: () => void;
  onQuantityChange: (id: string, quantity: number) => void;
  onAcceptChange: (id: string, accept: Accept) => void;
  onToggleLock: (id: string) => void;
  onAnyBrandChange: (value: boolean) => void;
  onChainFilterChange: (chains: string[] | null) => void;
  onRemove: (id: string) => void;
  onSaveList: (name: string) => void;
  onCalculate: () => void;
  onExportProfile: () => void;
  onImportProfile: (json: string) => void;
}

/** «Cualquier leche entera»: the generic name of a line, in lowercase. */
function anyLabel(name: string): string {
  return `${CART_ACCEPT_ANY_PREFIX} ${name.toLocaleLowerCase("es")}`;
}

function PadlockIcon({ closed }: { closed: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
    >
      <rect x="5" y="10" width="14" height="10" rx="2" />
      {closed ? (
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      ) : (
        <path d="M8 10V7a4 4 0 0 1 7.5-2" />
      )}
    </svg>
  );
}

function QuantityStepper({
  line,
  onChange,
}: {
  line: CartLine;
  onChange: (quantity: number) => void;
}) {
  return (
    <div className="flex items-center rounded-full border border-stone-300 bg-white">
      <button
        type="button"
        aria-label="Restar cantidad"
        disabled={line.quantity <= MIN_QUANTITY}
        onClick={() => onChange(line.quantity - 1)}
        className="h-8 w-8 rounded-full text-lg leading-none text-brand disabled:opacity-40"
      >
        −
      </button>
      <span className="w-8 text-center text-sm font-semibold text-slate-900">{line.quantity}</span>
      <button
        type="button"
        aria-label="Sumar cantidad"
        disabled={line.quantity >= MAX_QUANTITY}
        onClick={() => onChange(line.quantity + 1)}
        className="h-8 w-8 rounded-full text-lg leading-none text-brand disabled:opacity-40"
      >
        +
      </button>
    </div>
  );
}

/** The list being built: a side panel on desktop and a bottom sheet on mobile. */
export function CartDrawer({
  open,
  lines,
  anyBrand,
  chainFilter,
  onClose,
  onQuantityChange,
  onAcceptChange,
  onToggleLock,
  onAnyBrandChange,
  onChainFilterChange,
  onRemove,
  onSaveList,
  onCalculate,
  onExportProfile,
  onImportProfile,
}: CartDrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  // The parent passes a new onClose on every render; the effect below must run only when the
  // drawer opens or closes, or the focus would jump back on every quantity change.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    // A modal dialog takes the focus and gives it back to whatever opened it (WAI-ARIA).
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      opener?.focus();
    };
  }, [open]);

  if (!open) return null;

  const computable = draftItemsFromCart(lines).length;
  const someUnclassified = computable < lines.length;

  function saveList() {
    const name = askListName();
    if (name !== null) onSaveList(name);
  }

  function toggleChain(code: string) {
    const current = chainFilter ?? [];
    const next = current.includes(code)
      ? current.filter((candidate) => candidate !== code)
      : [...current, code];
    onChainFilterChange(next.length === 0 ? null : next);
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    onImportProfile(await file.text());
  }

  return (
    <div className="fixed inset-0 z-50 text-slate-900">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={CART_TITLE}
        className="absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-3xl bg-white shadow-2xl sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[26rem] sm:rounded-none"
      >
        <header className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
          <h2 className="text-lg font-extrabold">{CART_TITLE}</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="h-9 w-9 rounded-full text-xl leading-none text-stone-500 hover:bg-stone-100"
          >
            ×
          </button>
        </header>

        <div className="border-b border-stone-200 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span id="any-brand-label" className="text-sm font-semibold">
              {CART_ANY_BRAND}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={anyBrand}
              aria-labelledby="any-brand-label"
              onClick={() => onAnyBrandChange(!anyBrand)}
              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                anyBrand ? "bg-brand" : "bg-stone-300"
              }`}
            >
              <span
                className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
                  anyBrand ? "left-[1.375rem]" : "left-0.5"
                }`}
              />
            </button>
          </div>
          <p className="mt-1 text-xs text-stone-500">{CART_ANY_BRAND_HELP}</p>

          <div className="mt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              {CART_CHAINS}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                type="button"
                aria-pressed={chainFilter === null}
                onClick={() => onChainFilterChange(null)}
                className={chainChipClass(chainFilter === null)}
              >
                {CART_CHAINS_ALL}
              </button>
              {CHAINS.map(({ code, name }) => (
                <button
                  key={code}
                  type="button"
                  aria-label={name}
                  aria-pressed={chainFilter?.includes(code) ?? false}
                  title={name}
                  onClick={() => toggleChain(code)}
                  className={chainChipClass(chainFilter?.includes(code) ?? false)}
                >
                  <ChainLogo chain={code} className="h-4 w-auto" />
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-2">
          {lines.length === 0 ? (
            <p className="py-8 text-center text-stone-500">{CART_EMPTY}</p>
          ) : (
            <ul>
              {lines.map((line) => (
                <li key={line.id} className="flex gap-3 border-b border-stone-100 py-3 last:border-0">
                  <span className="block h-16 w-16 shrink-0 overflow-hidden rounded-xl">
                    <ProductImage src={line.image_url} alt={line.name} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-sm font-semibold">
                      {isGenericLine(line)
                        ? anyLabel(line.category_name ?? line.name)
                        : line.name}
                    </p>
                    {!isGenericLine(line) && (line.brand || line.packaging) && (
                      <p className="text-xs text-stone-500">
                        {[line.brand, line.packaging].filter(Boolean).join(" · ")}
                      </p>
                    )}
                    {!isGenericLine(line) && (
                      <div className="mt-2 flex items-center gap-2">
                        <select
                          aria-label={CART_ACCEPT_LABEL}
                          value={line.accept}
                          onChange={(event) =>
                            onAcceptChange(line.id, event.target.value as Accept)
                          }
                          className="min-w-0 rounded-lg border border-stone-300 bg-white px-2 py-1 text-xs text-slate-900"
                        >
                          <option value="exact">{CART_ACCEPT_EXACT}</option>
                          <option value="equivalent">
                            {anyLabel(line.category_name ?? line.name)}
                          </option>
                        </select>
                        <button
                          type="button"
                          aria-label={line.locked ? CART_UNLOCK : CART_LOCK}
                          aria-pressed={line.locked}
                          title={CART_LOCK_HELP}
                          onClick={() => onToggleLock(line.id)}
                          className={`shrink-0 rounded-lg border px-2 py-1 ${
                            line.locked
                              ? "border-brand bg-brand-soft text-brand"
                              : "border-stone-300 bg-white text-stone-500"
                          }`}
                        >
                          <PadlockIcon closed={line.locked} />
                        </button>
                      </div>
                    )}
                    <div className="mt-2 flex items-center gap-3">
                      <QuantityStepper
                        line={line}
                        onChange={(quantity) => onQuantityChange(line.id, quantity)}
                      />
                      <button
                        type="button"
                        onClick={() => onRemove(line.id)}
                        className="ml-auto w-auto rounded-full px-2 py-1 text-xs font-semibold text-stone-500 underline hover:text-red-700"
                      >
                        Quitar
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="border-t border-stone-200 px-4 py-3">
          {someUnclassified && (
            <p role="alert" className="mb-2 text-sm font-semibold text-amber-800">
              {CART_UNCALCULABLE}
            </p>
          )}
          <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-semibold text-brand">
            <button type="button" onClick={onExportProfile} className="underline">
              {CART_EXPORT_PROFILE}
            </button>
            <label className="cursor-pointer underline">
              {CART_IMPORT_PROFILE}
              <input
                type="file"
                accept="application/json,.json"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  void importFile(file);
                }}
              />
            </label>
          </div>
          <p className="mb-2 text-[0.7rem] text-stone-500">{CART_PROFILE_NOTICE}</p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={saveList}
              disabled={lines.length === 0}
              className="w-full rounded-full border border-brand bg-white px-4 py-2.5 text-sm font-semibold text-brand hover:bg-brand-soft"
            >
              {CART_SAVE}
            </button>
            <button
              type="button"
              onClick={onCalculate}
              disabled={computable === 0}
              className="w-full rounded-full bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-dark"
            >
              {CART_CALCULATE}
            </button>
          </div>
        </footer>
      </aside>
    </div>
  );
}

function chainChipClass(active: boolean): string {
  return [
    "flex h-8 min-w-8 items-center justify-center rounded-full border px-2",
    active
      ? "border-brand bg-brand-soft ring-1 ring-brand"
      : "border-stone-200 bg-white hover:border-brand",
  ].join(" ");
}
