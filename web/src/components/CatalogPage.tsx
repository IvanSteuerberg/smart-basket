import { useEffect, useState } from "react";
import {
  describeError,
  getProducts,
  type CatalogSection,
  type Product,
  type ProductSort,
} from "../api";
import { CATALOG_HASH, catalogHash } from "../router";
import { SORT_OPTIONS } from "../texts";
import { ProductCard } from "./ProductCard";

const PAGE_SIZE = 24;

export interface CatalogPageProps {
  section: string | null;
  sections: CatalogSection[];
  sectionsError: string | null;
  query: string;
  onQueryChange: (query: string) => void;
  onAdd: (product: Product) => void;
}

export function CatalogPage({
  section,
  sections,
  sectionsError,
  query,
  onQueryChange,
  onAdd,
}: CatalogPageProps) {
  const [sort, setSort] = useState<ProductSort>("unit_price");
  const [items, setItems] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedQuery = query.trim();
  // Searching goes across sections: the section filter only applies without a query.
  const effectiveSection = trimmedQuery === "" ? section : null;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getProducts(
      { section: effectiveSection, q: trimmedQuery, sort, page: 1, size: PAGE_SIZE },
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        setItems(result.items);
        setTotal(result.total);
        setPage(result.page);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(describeError(cause));
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [effectiveSection, trimmedQuery, sort]);

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      const result = await getProducts({
        section: effectiveSection,
        q: trimmedQuery,
        sort,
        page: page + 1,
        size: PAGE_SIZE,
      });
      setItems((current) => [...current, ...result.items]);
      setTotal(result.total);
      setPage(result.page);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  const sectionName = sections.find((candidate) => candidate.key === section)?.name ?? null;
  const title =
    trimmedQuery !== ""
      ? `Resultados para «${trimmedQuery}»`
      : (sectionName ?? "Catálogo");

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="lg:flex lg:gap-6">
        <nav
          aria-label="Secciones del catálogo"
          className="flex gap-2 overflow-x-auto pb-2 lg:sticky lg:top-20 lg:w-52 lg:shrink-0 lg:flex-col lg:gap-1 lg:self-start lg:overflow-visible lg:pb-0"
        >
          <a
            href={CATALOG_HASH}
            onClick={() => onQueryChange("")}
            className={chipClass(section === null && trimmedQuery === "")}
          >
            Todas
          </a>
          {sections.map((candidate) => (
            <a
              key={candidate.key}
              href={catalogHash(candidate.key)}
              onClick={() => onQueryChange("")}
              className={chipClass(candidate.key === section && trimmedQuery === "")}
            >
              {candidate.name}
            </a>
          ))}
        </nav>

        <div className="min-w-0 flex-1">
          {sectionsError && (
            <p role="alert" className="mb-3 text-sm font-semibold text-red-700">
              {sectionsError}
            </p>
          )}

          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-extrabold text-slate-900">{title}</h1>
              <p className="text-sm text-stone-500">
                {loading ? "Cargando…" : `${total} ${total === 1 ? "producto" : "productos"}`}
              </p>
            </div>
            <label className="flex items-center gap-2 text-sm text-stone-600">
              <span>Ordenar por</span>
              <select
                value={sort}
                aria-label="Ordenar por"
                onChange={(event) => setSort(event.target.value as ProductSort)}
                className="w-auto rounded-full border border-stone-300 bg-white px-3 py-2 text-sm text-slate-900"
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {trimmedQuery !== "" && (
            <div className="mt-3 flex items-center gap-2 text-sm text-stone-600">
              <span>Buscando en todas las secciones</span>
              <button
                type="button"
                onClick={() => onQueryChange("")}
                className="w-auto rounded-full border border-stone-300 bg-white px-3 py-1 text-xs font-semibold text-brand"
              >
                Quitar búsqueda
              </button>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-4 text-sm font-semibold text-red-700">
              {error}
            </p>
          )}

          {!loading && !error && items.length === 0 && (
            <p className="mt-8 text-stone-600">
              {trimmedQuery !== ""
                ? `No hemos encontrado productos para «${trimmedQuery}».`
                : "No hay productos en esta sección."}
            </p>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {items.map((product) => (
              <ProductCard key={product.id} product={product} onAdd={onAdd} />
            ))}
          </div>

          {items.length > 0 && items.length < total && (
            <div className="mt-6 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="w-auto rounded-full border border-brand bg-white px-6 py-2.5 font-semibold text-brand hover:bg-brand-soft"
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
    "shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-semibold lg:rounded-xl",
    active
      ? "border-brand bg-brand text-white"
      : "border-stone-200 bg-white text-slate-700 hover:border-brand hover:text-brand",
  ].join(" ");
}
