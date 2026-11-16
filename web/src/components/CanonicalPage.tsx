import { useEffect, useState } from "react";
import {
  describeError,
  getCanonical,
  type CanonicalDetail,
  type Product,
} from "../api";
import { formatUnitPrice } from "../format";
import { CATALOG_HASH } from "../router";
import { ADD_GENERIC_PREFIX } from "../texts";
import { ProductCard } from "./ProductCard";
import { ProductImage } from "./ProductImage";

export interface CanonicalPageProps {
  id: number;
  onAddGeneric: (card: CanonicalDetail) => void;
  onAddSpecific: (product: Product, exactOnly?: boolean) => void;
}

/** The generic product: one tap accepts any of its concrete products, or pick one. */
export function CanonicalPage({ id, onAddGeneric, onAddSpecific }: CanonicalPageProps) {
  const [canonical, setCanonical] = useState<CanonicalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setCanonical(null);
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
      <a href={CATALOG_HASH} className="text-sm font-semibold text-brand hover:underline">
        ← Volver al catálogo
      </a>

      {loading && <p className="mt-6 text-stone-600">Cargando…</p>}
      {error && (
        <p role="alert" className="mt-6 text-sm font-semibold text-red-700">
          {error}
        </p>
      )}

      {canonical && (
        <>
          <div className="mt-4 grid gap-6 md:grid-cols-2">
            <ProductImage
              src={canonical.image_url}
              alt={canonical.name}
              className="rounded-3xl border border-stone-200"
            />

            <div className="text-slate-900">
              <h1 className="text-2xl font-extrabold sm:text-3xl">{canonical.name}</h1>
              <p className="mt-4 text-3xl font-bold text-price">
                desde {formatUnitPrice(canonical.from_unit_price, canonical.base_unit)}
              </p>
              <p className="text-sm text-stone-500">
                {canonical.product_count}{" "}
                {canonical.product_count === 1 ? "producto" : "productos"}
              </p>

              {!canonical.exact_only && (
                <button
                  type="button"
                  onClick={() => onAddGeneric(canonical)}
                  className="mt-5 w-full rounded-full bg-brand px-4 py-3 font-semibold text-white hover:bg-brand-dark"
                >
                  {`${ADD_GENERIC_PREFIX} ${canonical.name.toLocaleLowerCase("es")}`}
                </button>
              )}
            </div>
          </div>

          {canonical.products.length > 0 && (
            <section className="mt-10">
              <h2 className="text-xl font-extrabold text-slate-900">Elige uno concreto</h2>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {canonical.products.map((product) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    onAdd={(chosen) => onAddSpecific(chosen, canonical.exact_only)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
