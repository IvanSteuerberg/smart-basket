import { useEffect, useState, type ReactNode } from "react";
import type { AgentRunResponse, BasketLine, Recommendation } from "../api";
import {
  formatAmount,
  formatDateTime,
  formatDistance,
  formatEuro,
  formatMinutes,
  formatQuantity,
  haversineDistanceMeters,
  parseDecimal,
} from "../format";
import type { StoredOrigin } from "../storage";
import { AgentTracePanel } from "./AgentTracePanel";
import { chainCode, ChainLogo } from "./ChainLogo";
import { MapView } from "./MapView";
import { ProductAlternativesModal } from "./ProductAlternativesModal";
import { ProductImage } from "./ProductImage";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS;
const PRIMARY =
  "inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS;
const CHANGE =
  "inline-flex min-h-11 items-center rounded-xl border border-[var(--accent-primary)] bg-[var(--surface-card)] px-3 text-[0.8125rem] font-semibold text-[var(--accent-primary)] transition-colors hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS;

/** Case- and accent-insensitive comparison base for store and brand names (B4). */
function normalizeFold(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

/**
 * Store heading without duplicated names (B4): «1. Alimerka» when the store name just repeats
 * the chain, «1. Carrefour, Espacio León» when the name adds something the chain lacks.
 */
export function formatStoreHeading(position: number, chain: string, name: string): string {
  const cleanChain = chain.trim();
  const cleanName = name.trim();
  if (cleanName === "") return `${position}. ${cleanChain}`;
  const foldedName = normalizeFold(cleanName);
  const foldedChain = normalizeFold(cleanChain);
  if (foldedChain !== "" && foldedName.includes(foldedChain)) {
    return `${position}. ${cleanName}`;
  }
  return `${position}. ${cleanChain}, ${cleanName}`;
}

/**
 * Whether the line should repeat the brand next to the product name: never when the name
 * already contains it, insensitive to case and accents (B4).
 */
export function shouldShowBrand(productName: string, brand: string | null): boolean {
  const cleanBrand = brand?.trim() ?? "";
  if (cleanBrand === "") return false;
  return !normalizeFold(productName).includes(normalizeFold(cleanBrand));
}

/** A standalone weight or volume unit in the raw line text: the line is bought in bulk. */
const BULK_UNIT_RE = /\b(?:kgs?|kilos?|gramos?|gr|g|litros?|l|mililitros?|mls?|ml)\b/i;

/** True when the line asks for weight or volume, or was bought by a fractional amount (B13). */
function isBulkLine(text: string, quantityBought: string | number): boolean {
  if (BULK_UNIT_RE.test(text)) return true;
  const bought = parseDecimal(quantityBought);
  return Number.isFinite(bought) && bought > 0 && !Number.isInteger(bought);
}

/**
 * The bought amount in natural Spanish (B13): «2 envases» for packaged products, and just the
 * clean request text («1 kg de plátanos») for bulk lines, never «1 kg de plátanos · 1 envase».
 */
export function formatBoughtLine(
  line: Pick<BasketLine, "text" | "packs" | "quantity_bought">,
): string {
  const packs = line.packs > 0 ? line.packs : 1;
  if (packs > 1) return `${formatQuantity(packs)} envases`;
  const text = line.text.trim();
  if (isBulkLine(text, line.quantity_bought)) {
    return text !== "" ? text : formatQuantity(line.quantity_bought);
  }
  return "1 envase";
}

export interface BasketStepProps {
  recommendation: Recommendation;
  origin: StoredOrigin | null;
  calculating?: boolean;
  calcError?: string | null;
  agentRun?: AgentRunResponse | null;
  agentLoading?: boolean;
  withoutAgent?: boolean;
  onToggleWithoutAgent?: (next: boolean) => void;
  /** Sends a natural-language request derived from a Pareto alternative («Usar esta opción»). */
  onApplyAlternative?: (message: string) => void;
  /** Optional interactive controls (e.g. E9 question answers / change request). */
  agentSlot?: ReactNode;
  onBack: () => void;
  onNewList: () => void;
  onApplyAnyBrand: () => void;
  onChangeProduct: (lineId: number, productId: number) => void;
}

interface EditingLine {
  lineId: number;
  canonicalId: number;
  currentProductId: number | null;
}

export function BasketStep({
  recommendation,
  origin,
  calculating = false,
  calcError = null,
  agentRun = null,
  agentLoading = false,
  withoutAgent = false,
  onToggleWithoutAgent,
  onApplyAlternative,
  agentSlot,
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
  const plannedChains = stores.map((store) => chainCode(store.chain));

  // One summary, never two (M5): the agent's confirmation when there is one, the engine's
  // explanation only when the agent did not run (or runs without it).
  const buyerSummary = agentRun?.buyer_summary?.trim() || null;
  const summaryText =
    buyerSummary !== null && !withoutAgent ? buyerSummary : recommendation.explanation;

  function lineSavings(lineId: number) {
    if (!recommendation.flex_savings) return null;
    const match = recommendation.flex_savings.lines.find((l) => l.line_id === lineId);
    return match ? match.savings : null;
  }

  const minutesText = formatMinutes(recommendation.minutes);
  const travelText =
    minutesText === ""
      ? `${stores.length} tiendas`
      : `${stores.length} tiendas · ${minutesText} min de trayecto`;

  return (
    <section aria-label="Tu plan de compra" className="flex min-w-0 flex-col gap-4">
      {/* Flat header: title and the big total, left aligned on mobile (A6). */}
      <header className="flex min-w-0 flex-col gap-1 border-b border-[var(--border-subtle)] pb-4 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h2 className="text-[1.375rem] font-bold tracking-tight">Tu plan de compra</h2>
          <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{travelText}</p>
        </div>
        <p className="min-w-0 text-left tabular-nums text-[var(--ink-primary)] sm:text-right">
          <span className="text-[clamp(1.5rem,3.5vw,1.75rem)] font-extrabold tracking-tight">
            {formatEuro(recommendation.total_cost)}
          </span>
        </p>
      </header>

      {calcError && (
        <p className="text-[0.9375rem] font-semibold text-[var(--danger-fg)]" role="alert">
          {calcError}
        </p>
      )}

      {/* The single summary of the plan (M5). */}
      <p className="min-w-0 max-w-prose text-[0.9375rem] leading-relaxed text-[var(--ink-secondary)]">
        {summaryText}
      </p>

      {/* Flex savings callout */}
      {recommendation.flex_savings && parseDecimal(recommendation.flex_savings.total) > 0 && (
        <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-[var(--savings-bg)] p-3.5 text-[var(--savings-fg)] sm:flex-row sm:items-center sm:justify-between">
          <p className="min-w-0 text-[0.9375rem] font-semibold">
            Con cualquier marca ahorrarías {formatEuro(recommendation.flex_savings.total)}.
          </p>
          <button
            type="button"
            onClick={onApplyAnyBrand}
            disabled={calculating}
            className={`${PRIMARY} shrink-0`}
          >
            Aplicar a toda la lista
          </button>
        </div>
      )}

      {/* Agent alternatives, follow-up controls and the decision trace */}
      {(onToggleWithoutAgent || agentRun || agentLoading) && (
        <AgentTracePanel
          agentRun={agentRun}
          loading={agentLoading}
          withoutAgent={withoutAgent}
          onToggleWithoutAgent={onToggleWithoutAgent ?? (() => {})}
          onApplyAlternative={onApplyAlternative}
        >
          {agentSlot}
        </AgentTracePanel>
      )}

      {/* Store cards on the canvas: no card wrapping other cards. */}
      <ol className="flex min-w-0 flex-col gap-4">
        {stores.map((store) => {
          const distanceText = origin
            ? formatDistance(
                haversineDistanceMeters(origin, { lat: store.lat, lon: store.lon }),
              )
            : null;

          return (
            <li key={store.store_id} className="min-w-0">
              <article className="min-w-0 overflow-hidden rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)]">
                {/* Store header */}
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] p-3.5">
                  <div className="flex min-w-0 items-center gap-3">
                    <ChainLogo chain={store.chain.toLowerCase()} className="h-6 w-16 shrink-0" />
                    <div className="min-w-0">
                      <h3 className="min-w-0 text-[0.9375rem] font-bold text-[var(--ink-primary)]">
                        {formatStoreHeading(store.position, store.chain, store.name)}
                      </h3>
                      {store.address && (
                        <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
                          {store.address}
                        </p>
                      )}
                    </div>
                  </div>
                  {distanceText && (
                    <span className="shrink-0 text-[0.8125rem] font-semibold tabular-nums text-[var(--ink-secondary)]">
                      {distanceText}
                    </span>
                  )}
                </div>

                {/* Store lines */}
                <ul className="min-w-0 divide-y divide-[var(--border-subtle)] p-1">
                  {store.lines.map((line) => {
                    const savings = lineSavings(line.line_id);
                    return (
                      <li
                        key={`${line.line_id}-${line.product_id}`}
                        className="flex min-w-0 items-center justify-between gap-3 p-2"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <ProductImage
                            src={line.image_url}
                            alt={line.product_name}
                            className="h-12 w-12 shrink-0 rounded-lg"
                          />
                          <div className="min-w-0">
                            <p className="min-w-0 truncate text-[0.9375rem] font-semibold text-[var(--ink-primary)]">
                              {line.product_name}
                              {shouldShowBrand(line.product_name, line.brand) && (
                                <span className="font-normal text-[var(--ink-secondary)]">
                                  {" "}
                                  · {line.brand}
                                </span>
                              )}
                            </p>
                            <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
                              {formatBoughtLine(line)}
                            </p>
                            {savings && parseDecimal(savings) > 0 && (
                              <p className="text-[0.8125rem] font-semibold text-[var(--savings-fg)]">
                                {formatEuro(savings)} menos con cualquier marca
                              </p>
                            )}
                          </div>
                        </div>

                        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 text-right">
                          <span className="text-[0.9375rem] font-bold tabular-nums text-[var(--ink-primary)]">
                            {formatEuro(line.cost)}
                          </span>
                          {line.canonical_id !== null && !line.exact_only && (
                            <button
                              type="button"
                              disabled={calculating}
                              onClick={() =>
                                setEditingLine({
                                  lineId: line.line_id,
                                  canonicalId: line.canonical_id!,
                                  currentProductId: line.product_id,
                                })
                              }
                              className={CHANGE}
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
                <div className="flex min-w-0 items-center justify-between border-t border-[var(--border-subtle)] px-3.5 py-2.5 text-[0.9375rem] font-bold text-[var(--ink-primary)]">
                  <span>Subtotal</span>
                  <span className="tabular-nums">{formatEuro(store.subtotal)}</span>
                </div>
              </article>
            </li>
          );
        })}
      </ol>

      {/* Missing items */}
      {recommendation.missing.length > 0 && (
        <div className="min-w-0 border-t border-[var(--border-subtle)] pt-3">
          <h3 className="text-[0.9375rem] font-bold text-[var(--ink-primary)]">No incluido</h3>
          <ul className="mt-1.5 flex min-w-0 flex-col gap-1 text-[0.8125rem] text-[var(--ink-secondary)]">
            {recommendation.missing.map((missing, index) => (
              <li key={`${missing.text}-${index}`} className="min-w-0">
                <span className="font-semibold text-[var(--ink-primary)]">{missing.text}</span>
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
      <MapView origin={origin} stores={stores} route={recommendation.route} fitContent />

      {recommendation.data_as_of && (
        <p className="text-center text-[0.8125rem] text-[var(--ink-secondary)]">
          Precios del {formatDateTime(recommendation.data_as_of)}
        </p>
      )}

      {/* Bottom actions */}
      <div className="grid min-w-0 grid-cols-2 gap-3">
        <button type="button" onClick={onBack} className={BUTTON}>
          Volver a la lista
        </button>
        <button type="button" onClick={onNewList} className={PRIMARY}>
          Nueva lista
        </button>
      </div>

      {editingLine && (
        <ProductAlternativesModal
          open
          canonicalId={editingLine.canonicalId}
          lineId={editingLine.lineId}
          currentProductId={editingLine.currentProductId}
          plannedChains={plannedChains}
          onSelect={onChangeProduct}
          onClose={() => setEditingLine(null)}
        />
      )}
    </section>
  );
}
