import { useEffect, useState } from "react";
import { describeError, getProduct, type Product, type ProductDetail } from "../api";
import { formatEuro, formatUnitPrice } from "../format";
import type { UnifiedLine } from "../listStore";
import { ADD_GENERIC_PREFIX, ADD_SPECIFIC } from "../texts";
import { ChainLogoPlate } from "./ChainLogo";
import {
  changeLineQuantity,
  findProductLine,
  lineQuantity,
  ProductCard,
} from "./ProductCard";
import { ProductImage } from "./ProductImage";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface ProductPageProps {
  id: number;
  /** Exact catalog URL (section, search, filters) the «Volver» link returns to. */
  backHref: string;
  lines: UnifiedLine[];
  onAddSpecific: (product: Product) => void;
  onAddGeneric: (product: Product) => void;
  onUpdateLineQuantity: (id: string, quantity: string) => void;
  onRemoveLine: (id: string) => void;
}

export function ProductPage({
  id,
  backHref,
  lines,
  onAddSpecific,
  onAddGeneric,
  onUpdateLineQuantity,
  onRemoveLine,
}: ProductPageProps) {
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setProduct(null);
    getProduct(id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setProduct(result);
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

      {product && (
        <div className="mt-4 grid min-w-0 gap-6 md:grid-cols-2">
          <ProductImage
            src={product.image_url}
            alt={product.name}
            className="rounded-3xl"
          />

          <div className="min-w-0 text-[var(--ink-primary)]">
            <div className="flex min-w-0 items-center gap-3">
              <ChainLogoPlate chain={product.chain} />
              {product.brand && (
                <p className="min-w-0 truncate text-[0.9375rem] font-semibold text-[var(--ink-secondary)]">
                  {product.brand}
                </p>
              )}
            </div>
            <h1 className="mt-2 text-[1.375rem] font-extrabold">{product.name}</h1>
            {product.packaging && (
              <p className="mt-1 text-[0.9375rem] text-[var(--ink-secondary)]">
                {product.packaging}
              </p>
            )}

            <div className="mt-4 flex flex-wrap items-baseline gap-3">
              <p className="text-[1.375rem] font-bold tabular-nums">{formatEuro(product.price)}</p>
              {product.on_promo === true && (
                <span className="rounded-md bg-[var(--savings-bg)] px-2 py-0.5 text-[0.8125rem] font-semibold text-[var(--savings-fg)]">
                  Oferta
                </span>
              )}
            </div>
            <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
              {formatUnitPrice(product.unit_price, product.base_unit)}
            </p>

            <div className="mt-5 grid gap-2">
              <button
                type="button"
                onClick={() => onAddSpecific(product)}
                className={`min-h-11 w-full rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS}`}
              >
                {ADD_SPECIFIC}
              </button>
              {product.canonical && !product.canonical.exact_only && (
                <button
                  type="button"
                  onClick={() => onAddGeneric(product)}
                  className={`min-h-11 w-full rounded-xl border border-[var(--accent-primary)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--accent-primary)] transition-colors hover:bg-[var(--accent-soft)] ${FOCUS}`}
                >
                  {`${ADD_GENERIC_PREFIX} "${product.canonical.name}"`}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {product && product.alternatives.length > 0 && (
        <section className="mt-10">
          <h2 className="text-[1.375rem] font-extrabold text-[var(--ink-primary)]">
            Otras opciones
          </h2>
          <div className="mt-4 grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {product.alternatives.map((alternative) => (
              <ProductCard
                key={alternative.id}
                product={alternative}
                onAdd={onAddSpecific}
                quantityInList={lineQuantity(findProductLine(lines, alternative.id))}
                onQuantityChange={(target, quantity) => {
                  const line = findProductLine(lines, target.id);
                  if (line) changeLineQuantity(line, quantity, onUpdateLineQuantity, onRemoveLine);
                }}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
