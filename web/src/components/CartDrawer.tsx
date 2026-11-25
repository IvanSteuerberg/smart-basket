import { useId, useState } from "react";
import { MAX_QUANTITY, MIN_QUANTITY } from "../cart";
import { unifiedLineCount, type UnifiedLine } from "../listStore";
import type { SavedList } from "../storage";
import {
  anyBrandOf,
  BRAND_ANY,
  BRAND_EXACT_ONLY,
  BRAND_SWITCH,
  BRAND_SWITCH_HELP,
  CART_CHAINS,
  CART_CHAINS_ALL,
  CART_SAVE,
  LIST_EDIT,
  LIST_EMPTY,
  LIST_REMOVE,
  LIST_TITLE,
  LIST_UNCLASSIFIED_LINE,
  PLAN_CALCULATE,
  pinBrandLabel,
  quantityLabel,
} from "../texts";
import { CHAINS, ChainLogoPlate } from "./ChainLogo";
import { ProductImage } from "./ProductImage";
import { SavedListsDialog, useModalDialog } from "./SavedListsDialog";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON = `inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS} disabled:cursor-not-allowed disabled:opacity-50`;
const PRIMARY = `inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS} disabled:cursor-not-allowed disabled:opacity-50`;

const ALL_ACTIVE = `inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--accent-primary)] bg-[var(--accent-soft)] px-4 text-[0.9375rem] font-semibold text-[var(--accent-primary)] ${FOCUS}`;

/** A line the recommender can already use: it has a product or a category and no pending choice. */
export function isLineResolved(line: UnifiedLine): boolean {
  if (line.exactOnly && line.productId === null) return false;
  return line.options.length === 0 && (line.productId !== null || line.categoryKey !== null);
}

/** Name shown for a line: the product when it is concrete, the generic name otherwise. */
export function lineTitle(line: UnifiedLine): string {
  return line.productId !== null ? line.text : line.categoryName || line.text;
}

/** Second line of a row: brand and size of a pinned product, or the brand rule otherwise (B5). */
export function lineSubline(line: UnifiedLine): string {
  if (line.productId !== null) {
    if (line.pinBrand || line.exactOnly) {
      return [line.brand, line.packaging].filter(Boolean).join(" · ");
    }
    return anyBrandOf(line.categoryName);
  }
  return line.brand.trim() === "" ? BRAND_ANY : `Marca: ${line.brand.trim()}`;
}

/** The single brand control of a concrete line (M2); lines of shades only say they are exact. */
export function BrandControl({
  line,
  onChange,
}: {
  line: UnifiedLine;
  onChange: (pinBrand: boolean) => void;
}) {
  if (line.productId === null) return null;
  if (line.exactOnly) {
    return <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{BRAND_EXACT_ONLY}</p>;
  }
  return (
    <button
      type="button"
      aria-pressed={line.pinBrand}
      onClick={() => onChange(!line.pinBrand)}
      className={`inline-flex min-h-11 items-center rounded-xl border px-3 text-[0.8125rem] font-semibold transition-colors ${FOCUS} ${
        line.pinBrand
          ? "border-[var(--accent-primary)] bg-[var(--accent-soft)] text-[var(--accent-primary)]"
          : "border-[var(--border-subtle)] bg-[var(--surface-elevated)] text-[var(--ink-secondary)]"
      }`}
    >
      {pinBrandLabel(line.pinBrand, line.brand)}
    </button>
  );
}

/** Global «Me da igual la marca» switch. */
export function AnyBrandSwitch({
  anyBrand,
  onChange,
}: {
  anyBrand: boolean;
  onChange: (value: boolean) => void;
}) {
  const helpId = useId();
  return (
    <div className="flex flex-col">
      <button
        type="button"
        role="switch"
        aria-checked={anyBrand}
        aria-describedby={helpId}
        onClick={() => onChange(!anyBrand)}
        className={`flex min-h-11 w-full items-center justify-between gap-3 text-left text-[0.9375rem] font-semibold ${FOCUS}`}
      >
        {BRAND_SWITCH}
        <span
          aria-hidden="true"
          className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
            anyBrand ? "bg-[var(--accent-primary)]" : "bg-[var(--ink-secondary)]"
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-[var(--surface-card)] transition-transform ${
              anyBrand ? "translate-x-5" : ""
            }`}
          />
        </span>
      </button>
      <p id={helpId} className="text-[0.8125rem] text-[var(--ink-secondary)]">
        {BRAND_SWITCH_HELP}
      </p>
    </div>
  );
}

/** Stepper for a line counted in units or packs. */
export function QuantityStepper({
  line,
  onChange,
}: {
  line: UnifiedLine;
  onChange: (quantity: string) => void;
}) {
  const value = Number(line.quantity.replace(",", "."));
  const current = Number.isFinite(value) ? value : MIN_QUANTITY;
  const label = quantityLabel(String(current), "ud", line.productId !== null);
  const step =
    "inline-flex min-h-11 min-w-11 items-center justify-center text-[1.375rem] leading-none text-[var(--accent-primary)] disabled:opacity-40 " +
    FOCUS;
  return (
    <div
      role="group"
      aria-label={`Cantidad de ${lineTitle(line)}: ${label}`}
      className="inline-flex items-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)]"
    >
      <button
        type="button"
        aria-label="Restar cantidad"
        disabled={current <= MIN_QUANTITY}
        onClick={() => onChange(String(current - 1))}
        className={step}
      >
        −
      </button>
      <span className="min-w-8 text-center text-[0.9375rem] font-semibold tabular-nums">{current}</span>
      <button
        type="button"
        aria-label="Sumar cantidad"
        disabled={current >= MAX_QUANTITY}
        onClick={() => onChange(String(current + 1))}
        className={step}
      >
        +
      </button>
    </div>
  );
}

export interface CartDrawerProps {
  open: boolean;
  lines: UnifiedLine[];
  anyBrand: boolean;
  /** Selected chains; null means every chain. */
  chainFilter: string[] | null;
  /** Chains offered in the filter; the twelve known chains by default. */
  chains?: { code: string; name: string }[];
  onClose: () => void;
  onQuantityChange: (id: string, quantity: string) => void;
  onSetPinBrand: (id: string, pinBrand: boolean) => void;
  onAnyBrandChange: (value: boolean) => void;
  onChainFilterChange: (chains: string[] | null) => void;
  onRemove: (id: string) => void;
  lists: SavedList[];
  onSaveList: (name: string) => void;
  onLoadList: (id: string) => void;
  onRenameList: (id: string, name: string) => void;
  onDeleteList: (id: string) => void;
  /** Goes to the full list screen (`#/lista`) and closes the drawer. */
  onEditList: () => void;
  onCalculate: () => void;
}

/** The quick view of «Tu lista»: a native modal side panel on desktop and a bottom sheet on mobile. */
export function CartDrawer({
  open,
  lines,
  anyBrand,
  chainFilter,
  chains = CHAINS,
  onClose,
  onQuantityChange,
  onSetPinBrand,
  onAnyBrandChange,
  onChainFilterChange,
  onRemove,
  lists,
  onSaveList,
  onLoadList,
  onRenameList,
  onDeleteList,
  onEditList,
  onCalculate,
}: CartDrawerProps) {
  const dialog = useModalDialog(open, onClose);
  const titleId = useId();
  const [listsOpen, setListsOpen] = useState(false);

  function toggleChain(code: string) {
    const current = chainFilter ?? [];
    const next = current.includes(code)
      ? current.filter((candidate) => candidate !== code)
      : [...current, code];
    onChainFilterChange(next.length === 0 ? null : next);
  }

  const chainSummary =
    chainFilter === null ? CART_CHAINS_ALL : `${chainFilter.length} de ${chains.length}`;

  return (
    <>
      <dialog
        ref={dialog.ref}
        aria-labelledby={titleId}
        onCancel={dialog.onCancel}
        onClose={dialog.onClose}
        onClick={dialog.onClick}
        className="mt-auto mb-0 mx-0 max-h-[85dvh] w-full max-w-none overflow-hidden rounded-t-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-0 text-[var(--ink-primary)] backdrop:bg-black/55 sm:my-0 sm:mr-0 sm:ml-auto sm:h-dvh sm:max-h-dvh sm:w-[26rem] sm:rounded-none"
      >
        {open && (
          <div className="flex h-full max-h-[inherit] flex-col">
            <header className="flex items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-3">
              <h2 id={titleId} className="text-[1.375rem] font-bold tracking-tight">
                {LIST_TITLE}{" "}
                <span className="text-[0.9375rem] font-semibold tabular-nums text-[var(--ink-secondary)]">
                  ({unifiedLineCount(lines)})
                </span>
              </h2>
              <button type="button" onClick={onClose} autoFocus className={BUTTON}>
                Cerrar
              </button>
            </header>

            <div className="flex flex-col gap-1 border-b border-[var(--border-subtle)] px-4 py-2">
              <AnyBrandSwitch anyBrand={anyBrand} onChange={onAnyBrandChange} />
              <details className="group">
                <summary
                  className={`flex min-h-11 cursor-pointer items-center justify-between gap-3 text-[0.9375rem] font-semibold ${FOCUS}`}
                >
                  {CART_CHAINS}
                  <span className="text-[0.8125rem] font-normal text-[var(--ink-secondary)]">
                    {chainSummary}
                  </span>
                </summary>
                <div className="flex flex-wrap gap-1.5 pb-2">
                  <button
                    type="button"
                    aria-pressed={chainFilter === null}
                    onClick={() => onChainFilterChange(null)}
                    className={chainFilter === null ? ALL_ACTIVE : BUTTON}
                  >
                    {CART_CHAINS_ALL}
                  </button>
                  {chains.map(({ code, name }) => {
                    const active = chainFilter?.includes(code) ?? false;
                    return (
                      <button
                        key={code}
                        type="button"
                        aria-label={name}
                        aria-pressed={active}
                        title={name}
                        onClick={() => toggleChain(code)}
                        className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border-2 p-0.5 ${FOCUS} ${
                          active
                            ? "border-[var(--accent-primary)]"
                            : "border-transparent opacity-70 hover:opacity-100"
                        }`}
                      >
                        <ChainLogoPlate chain={code} />
                      </button>
                    );
                  })}
                </div>
              </details>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
              {lines.length === 0 ? (
                <p className="py-8 text-center text-[0.9375rem] text-[var(--ink-secondary)]">
                  {LIST_EMPTY}
                </p>
              ) : (
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {lines.map((line) => {
                    const resolved = isLineResolved(line);
                    return (
                      <li key={line.id} className="flex gap-3 py-3">
                        <span className="block h-16 w-16 shrink-0 overflow-hidden rounded-xl">
                          <ProductImage src={line.imageUrl} alt={lineTitle(line)} />
                        </span>
                        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                          <p className="line-clamp-2 text-[0.9375rem] font-semibold">
                            {lineTitle(line)}
                          </p>
                          {resolved ? (
                            <p className="text-[0.8125rem] text-[var(--ink-secondary)]">
                              {lineSubline(line)}
                            </p>
                          ) : (
                            <p className="text-[0.8125rem] font-semibold text-[var(--alert-fg)]">
                              {LIST_UNCLASSIFIED_LINE}
                            </p>
                          )}
                          <BrandControl
                            line={line}
                            onChange={(pin) => onSetPinBrand(line.id, pin)}
                          />
                          <div className="flex items-center gap-3">
                            {line.unit === "ud" ? (
                              <QuantityStepper
                                line={line}
                                onChange={(quantity) => onQuantityChange(line.id, quantity)}
                              />
                            ) : (
                              <p className="text-[0.9375rem] font-semibold tabular-nums">
                                {quantityLabel(line.quantity, line.unit, false)}
                              </p>
                            )}
                            <button
                              type="button"
                              onClick={() => onRemove(line.id)}
                              aria-label={`${LIST_REMOVE} ${lineTitle(line)}`}
                              className={`ml-auto inline-flex min-h-11 items-center px-2 text-[0.8125rem] font-semibold text-[var(--ink-secondary)] underline hover:text-[var(--danger-fg)] ${FOCUS}`}
                            >
                              {LIST_REMOVE}
                            </button>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <footer className="flex flex-col gap-2 border-t border-[var(--border-subtle)] px-4 py-3">
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={onEditList} className={BUTTON}>
                  {LIST_EDIT}
                </button>
                <button
                  type="button"
                  onClick={onCalculate}
                  disabled={lines.length === 0}
                  className={PRIMARY}
                >
                  {PLAN_CALCULATE}
                </button>
              </div>
              <button type="button" onClick={() => setListsOpen(true)} className={BUTTON}>
                {CART_SAVE}
              </button>
            </footer>
          </div>
        )}
      </dialog>

      <SavedListsDialog
        open={listsOpen}
        onClose={() => setListsOpen(false)}
        lists={lists}
        currentCount={lines.length}
        onSave={onSaveList}
        onLoad={(id) => {
          setListsOpen(false);
          onLoadList(id);
        }}
        onRename={onRenameList}
        onDelete={onDeleteList}
      />
    </>
  );
}
