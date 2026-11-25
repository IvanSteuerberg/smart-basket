import { useEffect, useId, useState } from "react";
import type { ActiveChain, SectionCategory } from "../api";
import { DEFAULT_CATALOG_FILTERS, LIST_HASH, type CatalogFilters as Filters } from "../router";
import {
  CATALOG_DIETARY_NOTICE,
  CATALOG_NEAR_NEEDS_ORIGIN,
  DIETARY_LABELS,
} from "../texts";
import { ChainLogoPlate } from "./ChainLogo";
import { useModalDialog } from "./SavedListsDialog";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON = `inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS}`;
const PRIMARY = `inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS}`;
const FIELD = `min-h-11 w-full min-w-0 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.9375rem] text-[var(--ink-primary)] ${FOCUS}`;
const CHECK_ROW =
  "flex min-h-11 cursor-pointer items-center gap-3 text-[0.9375rem] text-[var(--ink-primary)]";

/** The dietary claims offered in the catalog (FR-42), in display order. */
export const DIETARY_FILTERS = ["sin_gluten", "sin_lactosa", "vegano", "vegetariano"];

export type FilterPatch = Partial<Filters>;

/** Number of active filters; sorting, search text and the page are not filters. */
export function countActiveFilters(filters: Filters): number {
  return (
    (filters.sub ? 1 : 0) +
    filters.chains.length +
    (filters.brand.trim() !== "" ? 1 : 0) +
    (filters.privateLabel ? 1 : 0) +
    filters.dietary.length +
    (filters.onPromo ? 1 : 0) +
    (filters.minPrice !== null ? 1 : 0) +
    (filters.maxPrice !== null ? 1 : 0) +
    (filters.near ? 1 : 0)
  );
}

export interface FilterChip {
  key: string;
  label: string;
  /** What removes this chip. */
  patch: FilterPatch;
}

function euros(value: number): string {
  return `${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 }).format(value)} €`;
}

/** Every leaf and group of the categories, keyed, to name a sub-category chip. */
export function subcategoryName(categories: SectionCategory[], key: string): string {
  for (const section of categories) {
    for (const group of section.children) {
      if (group.key === key) return group.name;
      const leaf = group.children.find((candidate) => candidate.key === key);
      if (leaf) return leaf.name;
    }
  }
  return key;
}

export function activeFilterChips(
  filters: Filters,
  categories: SectionCategory[],
  chains: ActiveChain[],
): FilterChip[] {
  const chips: FilterChip[] = [];
  if (filters.sub) {
    chips.push({
      key: "sub",
      label: subcategoryName(categories, filters.sub),
      patch: { sub: null },
    });
  }
  for (const code of filters.chains) {
    const name = chains.find((chain) => chain.code === code)?.name ?? code;
    chips.push({
      key: `chain-${code}`,
      label: name,
      patch: { chains: filters.chains.filter((candidate) => candidate !== code) },
    });
  }
  if (filters.brand.trim() !== "") {
    chips.push({ key: "brand", label: `Marca: ${filters.brand.trim()}`, patch: { brand: "" } });
  }
  if (filters.privateLabel) {
    chips.push({ key: "private", label: "Marca blanca", patch: { privateLabel: false } });
  }
  for (const rule of filters.dietary) {
    chips.push({
      key: `diet-${rule}`,
      label: DIETARY_LABELS[rule] ?? rule,
      patch: { dietary: filters.dietary.filter((candidate) => candidate !== rule) },
    });
  }
  if (filters.onPromo) chips.push({ key: "promo", label: "Solo ofertas", patch: { onPromo: false } });
  if (filters.minPrice !== null) {
    chips.push({
      key: "min",
      label: `Desde ${euros(filters.minPrice)}`,
      patch: { minPrice: null },
    });
  }
  if (filters.maxPrice !== null) {
    chips.push({
      key: "max",
      label: `Hasta ${euros(filters.maxPrice)}`,
      patch: { maxPrice: null },
    });
  }
  if (filters.near) chips.push({ key: "near", label: "Cerca de mí", patch: { near: false } });
  return chips;
}

/** Filters back to their defaults, keeping the search text and the sorting. */
export function clearedFilters(filters: Filters): FilterPatch {
  return {
    ...DEFAULT_CATALOG_FILTERS,
    q: filters.q,
    sort: filters.sort,
  };
}

function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function parsePrice(value: string): number | null {
  const parsed = Number(value.trim().replace(",", "."));
  return value.trim() === "" || !Number.isFinite(parsed) || parsed < 0 ? null : parsed;
}

interface FieldsProps {
  idPrefix: string;
  section: string | null;
  filters: Filters;
  categories: SectionCategory[];
  chains: ActiveChain[];
  hasOrigin: boolean;
  onChange: (patch: FilterPatch) => void;
}

function BrandField({ idPrefix, filters, onChange }: Pick<FieldsProps, "idPrefix" | "filters" | "onChange">) {
  const [draft, setDraft] = useState(filters.brand);

  // The URL is the source of truth: follow it when a chip or «Limpiar» changes the brand.
  useEffect(() => setDraft(filters.brand), [filters.brand]);

  useEffect(() => {
    if (draft.trim() === filters.brand.trim()) return;
    const timer = window.setTimeout(() => onChange({ brand: draft.trim() }), 400);
    return () => window.clearTimeout(timer);
  }, [draft, filters.brand, onChange]);

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`${idPrefix}-brand`} className="text-[0.9375rem] font-semibold">
        Marca
      </label>
      <input
        id={`${idPrefix}-brand`}
        type="search"
        value={draft}
        placeholder="Por ejemplo, Hacendado"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") onChange({ brand: draft.trim() });
        }}
        className={FIELD}
      />
    </div>
  );
}

function PriceField({
  id,
  label,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  value: number | null;
  onCommit: (value: number | null) => void;
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  useEffect(() => setDraft(value === null ? "" : String(value)), [value]);

  function commit() {
    const parsed = parsePrice(draft);
    if (parsed !== value) onCommit(parsed);
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <label htmlFor={id} className="text-[0.8125rem] text-[var(--ink-secondary)]">
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        step="0.01"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
        className={`${FIELD} tabular-nums`}
      />
    </div>
  );
}

const GROUP_TITLE = "text-[0.9375rem] font-semibold text-[var(--ink-primary)]";

/** The filter controls, the same in the desktop side panel and in the mobile dialog. */
export function CatalogFilterFields({
  idPrefix,
  section,
  filters,
  categories,
  chains,
  hasOrigin,
  onChange,
}: FieldsProps) {
  const visibleSections = categories.filter(
    (candidate) => section === null || candidate.key === section,
  );

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="flex flex-col gap-1">
        <label htmlFor={`${idPrefix}-sub`} className={GROUP_TITLE}>
          Subcategoría
        </label>
        <select
          id={`${idPrefix}-sub`}
          value={filters.sub ?? ""}
          onChange={(event) => onChange({ sub: event.target.value || null })}
          className={FIELD}
        >
          <option value="">Todas</option>
          {visibleSections.map((candidate) =>
            candidate.children.map((group) => (
              <optgroup key={group.key} label={group.name}>
                <option value={group.key}>{`Todo en ${group.name}`}</option>
                {group.children.map((leaf) => (
                  <option key={leaf.key} value={leaf.key}>
                    {leaf.name}
                  </option>
                ))}
              </optgroup>
            )),
          )}
        </select>
      </div>

      {chains.length > 0 && (
        <fieldset className="min-w-0">
          <legend className={GROUP_TITLE}>Supermercados</legend>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {chains.map((chain) => {
              const selected = filters.chains.includes(chain.code);
              return (
                <button
                  key={chain.code}
                  type="button"
                  aria-pressed={selected}
                  aria-label={chain.name}
                  title={chain.name}
                  onClick={() => onChange({ chains: toggle(filters.chains, chain.code) })}
                  className={`flex min-h-11 min-w-0 items-center justify-center rounded-xl border-2 p-1 ${FOCUS} ${
                    selected
                      ? "border-[var(--accent-primary)]"
                      : "border-[var(--border-subtle)] hover:border-[var(--accent-primary)]"
                  }`}
                >
                  <ChainLogoPlate chain={chain.code} className="h-8! w-full!" />
                </button>
              );
            })}
          </div>
        </fieldset>
      )}

      <div className="flex flex-col gap-1">
        <BrandField idPrefix={idPrefix} filters={filters} onChange={onChange} />
        <label className={CHECK_ROW}>
          <input
            type="checkbox"
            checked={filters.privateLabel}
            onChange={(event) => onChange({ privateLabel: event.target.checked })}
            className="h-5 w-5"
          />
          Solo marca blanca
        </label>
      </div>

      <fieldset className="min-w-0">
        <legend className={GROUP_TITLE}>Alimentación</legend>
        {DIETARY_FILTERS.map((rule) => (
          <label key={rule} className={CHECK_ROW}>
            <input
              type="checkbox"
              checked={filters.dietary.includes(rule)}
              onChange={() => onChange({ dietary: toggle(filters.dietary, rule) })}
              className="h-5 w-5"
            />
            {DIETARY_LABELS[rule] ?? rule}
          </label>
        ))}
        <p className="mt-1 text-[0.8125rem] leading-snug text-[var(--ink-secondary)]">
          {CATALOG_DIETARY_NOTICE}
        </p>
      </fieldset>

      <label className={CHECK_ROW}>
        <input
          type="checkbox"
          checked={filters.onPromo}
          onChange={(event) => onChange({ onPromo: event.target.checked })}
          className="h-5 w-5"
        />
        Solo ofertas
      </label>

      <fieldset className="min-w-0">
        <legend className={GROUP_TITLE}>Precio (€)</legend>
        <div className="mt-2 flex gap-2">
          <PriceField
            id={`${idPrefix}-min`}
            label="Mínimo"
            value={filters.minPrice}
            onCommit={(minPrice) => onChange({ minPrice })}
          />
          <PriceField
            id={`${idPrefix}-max`}
            label="Máximo"
            value={filters.maxPrice}
            onCommit={(maxPrice) => onChange({ maxPrice })}
          />
        </div>
      </fieldset>

      <div className="flex flex-col">
        <label className={CHECK_ROW}>
          <input
            type="checkbox"
            checked={filters.near}
            disabled={!hasOrigin}
            onChange={(event) => onChange({ near: event.target.checked })}
            className="h-5 w-5"
          />
          Cerca de mí
        </label>
        {!hasOrigin && (
          <p className="text-[0.8125rem] leading-snug text-[var(--ink-secondary)]">
            {CATALOG_NEAR_NEEDS_ORIGIN}{" "}
            <a href={LIST_HASH} className="font-semibold text-[var(--accent-primary)] underline">
              tu lista
            </a>
            .
          </p>
        )}
      </div>
    </div>
  );
}

export interface CatalogFiltersProps {
  section: string | null;
  filters: Filters;
  categories: SectionCategory[];
  chains: ActiveChain[];
  hasOrigin: boolean;
  onChange: (patch: FilterPatch) => void;
  onClear: () => void;
}

/** Side panel on desktop and a native `<dialog>` sheet on mobile, both over the same fields. */
export function CatalogFilters(props: CatalogFiltersProps) {
  const { filters, onClear } = props;
  const [open, setOpen] = useState(false);
  const dialog = useModalDialog(open, () => setOpen(false));
  const titleId = useId();
  const count = countActiveFilters(filters);

  return (
    <>
      <aside
        aria-label="Filtros del catálogo"
        className="hidden min-w-0 lg:sticky lg:top-20 lg:block lg:w-64 lg:shrink-0 lg:self-start"
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-[1.375rem] font-bold tracking-tight">Filtros</h2>
          {count > 0 && (
            <button type="button" onClick={onClear} className={BUTTON}>
              Limpiar filtros
            </button>
          )}
        </div>
        <CatalogFilterFields idPrefix="desktop" {...props} />
      </aside>

      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`${BUTTON} lg:hidden`}
      >
        {count > 0 ? `Filtros (${count})` : "Filtros"}
      </button>

      <dialog
        ref={dialog.ref}
        aria-labelledby={titleId}
        onCancel={dialog.onCancel}
        onClose={dialog.onClose}
        onClick={dialog.onClick}
        className="mt-auto mb-0 mx-0 max-h-[90dvh] w-full max-w-none overflow-hidden rounded-t-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-0 text-[var(--ink-primary)] backdrop:bg-black/55"
      >
        {open && (
          <div className="flex h-full max-h-[inherit] flex-col">
            <header className="flex items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-3">
              <h2 id={titleId} className="text-[1.375rem] font-bold tracking-tight">
                {count > 0 ? `Filtros (${count})` : "Filtros"}
              </h2>
              <button type="button" onClick={() => setOpen(false)} autoFocus className={BUTTON}>
                Cerrar
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <CatalogFilterFields idPrefix="sheet" {...props} />
            </div>
            <footer className="flex gap-2 border-t border-[var(--border-subtle)] px-4 py-3">
              {count > 0 && (
                <button type="button" onClick={onClear} className={BUTTON}>
                  Limpiar filtros
                </button>
              )}
              <button type="button" onClick={() => setOpen(false)} className={`${PRIMARY} flex-1`}>
                Ver resultados
              </button>
            </footer>
          </div>
        )}
      </dialog>
    </>
  );
}
