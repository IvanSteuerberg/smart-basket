import { useEffect, useRef, useState } from "react";
import { searchProducts, type InterpretOption, type SearchResult, type Unit } from "../api";
import { UNITS, lineFromSearchResult } from "../draft";
import { formatUnitPrice } from "../format";
import { unifiedLineCount, type UnifiedLine } from "../listStore";
import { CATALOG_HASH } from "../router";
import type { SavedList, StoredOrigin } from "../storage";
import {
  EXACT_ONLY_PICK,
  exactOnlyLine,
  LIST_ADD_FROM_CATALOG,
  LIST_ADD_TEXT,
  LIST_DEGRADED,
  LIST_EMPTY,
  LIST_ORIGIN_REQUIRED,
  LIST_REMOVE,
  LIST_SAVED_LISTS,
  LIST_TEXT_LABEL,
  LIST_TEXT_PLACEHOLDER,
  LIST_TITLE,
  PLAN_CALCULATE,
  quantityLabel,
  unresolvedAlert,
} from "../texts";
import {
  AnyBrandSwitch,
  BrandControl,
  isLineResolved,
  lineSubline,
  lineTitle,
  QuantityStepper,
} from "./CartDrawer";
import { OriginStep, type RouteOptions } from "./OriginStep";
import { ProductImage } from "./ProductImage";
import { SavedListsDialog } from "./SavedListsDialog";
import { SearchBox } from "./SearchBox";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON = `inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS} disabled:cursor-not-allowed disabled:opacity-50`;
const PRIMARY = `inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS} disabled:cursor-not-allowed disabled:opacity-50`;
const REMOVE = `inline-flex min-h-11 items-center px-2 text-[0.8125rem] font-semibold text-[var(--ink-secondary)] underline hover:text-[var(--danger-fg)] ${FOCUS}`;
const ALERT =
  "rounded-xl bg-[var(--alert-bg)] p-3 text-[0.9375rem] font-semibold text-[var(--alert-fg)]";

/** A reason to look at the list again: lines left to resolve, or no origin yet. `tick` is new on every attempt. */
export interface ListNotice {
  kind: "unresolved" | "origin";
  tick: number;
}

/** What a vague line becomes once the user picks one of its options. */
export function optionPatch(option: InterpretOption): Partial<UnifiedLine> {
  return {
    categoryKey: option.category_key,
    categoryName: option.name,
    imageUrl: option.image_url,
    options: [],
    exactOnly: option.exact_only,
  };
}

/** Quantity typed for a line switched to units: whole and at least one. */
export function wholeQuantity(quantity: string): string {
  const parsed = Number(quantity.trim().replace(",", "."));
  return String(Number.isFinite(parsed) ? Math.max(1, Math.round(parsed)) : 1);
}

export interface ListStepProps {
  lines: UnifiedLine[];
  anyBrand: boolean;
  onAnyBrandChange: (value: boolean) => void;
  onUpdateLine: (id: string, patch: Partial<Omit<UnifiedLine, "id">>) => void;
  onRemoveLine: (id: string) => void;
  onSetPinBrand: (id: string, pinBrand: boolean) => void;
  /** Opens the catalog searching for the text of a line that needs a concrete product. */
  onChooseInCatalog: (query: string) => void;

  text: string;
  onTextChange: (value: string) => void;
  /** Interprets the text and adds its lines to the list. */
  onAddText: () => void;
  onCalculate: () => void;
  calculating: boolean;
  interpreting: boolean;
  interpretError: string | null;
  calcError: string | null;
  degraded: boolean;
  /** Set by the app when a calculate attempt left lines to resolve or lacked an origin. */
  notice: ListNotice | null;

  lists: SavedList[];
  onSaveList: (name: string) => void;
  onLoadList: (id: string) => void;
  onRenameList: (id: string, name: string) => void;
  onDeleteList: (id: string) => void;

  origin: StoredOrigin | null;
  onOriginChange: (origin: StoredOrigin) => void;
  options: RouteOptions;
  onOptionsChange: (patch: Partial<RouteOptions>) => void;
  originOpen: boolean;
  onToggleOriginOpen: () => void;
}

// First control worth focusing: the address field of the origin bar, or the first choice of a
// pending line (its «Quitar» button is the last resort).
const ORIGIN_FOCUS = "input[type=search], button";
const UNRESOLVED_FOCUS = "ul button, input[type=search], button:not([data-remove])";

/** «Tu lista»: origin bar, the resolved and pending lines, free text and the plan button. */
export function ListStep({
  lines,
  anyBrand,
  onAnyBrandChange,
  onUpdateLine,
  onRemoveLine,
  onSetPinBrand,
  onChooseInCatalog,
  text,
  onTextChange,
  onAddText,
  onCalculate,
  calculating,
  interpreting,
  interpretError,
  calcError,
  degraded,
  notice,
  lists,
  onSaveList,
  onLoadList,
  onRenameList,
  onDeleteList,
  origin,
  onOriginChange,
  options,
  onOptionsChange,
  originOpen,
  onToggleOriginOpen,
}: ListStepProps) {
  const [listsOpen, setListsOpen] = useState(false);
  const originRef = useRef<HTMLDivElement>(null);
  const linesRef = useRef<HTMLDivElement>(null);
  // Initialize to 0 so an alert raised right before navigating to #/lista still scrolls and focuses.
  const seenTick = useRef(0);

  useEffect(() => {
    if (!notice || notice.tick === seenTick.current) return;
    seenTick.current = notice.tick;
    const block =
      notice.kind === "origin"
        ? originRef.current
        : linesRef.current?.querySelector<HTMLElement>("[data-unresolved]");
    if (!block) return;
    block.scrollIntoView?.({ behavior: "smooth", block: "center" });
    const control = block.querySelector<HTMLElement>(
      notice.kind === "origin" ? ORIGIN_FOCUS : UNRESOLVED_FOCUS,
    );
    (control ?? block).focus({ preventScroll: true });
  }, [notice]);

  const resolved = lines.filter(isLineResolved);
  const unresolved = lines.filter((line) => !isLineResolved(line));
  const busy = calculating || interpreting;
  const showUnresolvedAlert = notice?.kind === "unresolved" && unresolved.length > 0;
  const showOriginAlert = notice?.kind === "origin" && origin === null;

  function renderQuantity(line: UnifiedLine) {
    if (line.productId !== null && line.unit === "ud") {
      return (
        <QuantityStepper
          line={line}
          onChange={(quantity) => onUpdateLine(line.id, { quantity })}
        />
      );
    }
    return (
      <div className="flex items-center gap-2">
        <input
          type="text"
          inputMode="decimal"
          value={line.quantity}
          aria-label={`Cantidad de ${lineTitle(line)}: ${quantityLabel(line.quantity, line.unit, false)}`}
          onChange={(event) => onUpdateLine(line.id, { quantity: event.target.value })}
          className={`min-h-11 w-20 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-2 text-center font-sans text-[0.9375rem] font-semibold tabular-nums text-[var(--ink-primary)] outline-none focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]`}
        />
        <select
          aria-label="Unidad"
          value={line.unit}
          onChange={(event) => {
            const unit = event.target.value as Unit;
            onUpdateLine(line.id, {
              unit,
              ...(unit === "ud" ? { quantity: wholeQuantity(line.quantity) } : {}),
            });
          }}
          className="min-h-11 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-2 font-sans text-[0.9375rem] font-semibold text-[var(--ink-primary)] outline-none focus:border-[var(--accent-primary)]"
        >
          {UNITS.map((unit) => (
            <option key={unit} value={unit}>
              {unit}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div ref={originRef} className="scroll-mt-24">
        <OriginStep
          origin={origin}
          onOriginChange={onOriginChange}
          options={options}
          onOptionsChange={onOptionsChange}
          open={originOpen}
          onToggleOpen={onToggleOriginOpen}
        />
      </div>
      {showOriginAlert && (
        <p role="alert" className={ALERT}>
          {LIST_ORIGIN_REQUIRED}
        </p>
      )}

      <section aria-labelledby="list-title" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="list-title" className="text-[1.375rem] font-bold tracking-tight">
            {LIST_TITLE}{" "}
            <span className="text-[0.9375rem] font-semibold tabular-nums text-[var(--ink-secondary)]">
              ({unifiedLineCount(lines)})
            </span>
          </h2>
          <div className="flex flex-wrap items-center gap-x-4">
            <a
              href={CATALOG_HASH}
              className={`inline-flex min-h-11 items-center text-[0.9375rem] font-semibold text-[var(--accent-primary)] hover:underline ${FOCUS}`}
            >
              {LIST_ADD_FROM_CATALOG}
            </a>
            <button type="button" onClick={() => setListsOpen(true)} className={BUTTON}>
              {LIST_SAVED_LISTS}
            </button>
          </div>
        </div>

        {lines.length > 0 && <AnyBrandSwitch anyBrand={anyBrand} onChange={onAnyBrandChange} />}

        {degraded && (
          <p role="status" className={ALERT}>
            {LIST_DEGRADED}
          </p>
        )}

        {showUnresolvedAlert && (
          <p role="alert" className={ALERT}>
            {unresolvedAlert(unresolved.length)}
          </p>
        )}

        <div ref={linesRef} className="flex flex-col gap-4">
          {lines.length === 0 && (
            <p className="text-[0.9375rem] text-[var(--ink-secondary)]">{LIST_EMPTY}</p>
          )}

          {resolved.length > 0 && (
            <ul className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">
              {resolved.map((line) => (
                <li key={line.id} className="flex gap-3 py-3">
                  <ProductImage
                    src={line.imageUrl}
                    alt={lineTitle(line)}
                    className="h-14 w-14 shrink-0 rounded-xl"
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <p className="text-[0.9375rem] font-semibold">{lineTitle(line)}</p>
                    <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{lineSubline(line)}</p>
                    <BrandControl line={line} onChange={(pin) => onSetPinBrand(line.id, pin)} />
                    <div className="flex flex-wrap items-center gap-3">
                      {renderQuantity(line)}
                      <button
                        type="button"
                        onClick={() => onRemoveLine(line.id)}
                        aria-label={`${LIST_REMOVE} ${lineTitle(line)}`}
                        className={`${REMOVE} ml-auto`}
                      >
                        {LIST_REMOVE}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {unresolved.map((line) => {
            const choosable = line.exactOnly || line.options.length > 0;
            const term = (line.categoryName || line.text).toLowerCase();
            return (
              <div
                key={line.id}
                data-unresolved=""
                tabIndex={-1}
                className="scroll-mt-24 flex flex-col gap-3 rounded-xl border-l-4 border-[var(--alert-fg)] bg-[var(--alert-bg)] p-3 outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-[0.9375rem] font-bold">
                    {choosable
                      ? line.exactOnly
                        ? exactOnlyLine(line.text)
                        : `¿Qué ${term}?`
                      : `No sabemos qué es «${line.text}».`}
                  </h3>
                  <button
                    type="button"
                    data-remove=""
                    onClick={() => onRemoveLine(line.id)}
                    aria-label={`${LIST_REMOVE} ${line.text}`}
                    className={`${REMOVE} shrink-0`}
                  >
                    {LIST_REMOVE}
                  </button>
                </div>

                {line.exactOnly ? (
                  <button
                    type="button"
                    onClick={() => onChooseInCatalog(line.text)}
                    className={`${PRIMARY} self-start`}
                  >
                    {EXACT_ONLY_PICK}
                  </button>
                ) : choosable ? (
                  <ul className="flex flex-col gap-2">
                    {line.options.map((option) => (
                      <li key={option.category_key}>
                        <button
                          type="button"
                          onClick={() => onUpdateLine(line.id, optionPatch(option))}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-2 text-left transition-colors hover:border-[var(--accent-primary)] ${FOCUS}`}
                        >
                          <ProductImage
                            src={option.image_url}
                            alt={option.name}
                            className="h-10 w-10 shrink-0 rounded-lg"
                          />
                          <span className="min-w-0">
                            <span className="block text-[0.9375rem] font-semibold">{option.name}</span>
                            {option.from_unit_price !== null && (
                              <span className="block text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
                                desde {formatUnitPrice(option.from_unit_price, option.base_unit)}
                              </span>
                            )}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <SearchBox<SearchResult>
                    placeholder="Busca el producto"
                    search={searchProducts}
                    labelOf={(result) => result.name}
                    keyOf={(result) => result.key}
                    hintOf={(result) => result.path}
                    onSelect={(result) => onUpdateLine(line.id, lineFromSearchResult(result))}
                    minLength={2}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-3">
          <textarea
            value={text}
            placeholder={LIST_TEXT_PLACEHOLDER}
            aria-label={LIST_TEXT_LABEL}
            rows={4}
            onChange={(event) => onTextChange(event.target.value)}
            className="w-full resize-y rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-3 font-sans text-[0.9375rem] text-[var(--ink-primary)] outline-none placeholder:text-[var(--ink-secondary)] focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]"
          />
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onAddText}
              disabled={busy || text.trim() === ""}
              className={BUTTON}
            >
              {interpreting ? "Interpretando…" : LIST_ADD_TEXT}
            </button>
            <button
              type="button"
              onClick={onCalculate}
              disabled={busy || (text.trim() === "" && lines.length === 0)}
              className={PRIMARY}
            >
              {calculating ? "Calculando…" : PLAN_CALCULATE}
            </button>
          </div>
        </div>

        {interpretError && (
          <p className="text-[0.8125rem] font-semibold text-[var(--danger-fg)]" role="alert">
            {interpretError}
          </p>
        )}
        {calcError && (
          <p className="text-[0.8125rem] font-semibold text-[var(--danger-fg)]" role="alert">
            {calcError}
          </p>
        )}
      </section>

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
    </div>
  );
}
