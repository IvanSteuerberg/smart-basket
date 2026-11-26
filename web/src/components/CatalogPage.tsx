import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  describeError,
  getCanonicals,
  getCategories,
  getProducts,
  type ActiveChain,
  type CanonicalCard as CanonicalCardData,
  type CatalogFilterQuery,
  type CatalogSection,
  type Product,
  type SectionCategory,
  type TravelMode,
} from "../api";
import type { UnifiedLine } from "../listStore";
import {
  CATALOG_HASH,
  catalogHash,
  navigate,
  replaceHash,
  type CatalogFilters as Filters,
  type CatalogView,
} from "../router";
import type { StoredOrigin } from "../storage";
import {
  CANONICAL_SORT_OPTIONS,
  CATALOG_BY_CHAIN,
  CATALOG_BY_PRODUCT,
  CATALOG_SECTION_MISSING,
  CATALOG_SEE_ALL,
} from "../texts";
import { CanonicalCard } from "./CanonicalCard";
import {
  activeFilterChips,
  CatalogFilters,
  clearedFilters,
  countActiveFilters,
  type FilterPatch,
} from "./CatalogFilters";
import {
  changeLineQuantity,
  findCanonicalLine,
  findProductLine,
  lineQuantity,
  ProductCard,
} from "./ProductCard";

export const PAGE_SIZE = 24;

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface CatalogPageProps {
  section: string | null;
  view: CatalogView;
  filters: Filters;
  sections: CatalogSection[];
  sectionsError: string | null;
  query: string;
  activeChains: ActiveChain[];
  /** Saved origin, used by «Cerca de mí». */
  origin: StoredOrigin | null;
  mode: TravelMode;
  /** «Tu lista», to show the inline stepper on cards already in it. */
  lines: UnifiedLine[];
  onQueryChange: (query: string) => void;
  onAdd: (product: Product) => void;
  onAddCanonical: (card: CanonicalCardData) => void;
  onUpdateLineQuantity: (id: string, quantity: string) => void;
  onRemoveLine: (id: string) => void;
}

/** API filters of the URL filters; `category` is the chosen sub-category. */
export function filterQuery(
  filters: Filters,
  origin: StoredOrigin | null,
  mode: TravelMode,
): CatalogFilterQuery & { category: string | null } {
  const near = filters.near && origin !== null;
  return {
    category: filters.sub,
    chains: filters.chains,
    brand: filters.brand.trim() === "" ? null : filters.brand.trim(),
    private_label: filters.privateLabel ? true : null,
    dietary: filters.dietary,
    on_promo: filters.onPromo ? true : null,
    min_price: filters.minPrice,
    max_price: filters.maxPrice,
    near_lat: near ? origin.lat : null,
    near_lon: near ? origin.lon : null,
    mode: near ? mode : null,
  };
}

export function CatalogPage({
  section,
  view,
  filters,
  sections,
  sectionsError,
  query,
  activeChains,
  origin,
  mode,
  lines,
  onQueryChange,
  onAdd,
  onAddCanonical,
  onUpdateLineQuantity,
  onRemoveLine,
}: CatalogPageProps) {
  const [products, setProducts] = useState<Product[]>([]);
  const [canonicals, setCanonicals] = useState<CanonicalCardData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sectionMissing, setSectionMissing] = useState(false);
  const [categories, setCategories] = useState<SectionCategory[]>([]);

  const trimmedQuery = query.trim();
  // Searching goes across sections: the section filter only applies without a query.
  const effectiveSection = trimmedQuery === "" ? section : null;
  const byProduct = view === "product";
  const apiFilters = filterQuery(filters, origin, mode);
  const requestKey = JSON.stringify([effectiveSection, trimmedQuery, byProduct, filters.sort, apiFilters]);

  useEffect(() => {
    const controller = new AbortController();
    getCategories(controller.signal)
      .then((result) => setCategories(result.sections))
      .catch(() => {
        // The sub-category list is optional: the rest of the filters still work.
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const common = {
      section: effectiveSection,
      q: trimmedQuery,
      sort: filters.sort,
      size: PAGE_SIZE,
      ...apiFilters,
    };
    setLoading(true);
    setError(null);
    setSectionMissing(false);
    const request = byProduct
      ? getCanonicals({ ...common, page: 1 }, controller.signal)
      : getProducts({ ...common, page: 1 }, controller.signal);
    request
      .then((result) => {
        if (controller.signal.aborted) return;
        setProducts(byProduct ? [] : (result.items as Product[]));
        setCanonicals(byProduct ? (result.items as CanonicalCardData[]) : []);
        setTotal(result.total);
        setPage(result.page);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        // B7: a section that does not exist is a 422; explain it and offer the whole catalog.
        if (cause instanceof ApiError && cause.status === 422 && effectiveSection !== null) {
          setSectionMissing(true);
        } else {
          setError(describeError(cause));
        }
        setProducts([]);
        setCanonicals([]);
        setTotal(0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // `requestKey` stands for every request input, so the effect runs once per real change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    const common = {
      section: effectiveSection,
      q: trimmedQuery,
      sort: filters.sort,
      size: PAGE_SIZE,
      page: page + 1,
      ...apiFilters,
    };
    try {
      if (byProduct) {
        const result = await getCanonicals(common);
        setCanonicals((current) => [...current, ...result.items]);
        setTotal(result.total);
        setPage(result.page);
      } else {
        const result = await getProducts(common);
        setProducts((current) => [...current, ...result.items]);
        setTotal(result.total);
        setPage(result.page);
      }
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  // Every filter change rewrites the URL (page back to 1), so F5 and «Volver» keep the view.
  const updateFilters = useCallback(
    (patch: FilterPatch) => {
      replaceHash(catalogHash(section, view, { ...filters, ...patch, page: 1 }));
    },
    [section, view, filters],
  );

  function switchView(next: CatalogView) {
    if (next !== view) navigate(catalogHash(section, next, { ...filters, page: 1 }));
  }

  const sectionName = sections.find((candidate) => candidate.key === section)?.name ?? null;
  const title =
    trimmedQuery !== "" ? `Resultados para «${trimmedQuery}»` : (sectionName ?? "Catálogo");
  const itemCount = byProduct ? canonicals.length : products.length;
  const chips = activeFilterChips(filters, categories, activeChains);
  const filterCount = countActiveFilters(filters);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div
        role="group"
        aria-label="Vista del catálogo"
        className="mb-4 inline-flex max-w-full overflow-hidden rounded-xl border border-[var(--border-subtle)]"
      >
        {(
          [
            ["product", CATALOG_BY_PRODUCT],
            ["super", CATALOG_BY_CHAIN],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={view === value}
            onClick={() => switchView(value)}
            className={`min-h-11 px-4 text-[0.9375rem] font-semibold ${FOCUS} ${
              view === value
                ? "bg-[var(--accent-primary)] text-[var(--accent-on-primary)]"
                : "bg-[var(--surface-card)] text-[var(--ink-primary)] hover:bg-[var(--accent-soft)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="lg:flex lg:gap-6">
        <div className="min-w-0 lg:w-64 lg:shrink-0">
          <nav
            aria-label="Secciones del catálogo"
            className="mb-3 flex gap-2 overflow-x-auto pb-2 lg:mb-6 lg:flex-col lg:gap-1 lg:overflow-visible lg:pb-0"
          >
            <a
              href={catalogHash(null, view, { ...filters, q: "", sub: null, page: 1 })}
              onClick={() => onQueryChange("")}
              className={chipClass(section === null && trimmedQuery === "")}
            >
              Todas
            </a>
            {sections.map((candidate) => (
              <a
                key={candidate.key}
                href={catalogHash(candidate.key, view, { ...filters, q: "", sub: null, page: 1 })}
                onClick={() => onQueryChange("")}
                className={chipClass(candidate.key === section && trimmedQuery === "")}
              >
                {candidate.name}
              </a>
            ))}
          </nav>

          <CatalogFilters
            section={effectiveSection}
            filters={filters}
            categories={categories}
            chains={activeChains}
            hasOrigin={origin !== null}
            onChange={updateFilters}
            onClear={() => updateFilters(clearedFilters(filters))}
          />
        </div>

        <div className="mt-4 min-w-0 flex-1 lg:mt-0">
          {sectionsError && (
            <p role="alert" className="mb-3 text-[0.9375rem] font-semibold text-[var(--danger-fg)]">
              {sectionsError}
            </p>
          )}

          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-[1.375rem] font-extrabold text-[var(--ink-primary)]">
                {title}
              </h1>
              <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
                {loading ? "Cargando…" : `${total} ${total === 1 ? "producto" : "productos"}`}
              </p>
            </div>
            <label className="flex items-center gap-2 text-[0.9375rem] text-[var(--ink-secondary)]">
              <span>Ordenar por</span>
              <select
                value={filters.sort}
                onChange={(event) =>
                  updateFilters({ sort: event.target.value as Filters["sort"] })
                }
                className={`min-h-11 w-auto min-w-0 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.9375rem] text-[var(--ink-primary)] ${FOCUS}`}
              >
                {CANONICAL_SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {trimmedQuery !== "" && (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[0.9375rem] text-[var(--ink-secondary)]">
              <span>Buscando en todas las secciones</span>
              <button
                type="button"
                onClick={() => onQueryChange("")}
                className={`min-h-11 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.9375rem] font-semibold text-[var(--accent-primary)] ${FOCUS}`}
              >
                Quitar búsqueda
              </button>
            </div>
          )}

          {chips.length > 0 && (
            <ul aria-label="Filtros activos" className="mt-3 flex flex-wrap items-center gap-2">
              {chips.map((chip) => (
                <li key={chip.key}>
                  <button
                    type="button"
                    onClick={() => updateFilters(chip.patch)}
                    aria-label={`Quitar filtro: ${chip.label}`}
                    className={`inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--accent-soft)] px-3 text-[0.9375rem] font-semibold text-[var(--accent-primary)] ${FOCUS}`}
                  >
                    <span className="min-w-0 truncate">{chip.label}</span>
                    <span aria-hidden="true">×</span>
                  </button>
                </li>
              ))}
              {filterCount > 0 && (
                <li>
                  <button
                    type="button"
                    onClick={() => updateFilters(clearedFilters(filters))}
                    className={`min-h-11 px-2 text-[0.9375rem] font-semibold text-[var(--accent-primary)] underline ${FOCUS}`}
                  >
                    Limpiar filtros
                  </button>
                </li>
              )}
            </ul>
          )}

          {sectionMissing && (
            <div
              role="alert"
              className="mt-4 flex flex-col items-start gap-3 rounded-2xl border border-[var(--danger-fg)] bg-[var(--danger-bg)] p-4 text-[var(--danger-fg)]"
            >
              <p className="text-[0.9375rem] font-semibold">{CATALOG_SECTION_MISSING}</p>
              <a
                href={CATALOG_HASH}
                className={`inline-flex min-h-11 items-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] ${FOCUS}`}
              >
                {CATALOG_SEE_ALL}
              </a>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-4 text-[0.9375rem] font-semibold text-[var(--danger-fg)]">
              {error}
            </p>
          )}

          {!loading && !error && !sectionMissing && itemCount === 0 && (
            <p className="mt-8 text-[0.9375rem] text-[var(--ink-secondary)]">
              {trimmedQuery !== ""
                ? `No hemos encontrado productos para «${trimmedQuery}».`
                : filterCount > 0
                  ? "Ningún producto cumple estos filtros."
                  : "No hay productos en esta sección."}
            </p>
          )}

          <div className="mt-4 grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {byProduct
              ? canonicals.map((card) => (
                  <CanonicalCard
                    key={card.id}
                    card={card}
                    onAdd={onAddCanonical}
                    quantityInList={lineQuantity(findCanonicalLine(lines, card.category_key))}
                    onQuantityChange={(target, quantity) => {
                      const line = findCanonicalLine(lines, target.category_key);
                      if (line) changeLineQuantity(line, quantity, onUpdateLineQuantity, onRemoveLine);
                    }}
                  />
                ))
              : products.map((product) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    onAdd={onAdd}
                    quantityInList={lineQuantity(findProductLine(lines, product.id))}
                    onQuantityChange={(target, quantity) => {
                      const line = findProductLine(lines, target.id);
                      if (line) changeLineQuantity(line, quantity, onUpdateLineQuantity, onRemoveLine);
                    }}
                  />
                ))}
          </div>

          {itemCount > 0 && itemCount < total && (
            <div className="mt-6 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className={`min-h-11 rounded-xl border border-[var(--accent-primary)] bg-[var(--surface-card)] px-6 text-[0.9375rem] font-semibold text-[var(--accent-primary)] hover:bg-[var(--accent-soft)] ${FOCUS}`}
              >
                {loadingMore ? "Cargando…" : "Cargar más"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function chipClass(active: boolean): string {
  return [
    "inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-xl border px-3 text-[0.9375rem] font-semibold",
    FOCUS,
    active
      ? "border-[var(--accent-primary)] bg-[var(--accent-primary)] text-[var(--accent-on-primary)]"
      : "border-[var(--border-subtle)] bg-[var(--surface-card)] text-[var(--ink-primary)] hover:border-[var(--accent-primary)]",
  ].join(" ");
}
