import { useEffect, useState } from "react";
import { describeError, getProduct, type Product, type ProductDetail } from "../api";
import { formatEuro, formatUnitPrice } from "../format";
import { CATALOG_HASH } from "../router";
import { ADD_GENERIC_PREFIX, ADD_SPECIFIC } from "../texts";
import { ProductCard } from "./ProductCard";
import { ProductImage } from "./ProductImage";

export interface ProductPageProps {
  id: number;
  onAddSpecific: (product: Product) => void;
  onAddGeneric: (product: Product) => void;
}

export function ProductPage({ id, onAddSpecific, onAddGeneric }: ProductPageProps) {
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
      <a href={CATALOG_HASH} className="text-sm font-semibold text-brand hover:underline">
        ← Volver al catálogo
      </a>

      {loading && <p className="mt-6 text-stone-600">Cargando…</p>}
      {error && (
        <p role="alert" className="mt-6 text-sm font-semibold text-red-700">
          {error}
        </p>
      )}

      {product && (
        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <ProductImage
            src={product.image_url}
            alt={product.name}
            className="rounded-3xl border border-stone-200"
          />

          <div className="text-slate-900">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              {product.brand ?? product.chain}
            </p>
            <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">{product.name}</h1>
            {product.packaging && <p className="mt-1 text-sm text-stone-500">{product.packaging}</p>}

            <p className="mt-4 text-3xl font-bold text-price">{formatEuro(product.price)}</p>
            <p className="text-sm text-stone-500">
              {formatUnitPrice(product.unit_price, product.base_unit)}
            </p>

            <div className="mt-5 grid gap-2">
              <button
                type="button"
                onClick={() => onAddSpecific(product)}
                className="w-full rounded-full bg-brand px-4 py-3 font-semibold text-white hover:bg-brand-dark"
              >
                {ADD_SPECIFIC}
              </button>
              {product.canonical && !product.canonical.exact_only && (
                <button
                  type="button"
                  onClick={() => onAddGeneric(product)}
                  className="w-full rounded-full border border-brand bg-white px-4 py-3 font-semibold text-brand hover:bg-brand-soft"
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
          <h2 className="text-xl font-extrabold text-slate-900">Otras opciones</h2>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {product.alternatives.map((alternative) => (
              <ProductCard key={alternative.id} product={alternative} onAdd={onAddSpecific} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
