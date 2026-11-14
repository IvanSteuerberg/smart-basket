import { useEffect, useRef } from "react";
import {
  draftItemsFromCart,
  isGenericLine,
  MAX_QUANTITY,
  MIN_QUANTITY,
  type CartLine,
} from "../cart";
import { askListName } from "../listName";
import {
  CART_CALCULATE,
  CART_EMPTY,
  CART_SAVE,
  CART_TITLE,
  CART_UNCALCULABLE,
} from "../texts";
import { ProductImage } from "./ProductImage";

export interface CartDrawerProps {
  open: boolean;
  lines: CartLine[];
  onClose: () => void;
  onQuantityChange: (id: string, quantity: number) => void;
  onRemove: (id: string) => void;
  onSaveList: (name: string) => void;
  onCalculate: () => void;
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
  onClose,
  onQuantityChange,
  onRemove,
  onSaveList,
  onCalculate,
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
                        ? `Cualquier ${line.category_name ?? line.name}`
                        : line.name}
                    </p>
                    {!isGenericLine(line) && (line.brand || line.packaging) && (
                      <p className="text-xs text-stone-500">
                        {[line.brand, line.packaging].filter(Boolean).join(" · ")}
                      </p>
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
