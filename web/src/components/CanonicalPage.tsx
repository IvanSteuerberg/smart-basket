import { useEffect, useState } from "react";
import {
  describeError,
  getCanonical,
  type CanonicalDetail,
  type Product,
} from "../api";
import { formatUnitPrice } from "../format";
import type { UnifiedLine } from "../listStore";
import { ADD_GENERIC_PREFIX } from "../texts";
import { canonicalCountLabel } from "./CanonicalCard";
import {
  changeLineQuantity,
  findProductLine,
  lineQuantity,
  ProductCard,
} from "./ProductCard";
import { ProductImage } from "./ProductImage";

/** Concrete products shown at first and added by each «Ver más productos» (B9). */
export const PRODUCTS_PAGE_SIZE = 24;

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface CanonicalPageProps {
  id: number;
  /** Exact catalog URL (section, search, filters) the «Volver» link returns to. */
  backHref: string;
  lines: UnifiedLine[];
  onAddGeneric: (card: CanonicalDetail) => void;
  onAddSpecific: (product: Product) => void;
  onUpdateLineQuantity: (id: string, quantity: string) => void;
  onRemoveLine: (id: string) => void;
}

/** The generic product: one tap accepts any of its concrete products, or pick one. */
export function CanonicalPage({
  id,
  backHref,
  lines,
  onAddGeneric,
  onAddSpecific,
  onUpdateLineQuantity,
  onRemoveLine,
}: CanonicalPageProps) {
  const [canonical, setCanonical] = useState<CanonicalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(PRODUCTS_PAGE_SIZE);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setCanonical(null);
    setVisible(PRODUCTS_PAGE_SIZE);
    getCanonical(id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setCanonical(result);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(describeError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id]);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <a
        href={backHref}
        className={`inline-flex min-h-11 items-center text-[0.9375rem] font-semibold text-[var(--accent-primary)] hover:underline ${FOCUS}`}
      >
        ← Volver al catálogo
      </a>

      {loading && <p className="mt-6 text-[0.9375rem] text-[var(--ink-secondary)]">Cargando…</p>}
      {error && (
        <p role="alert" className="mt-6 text-[0.9375rem] font-semibold text-[var(--danger-fg)]">
          {error}
        </p>
      )}

      {canonical && (
        <>
          <div className="mt-4 grid min-w-0 gap-6 md:grid-cols-2">
            <ProductImage src={canonical.image_url} alt={canonical.name} className="rounded-3xl" />

            <div className="min-w-0 text-[var(--ink-primary)]">
              <h1 className="text-[1.375rem] font-extrabold">{canonical.name}</h1>
              <p className="mt-4 text-[1.375rem] font-bold tabular-nums">
                desde {formatUnitPrice(canonical.from_unit_price, canonical.base_unit)}
              </p>
              <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
                {canonicalCountLabel(canonical)}
              </p>

              {!canonical.exact_only && (
                <button
                  type="button"
                  onClick={() => onAddGeneric(canonical)}
                  className={`mt-5 min-h-11 w-full rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS}`}
                >
                  {`${ADD_GENERIC_PREFIX} ${canonical.name.toLocaleLowerCase("es")}`}
                </button>
              )}
            </div>
          </div>

          <CanonicalProductList
            products={canonical.products}
            visible={visible}
            lines={lines}
            onAddSpecific={onAddSpecific}
            onUpdateLineQuantity={onUpdateLineQuantity}
            onRemoveLine={onRemoveLine}
            onShowMore={() => setVisible((current) => current + PRODUCTS_PAGE_SIZE)}
          />
        </>
      )}
    </div>
  );
}

export interface CanonicalProductListProps {
  products: Product[];
  /** How many of the products are shown; the rest wait behind «Ver más productos». */
  visible: number;
  lines: UnifiedLine[];
  onAddSpecific: (product: Product) => void;
  onUpdateLineQuantity: (id: string, quantity: string) => void;
  onRemoveLine: (id: string) => void;
  onShowMore: () => void;
}

/** The concrete products of a generic one, revealed 24 at a time (B9). */
export function CanonicalProductList({
  products,
  visible,
  lines,
  onAddSpecific,
  onUpdateLineQuantity,
  onRemoveLine,
  onShowMore,
}: CanonicalProductListProps) {
  if (products.length === 0) return null;
  const remaining = Math.max(0, products.length - visible);
  return (
    <section className="mt-10">
      <h2 className="text-[1.375rem] font-extrabold text-[var(--ink-primary)]">
        Elige uno concreto
      </h2>
      <div className="mt-4 grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {products.slice(0, visible).map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            onAdd={onAddSpecific}
            quantityInList={lineQuantity(findProductLine(lines, product.id))}
            onQuantityChange={(target, quantity) => {
              const line = findProductLine(lines, target.id);
              if (line) changeLineQuantity(line, quantity, onUpdateLineQuantity, onRemoveLine);
            }}
          />
        ))}
      </div>
      {remaining > 0 && (
        <div className="mt-6 flex justify-center">
          <button
            type="button"
            onClick={onShowMore}
            className={`min-h-11 rounded-xl border border-[var(--accent-primary)] bg-[var(--surface-card)] px-6 text-[0.9375rem] font-semibold text-[var(--accent-primary)] hover:bg-[var(--accent-soft)] ${FOCUS}`}
          >
            {`Ver más productos (quedan ${remaining})`}
          </button>
        </div>
      )}
    </section>
  );
}
