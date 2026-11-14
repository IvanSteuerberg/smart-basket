import { useEffect, useState } from "react";
import {
  describeError,
  getCanonicals,
  getProducts,
  type CanonicalCard as CanonicalCardData,
  type CatalogSection,
  type Product,
  type ProductSort,
} from "../api";
import { catalogHash, type CatalogView } from "../router";
import { CATALOG_BY_CHAIN, CATALOG_BY_PRODUCT, SORT_OPTIONS } from "../texts";
import { CanonicalCard } from "./CanonicalCard";
import { ProductCard } from "./ProductCard";

const PAGE_SIZE = 24;

export interface CatalogPageProps {
  section: string | null;
  view: CatalogView;
  sections: CatalogSection[];
  sectionsError: string | null;
  query: string;
  onQueryChange: (query: string) => void;
  onAdd: (product: Product) => void;
  onAddCanonical: (card: CanonicalCardData) => void;
}

export function CatalogPage({
  section,
  view,
  sections,
  sectionsError,
  query,
  onQueryChange,
  onAdd,
  onAddCanonical,
}: CatalogPageProps) {
  const [sort, setSort] = useState<ProductSort>("unit_price");
  const [products, setProducts] = useState<Product[]>([]);
  const [canonicals, setCanonicals] = useState<CanonicalCardData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedQuery = query.trim();
  // Searching goes across sections: the section filter only applies without a query.
  const effectiveSection = trimmedQuery === "" ? section : null;
  const byProduct = view === "product";

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const request = byProduct
      ? getCanonicals(
          { section: effectiveSection, q: trimmedQuery, page: 1, size: PAGE_SIZE },
          controller.signal,
        )
      : getProducts(
          { section: effectiveSection, q: trimmedQuery, sort, page: 1, size: PAGE_SIZE },
          controller.signal,
        );
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
        setError(describeError(cause));
        setProducts([]);
        setCanonicals([]);
        setTotal(0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [effectiveSection, trimmedQuery, sort, byProduct]);

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      if (byProduct) {
        const result = await getCanonicals({
          section: effectiveSection,
          q: trimmedQuery,
          page: page + 1,
          size: PAGE_SIZE,
        });
        setCanonicals((current) => [...current, ...result.items]);
        setTotal(result.total);
        setPage(result.page);
      } else {
        const result = await getProducts({
          section: effectiveSection,
          q: trimmedQuery,
          sort,
          page: page + 1,
          size: PAGE_SIZE,
        });
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

  const sectionName = sections.find((candidate) => candidate.key === section)?.name ?? null;
  const title =
    trimmedQuery !== ""
      ? `Resultados para «${trimmedQuery}»`
      : (sectionName ?? "Catálogo");
  const itemCount = byProduct ? canonicals.length : products.length;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex gap-2" role="tablist" aria-label="Vista del catálogo">
        <a
          role="tab"
          aria-selected={byProduct}
          href={catalogHash(section, "product")}
          className={tabClass(byProduct)}
        >
          {CATALOG_BY_PRODUCT}
        </a>
        <a
          role="tab"
          aria-selected={!byProduct}
          href={catalogHash(section, "super")}
          className={tabClass(!byProduct)}
        >
          {CATALOG_BY_CHAIN}
        </a>
      </div>

      <div className="lg:flex lg:gap-6">
        <nav
          aria-label="Secciones del catálogo"
          className="flex gap-2 overflow-x-auto pb-2 lg:sticky lg:top-20 lg:w-52 lg:shrink-0 lg:flex-col lg:gap-1 lg:self-start lg:overflow-visible lg:pb-0"
        >
          <a
            href={catalogHash(null, view)}
            onClick={() => onQueryChange("")}
            className={chipClass(section === null && trimmedQuery === "")}
          >
            Todas
          </a>
          {sections.map((candidate) => (
            <a
              key={candidate.key}
              href={catalogHash(candidate.key, view)}
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
            {!byProduct && (
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
            )}
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

          {!loading && !error && itemCount === 0 && (
            <p className="mt-8 text-stone-600">
              {trimmedQuery !== ""
                ? `No hemos encontrado productos para «${trimmedQuery}».`
                : "No hay productos en esta sección."}
            </p>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {byProduct
              ? canonicals.map((card) => (
                  <CanonicalCard key={card.id} card={card} onAdd={onAddCanonical} />
                ))
              : products.map((product) => (
                  <ProductCard key={product.id} product={product} onAdd={onAdd} />
                ))}
          </div>

          {itemCount > 0 && itemCount < total && (
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

function tabClass(active: boolean): string {
  return [
    "rounded-full border px-4 py-2 text-sm font-semibold",
    active
      ? "border-brand bg-brand text-white"
      : "border-stone-200 bg-white text-slate-700 hover:border-brand hover:text-brand",
  ].join(" ");
}
