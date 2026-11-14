import { useEffect, useState } from "react";
import {
  describeError,
  getCanonical,
  type CanonicalDetail,
  type Product,
  type Recommendation,
} from "../api";
import {
  formatAmount,
  formatDateTime,
  formatDistance,
  formatEuro,
  formatMinutes,
  formatUnitPrice,
  haversineDistanceMeters,
  parseDecimal,
} from "../format";
import type { StoredOrigin } from "../storage";
import { ChainLogo } from "./ChainLogo";
import { MapView } from "./MapView";
import { ProductImage } from "./ProductImage";

export interface BasketStepProps {
  recommendation: Recommendation;
  origin: StoredOrigin | null;
  onBack: () => void;
  onNewList: () => void;
  onApplyAnyBrand: () => void;
  onChangeProduct: (lineId: number, productId: number) => void;
}

interface EditingLine {
  lineId: number;
  canonicalId: number;
}

function ProductAlternativesModal({
  canonicalId,
  lineId,
  onSelect,
  onClose,
}: {
  canonicalId: number;
  lineId: number;
  onSelect: (lineId: number, productId: number) => void;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<CanonicalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getCanonical(canonicalId, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) setDetail(res);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(describeError(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [canonicalId]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Cambiar producto"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs"
    >
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-stone-100 p-4">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              {detail ? detail.name : "Cambiar producto"}
            </h3>
            <p className="text-xs text-stone-500">Elige otra opción de este producto genérico</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-slate-800"
            aria-label="Cerrar"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <p className="py-8 text-center text-sm text-stone-500">Cargando opciones…</p>
          )}
          {error && (
            <p className="py-4 text-center text-sm font-semibold text-price" role="alert">
              {error}
            </p>
          )}
          {detail && (
            <div className="flex flex-col gap-2.5">
              {detail.products.map((product: Product) => (
                <button
                  key={product.id}
                  type="button"
                  onClick={() => {
                    onSelect(lineId, product.id);
                    onClose();
                  }}
                  className="flex items-center gap-3 rounded-xl border border-stone-200 p-3 text-left transition-all hover:border-brand hover:bg-brand-soft/30 hover:shadow-xs"
                >
                  <ProductImage
                    src={product.image_url}
                    alt={product.name}
                    className="h-14 w-14 shrink-0 rounded-lg border border-stone-100"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-[0.7rem] font-semibold uppercase tracking-wide text-stone-500">
                      {product.brand ?? product.chain}
                    </p>
                    <p className="truncate text-sm font-semibold text-slate-900">{product.name}</p>
                    {product.packaging && (
                      <p className="text-xs text-stone-500">{product.packaging}</p>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-bold text-price">{formatEuro(product.price)}</p>
                    <p className="text-xs text-stone-500">
                      {formatUnitPrice(product.unit_price, product.base_unit)}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function BasketStep({
  recommendation,
  origin,
  onBack,
  onNewList,
  onApplyAnyBrand,
  onChangeProduct,
}: BasketStepProps) {
  const [editingLine, setEditingLine] = useState<EditingLine | null>(null);

  useEffect(() => {
    try {
      if (
        typeof navigator !== "undefined" &&
        navigator.storage &&
        typeof navigator.storage.persist === "function"
      ) {
        navigator.storage.persist().catch(() => {});
      }
    } catch {
      // Ignore
    }
  }, []);

  const stores = [...recommendation.stores].sort((a, b) => a.position - b.position);

  function lineSavings(lineId: number) {
    if (!recommendation.flex_savings) return null;
    const match = recommendation.flex_savings.lines.find((l) => l.line_id === lineId);
    return match ? match.savings : null;
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
        <h2 className="mb-4 text-xl font-bold tracking-tight text-slate-900">Tu cesta</h2>

        {/* Flex savings banner */}
        {recommendation.flex_savings && parseDecimal(recommendation.flex_savings.total) > 0 && (
          <div className="mb-4 flex flex-col gap-2.5 rounded-2xl border border-brand/20 bg-brand-soft p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-semibold text-brand-dark">
              Con cualquier marca ahorrarías {formatEuro(recommendation.flex_savings.total)}.
            </p>
            <button
              type="button"
              onClick={onApplyAnyBrand}
              className="shrink-0 rounded-xl bg-brand px-4 py-2 text-xs font-bold text-white shadow-xs transition-colors hover:bg-brand-dark"
            >
              Aplicar a toda la lista
            </button>
          </div>
        )}

        {/* Explanation */}
        <p className="mb-4 rounded-xl border-l-4 border-brand bg-brand-soft/50 p-3 text-sm text-slate-800">
          {recommendation.explanation}
        </p>

        {/* Summary totals */}
        <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-stone-100 pb-3">
          <strong className="text-lg font-bold text-slate-900">
            Total: {formatEuro(recommendation.total_cost)}
          </strong>
          <span className="text-xs text-stone-500">
            {formatMinutes(recommendation.minutes)} min de trayecto
          </span>
        </div>

        {/* Store cards */}
        <ol className="mb-4 flex flex-col gap-4">
          {stores.map((store) => {
            const distanceText = origin
              ? formatDistance(
                  haversineDistanceMeters(origin, { lat: store.lat, lon: store.lon }),
                )
              : null;

            return (
              <li key={store.store_id}>
                <article className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-xs">
                  {/* Store header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 bg-stone-50/70 p-3.5">
                    <div className="flex items-center gap-3">
                      <ChainLogo
                        chain={store.chain.toLowerCase()}
                        className="h-6 w-16"
                      />
                      <div>
                        <h3 className="text-sm font-bold text-slate-900">
                          {store.position}. {store.chain} – {store.name}
                        </h3>
                        {store.address && (
                          <p className="text-xs text-stone-500">{store.address}</p>
                        )}
                      </div>
                    </div>
                    {distanceText && (
                      <span className="text-xs font-semibold text-stone-600">{distanceText}</span>
                    )}
                  </div>

                  {/* Store lines */}
                  <ul className="divide-y divide-stone-100 p-3">
                    {store.lines.map((line) => {
                      const savings = lineSavings(line.line_id);
                      return (
                        <li
                          key={`${line.line_id}-${line.product_id}`}
                          className="flex items-center justify-between gap-3 py-2.5"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <ProductImage
                              src={line.image_url}
                              alt={line.product_name}
                              className="h-12 w-12 shrink-0 rounded-xl border border-stone-100"
                            />
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-slate-900">
                                {line.product_name}
                              </p>
                              <p className="text-xs text-stone-500">
                                «{line.text}» · {line.packs}{" "}
                                {line.packs === 1 ? "envase" : "envases"}
                              </p>
                              {savings && parseDecimal(savings) > 0 && (
                                <p className="text-xs font-semibold text-brand">
                                  {formatEuro(savings)} menos con cualquier marca
                                </p>
                              )}
                            </div>
                          </div>

                          <div className="flex shrink-0 items-center gap-3 text-right">
                            <span className="text-sm font-bold text-slate-900">
                              {formatEuro(line.cost)}
                            </span>
                            {line.canonical_id !== null && (
                              <button
                                type="button"
                                onClick={() =>
                                  setEditingLine({
                                    lineId: line.line_id,
                                    canonicalId: line.canonical_id!,
                                  })
                                }
                                className="rounded-lg border border-brand px-2.5 py-1 text-xs font-semibold text-brand hover:bg-brand-soft"
                              >
                                Cambiar
                              </button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>

                  {/* Subtotal */}
                  <div className="flex items-center justify-between border-t border-dashed border-stone-200 bg-stone-50/40 px-4 py-2.5 text-sm font-bold text-slate-900">
                    <span>Subtotal</span>
                    <span>{formatEuro(store.subtotal)}</span>
                  </div>
                </article>
              </li>
            );
          })}
        </ol>

        {/* Missing items */}
        {recommendation.missing.length > 0 && (
          <div className="mb-4 rounded-xl border border-stone-200 bg-stone-50/60 p-3.5">
            <h3 className="mb-2 text-sm font-bold text-slate-900">No incluido</h3>
            <ul className="flex flex-col gap-1 text-xs text-stone-600">
              {recommendation.missing.map((missing, index) => (
                <li key={`${missing.text}-${index}`}>
                  <span className="font-semibold text-slate-800">{missing.text}</span>
                  {missing.reason === "separate_stop" && missing.stop && (
                    <span>
                      {" "}
                      Está en {missing.stop.name}, {formatAmount(missing.stop.cost)} €,{" "}
                      {formatMinutes(missing.stop.extra_minutes)} min más
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Map */}
        <MapView
          origin={origin}
          stores={stores}
          route={recommendation.route}
          fitContent
        />

        {recommendation.data_as_of && (
          <p className="mt-2 text-center text-xs text-stone-500">
            Precios del {formatDateTime(recommendation.data_as_of)}
          </p>
        )}

        {/* Bottom actions */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={onBack}
            className="rounded-2xl border border-brand py-2.5 text-center text-sm font-bold text-brand hover:bg-brand-soft"
          >
            Volver a la lista
          </button>
          <button
            type="button"
            onClick={onNewList}
            className="rounded-2xl bg-brand py-2.5 text-center text-sm font-bold text-white hover:bg-brand-dark"
          >
            Nueva lista
          </button>
        </div>
      </section>

      {editingLine && (
        <ProductAlternativesModal
          canonicalId={editingLine.canonicalId}
          lineId={editingLine.lineId}
          onSelect={onChangeProduct}
          onClose={() => setEditingLine(null)}
        />
      )}
    </div>
  );
}
