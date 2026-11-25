import { useEffect, useId, useState } from "react";
import {
  describeError,
  getCanonical,
  getProducts,
  type CanonicalDetail,
  type Product,
} from "../api";
import { formatEuro, formatUnitPrice } from "../format";
import { chainCode, ChainLogoPlate } from "./ChainLogo";
import { ProductImage } from "./ProductImage";
import { useModalDialog } from "./SavedListsDialog";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50";
const SEGMENT =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.9375rem] font-semibold text-[var(--ink-secondary)] transition-colors hover:border-[var(--accent-primary)]";

export interface ProductOptionRowProps {
  product: Product;
  /** The product already in the plan: shown with an accent border and a label. */
  current?: boolean;
  /** Chain codes the plan already shops in; other chains get an alert note. */
  plannedChains: string[];
  disabled?: boolean;
  onSelect: (productId: number) => void;
}

/**
 * One selectable product of the modal: always shows the chain and, when it has one, the brand,
 * the price in tabular digits and the unit price. A chain outside the plan gets a clear note.
 */
export function ProductOptionRow({
  product,
  current = false,
  plannedChains,
  disabled = false,
  onSelect,
}: ProductOptionRowProps) {
  const outsidePlan = !plannedChains.includes(chainCode(product.chain));
  const chainLabel = product.brand ? `${product.brand} · ${product.chain}` : product.chain;

  return (
    <li>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSelect(product.id)}
        className={`flex min-h-11 w-full min-w-0 items-center gap-3 rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS} ${
          current
            ? "border-[var(--accent-primary)] bg-[var(--accent-soft)]"
            : "border-[var(--border-subtle)] bg-[var(--surface-card)] hover:border-[var(--accent-primary)]"
        }`}
      >
        <ProductImage
          src={product.image_url}
          alt={product.name}
          className="h-14 w-14 shrink-0 rounded-lg"
        />
        <div className="min-w-0 flex-1">
          <p className="text-[0.8125rem] font-semibold text-[var(--ink-secondary)]">
            {chainLabel}
          </p>
          <p className="truncate text-[0.9375rem] font-semibold text-[var(--ink-primary)]">
            {product.name}
          </p>
          {product.packaging && (
            <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{product.packaging}</p>
          )}
          {current && (
            <p className="text-[0.8125rem] font-semibold text-[var(--accent-primary)]">
              En tu plan actual
            </p>
          )}
          {outsidePlan && (
            <p className="text-[0.8125rem] text-[var(--alert-fg)]">
              Otra cadena: puede añadir o cambiar tiendas en tu plan
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-right">
          <ChainLogoPlate chain={product.chain} className="h-8 w-16 rounded-md" />
          <p className="text-[0.9375rem] font-bold tabular-nums text-[var(--ink-primary)]">
            {formatEuro(product.price)}
          </p>
          <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
            {formatUnitPrice(product.unit_price, product.base_unit)}
          </p>
        </div>
      </button>
    </li>
  );
}

export interface ProductAlternativesModalProps {
  open: boolean;
  canonicalId: number;
  /** Index of the basket line being changed (the request's `items` index). */
  lineId: number;
  /** The concrete product the line buys now, if any: marked as the current one. */
  currentProductId: number | null;
  /** Chain codes the plan already shops in, to warn about products in other chains. */
  plannedChains: string[];
  onSelect: (lineId: number, productId: number) => void;
  onClose: () => void;
}

/**
 * «Cambiar»: native modal dialog to swap the product of a plan line. The first tab lists the
 * products of the same canonical; the second one widens the choice to related products of the
 * same category, so a line is never stuck with one option (M3).
 */
export function ProductAlternativesModal({
  open,
  canonicalId,
  lineId,
  currentProductId,
  plannedChains,
  onSelect,
  onClose,
}: ProductAlternativesModalProps) {
  const dialog = useModalDialog(open, onClose);
  const titleId = useId();
  const tabsId = useId();
  const [tab, setTab] = useState<"same" | "related">("same");
  const [detail, setDetail] = useState<CanonicalDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [related, setRelated] = useState<Product[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  // Set as soon as the related tab fetches once: an empty answer must not fetch forever.
  const [relatedLoaded, setRelatedLoaded] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTab("same");
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    setRelated([]);
    setRelatedError(null);
    setRelatedLoaded(false);
  }, [open, canonicalId]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError(null);
    getCanonical(canonicalId, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) setDetail(res);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setDetailError(describeError(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [open, canonicalId]);

  // The related tab loads on first use, not on open: the shopper often stays on the first one.
  useEffect(() => {
    if (!open || tab !== "related" || detail === null || relatedLoaded) {
      return;
    }
    const controller = new AbortController();
    setRelatedLoaded(true);
    setRelatedLoading(true);
    setRelatedError(null);
    getProducts({ category: detail.category_key, size: 24 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setRelated(
          page.items.filter(
            (product) =>
              product.id !== currentProductId && product.canonical?.id !== detail.id,
          ),
        );
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setRelatedError(describeError(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setRelatedLoading(false);
      });
    return () => controller.abort();
  }, [open, tab, detail, relatedLoaded, currentProductId]);

  function handleSelect(productId: number) {
    onSelect(lineId, productId);
    onClose();
  }

  return (
    <dialog
      ref={dialog.ref}
      aria-labelledby={titleId}
      onCancel={dialog.onCancel}
      onClose={dialog.onClose}
      onClick={dialog.onClick}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-0 text-[var(--ink-primary)] backdrop:bg-black/55"
    >
      <div className="flex min-w-0 flex-col gap-4 p-5">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <h2 id={titleId} className="min-w-0 text-[1.375rem] font-bold tracking-tight">
            {detail ? `Cambiar: ${detail.name}` : "Cambiar producto"}
          </h2>
          <button type="button" onClick={onClose} autoFocus className={BUTTON}>
            Cerrar
          </button>
        </div>

        <div
          role="group"
          aria-labelledby={tabsId}
          className="flex min-w-0 flex-wrap gap-2"
        >
          <p id={tabsId} className="sr-only">
            Opciones del producto
          </p>
          <button
            type="button"
            aria-pressed={tab === "same"}
            onClick={() => setTab("same")}
            className={`${SEGMENT} ${tab === "same" ? "border-[var(--accent-primary)] bg-[var(--accent-soft)] text-[var(--accent-primary)]" : ""}`}
          >
            Mismo producto
          </button>
          <button
            type="button"
            aria-pressed={tab === "related"}
            onClick={() => setTab("related")}
            className={`${SEGMENT} ${tab === "related" ? "border-[var(--accent-primary)] bg-[var(--accent-soft)] text-[var(--accent-primary)]" : ""}`}
          >
            Otras opciones parecidas
          </button>
        </div>

        <div className="flex min-w-0 flex-col">
          {tab === "same" && (
            <>
              {detailLoading && (
                <p className="py-8 text-center text-[0.9375rem] text-[var(--ink-secondary)]">
                  Cargando opciones…
                </p>
              )}
              {detailError && (
                <p
                  className="py-4 text-center text-[0.9375rem] font-semibold text-[var(--danger-fg)]"
                  role="alert"
                >
                  {detailError}
                </p>
              )}
              {detail && detail.products.length === 0 && !detailLoading && (
                <p className="py-4 text-center text-[0.9375rem] text-[var(--ink-secondary)]">
                  No hay otras opciones de este producto.
                </p>
              )}
              {detail && detail.products.length > 0 && (
                <ul className="flex min-w-0 flex-col gap-2">
                  {detail.products.map((product) => (
                    <ProductOptionRow
                      key={product.id}
                      product={product}
                      current={product.id === currentProductId}
                      plannedChains={plannedChains}
                      disabled={detailLoading}
                      onSelect={handleSelect}
                    />
                  ))}
                </ul>
              )}
            </>
          )}

          {tab === "related" && (
            <>
              {relatedLoading && (
                <p className="py-8 text-center text-[0.9375rem] text-[var(--ink-secondary)]">
                  Buscando opciones parecidas…
                </p>
              )}
              {relatedError && (
                <p
                  className="py-4 text-center text-[0.9375rem] font-semibold text-[var(--danger-fg)]"
                  role="alert"
                >
                  {relatedError}
                </p>
              )}
              {!relatedLoading && !relatedError && related.length === 0 && (
                <p className="py-4 text-center text-[0.9375rem] text-[var(--ink-secondary)]">
                  No encontramos otras opciones parecidas.
                </p>
              )}
              {related.length > 0 && (
                <ul className="flex min-w-0 flex-col gap-2">
                  {related.map((product) => (
                    <ProductOptionRow
                      key={product.id}
                      product={product}
                      current={product.id === currentProductId}
                      plannedChains={plannedChains}
                      disabled={relatedLoading}
                      onSelect={handleSelect}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
