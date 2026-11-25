import { useState, type ReactNode } from "react";
import type { AgentRunResponse, AgentStep } from "../api";
import { formatEuro, formatMinutes, parseDecimal } from "../format";
import { CHAINS } from "./ChainLogo";

export interface AgentTracePanelProps {
  agentRun: AgentRunResponse | null;
  loading?: boolean;
  withoutAgent: boolean;
  onToggleWithoutAgent: (next: boolean) => void;
  /**
   * Applies a Pareto alternative: sends the agent the natural-language change that reproduces
   * it («Usar esta opción»). Absent when the host cannot talk to the agent.
   */
  onApplyAlternative?: (message: string) => void;
  /** Slot for follow-up shopper controls (e.g. answering a question or asking for changes). */
  children?: ReactNode;
}

const OBSERVATION_LABELS: Record<string, string> = {
  vague_line: "Línea ambigua",
  missing_everywhere: "No disponible",
  near_tie: "Empate técnico",
  shopper_request: "Petición",
};

const MODE_LABELS: Record<string, string> = {
  walk: "A pie",
  car: "En coche",
};

/** Display name of a chain code («alimerka» becomes «Alimerka»). */
function chainDisplayName(code: string): string {
  return CHAINS.find((chain) => chain.code === code)?.name ?? code;
}

function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function formatPercent(value: number): string {
  return `${Math.round(clampUnit(value) * 100)} %`;
}

function isDecimalLike(value: unknown): value is string | number {
  return (typeof value === "string" && value.trim() !== "") || typeof value === "number";
}

/** «+4,14 €» / «-0,80 €»; null when the value is missing or exactly zero. */
function formatEuroDelta(value: unknown): string | null {
  if (!isDecimalLike(value)) return null;
  const parsed = parseDecimal(value);
  if (!Number.isFinite(parsed) || parsed === 0) return null;
  const sign = parsed > 0 ? "+" : "-";
  return `${sign}${formatEuro(Math.abs(parsed))}`;
}

/** «+6 min» / «-3 min»; null when the value is missing or exactly zero. */
function formatMinutesDelta(value: unknown): string | null {
  if (!isDecimalLike(value)) return null;
  const parsed = parseDecimal(value);
  if (!Number.isFinite(parsed) || parsed === 0) return null;
  const sign = parsed > 0 ? "+" : "-";
  return `${sign}${Math.round(Math.abs(parsed))} min`;
}

export interface AlternativeView {
  storesText: string;
  modeLabel: string | null;
  costText: string | null;
  minutesText: string | null;
  costDelta: string | null;
  minutesDelta: string | null;
  reason: string | null;
}

export function parseAlternativePlan(alt: Record<string, unknown>): AlternativeView {
  const rawStores = Array.isArray(alt.store_names)
    ? alt.store_names
    : Array.isArray(alt.stores)
      ? alt.stores
      : [];
  const storeNames = rawStores.filter(
    (item): item is string => typeof item === "string" && item.trim() !== "",
  );
  const storesText = storeNames.length > 0 ? storeNames.join(", ") : "Plan alternativo";

  const rawMode = typeof alt.mode === "string" ? alt.mode : null;
  const modeLabel = rawMode ? (MODE_LABELS[rawMode] ?? rawMode) : null;

  const costText = isDecimalLike(alt.total_cost) ? formatEuro(alt.total_cost) : null;

  const rawMinutes = alt.travel_minutes ?? alt.minutes;
  const minutesText = isDecimalLike(rawMinutes)
    ? `${formatMinutes(rawMinutes)} min`
    : null;

  return {
    storesText,
    modeLabel,
    costText,
    minutesText,
    costDelta: formatEuroDelta(alt.cost_delta),
    minutesDelta: formatMinutesDelta(alt.minutes_delta),
    reason: typeof alt.reason === "string" && alt.reason.trim() !== "" ? alt.reason : null,
  };
}

/**
 * The request «Usar esta opción» sends to the agent for one alternative (M6): the mode change
 * when it differs, the single chain when there is one, and a generic fallback otherwise.
 */
export function alternativeRequestMessage(
  alt: Record<string, unknown>,
  currentMode: string,
): string {
  const parts: string[] = [];
  const mode = typeof alt.mode === "string" && alt.mode.trim() !== "" ? alt.mode : null;
  if (mode !== null && mode !== currentMode) {
    parts.push(mode === "car" ? "cambia a coche" : "cambia a ir a pie");
  }
  const chainCodes = Array.isArray(alt.chain_codes)
    ? alt.chain_codes.filter((code): code is string => typeof code === "string" && code !== "")
    : [];
  if (chainCodes.length === 1) {
    parts.push(`haz la compra solo en ${chainDisplayName(chainCodes[0])}`);
  }
  if (parts.length === 0) {
    const rawStores = Array.isArray(alt.store_names) ? alt.store_names : [];
    const names = rawStores.filter(
      (item): item is string => typeof item === "string" && item.trim() !== "",
    );
    parts.push(
      names.length > 0
        ? `usa esta opción: haz la compra en ${names.join(" y ")}`
        : "usa esta opción",
    );
  }
  return parts.join(", ");
}

function StepCard({ step }: { step: AgentStep }) {
  const observationKind = step.observation?.kind ?? "paso";
  const observationLabel = OBSERVATION_LABELS[observationKind] ?? observationKind;

  return (
    <li className="flex min-w-0 flex-col gap-1.5 rounded-xl bg-[var(--surface-elevated)] p-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 text-[0.8125rem] font-bold text-[var(--ink-primary)]">
          Paso {step.step_number} · {observationLabel}
        </p>
        <p className="flex shrink-0 items-center gap-2 text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
          {step.confidence !== null && (
            <span className="font-semibold text-[var(--ink-primary)]">
              Confianza {formatPercent(step.confidence)}
            </span>
          )}
          <span>{Math.round(step.latency_ms)} ms</span>
        </p>
      </div>

      {step.used_default && (
        <p className="text-[0.8125rem] font-semibold text-[var(--alert-fg)]">
          Decisión por defecto
        </p>
      )}

      {step.observation?.summary && (
        <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
          {step.observation.summary}
        </p>
      )}

      {step.candidates.length > 0 && (
        <ul className="mt-1 flex min-w-0 flex-col gap-1.5" aria-label="Opciones evaluadas">
          {step.candidates.map((candidate) => {
            const isChosen =
              candidate.key === step.chosen_action || candidate.kind === step.chosen_action;
            const probability =
              step.probabilities?.[candidate.key] ?? step.probabilities?.[candidate.kind];
            const hasProb = typeof probability === "number" && Number.isFinite(probability);
            const percent = hasProb ? Math.round(clampUnit(probability) * 100) : 0;

            return (
              <li
                key={candidate.key}
                className={
                  isChosen
                    ? "rounded-lg bg-[var(--accent-soft)] px-2.5 py-1.5 text-[0.8125rem] font-semibold text-[var(--ink-primary)]"
                    : "rounded-lg px-2.5 py-1.5 text-[0.8125rem] text-[var(--ink-secondary)]"
                }
              >
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <span className="min-w-0">
                    {isChosen ? `✓ ${candidate.label}` : candidate.label}
                  </span>
                  {hasProb && (
                    <span className="shrink-0 font-semibold tabular-nums">{percent} %</span>
                  )}
                </div>
                {hasProb && (
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]">
                    <div
                      className="h-full rounded-full bg-[var(--accent-primary)]"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {step.result?.summary && (
        <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
          <span className="font-semibold text-[var(--ink-primary)]">Resultado:</span>{" "}
          {step.result.summary}
        </p>
      )}

      {step.error && (
        <p className="min-w-0 text-[0.8125rem] font-semibold text-[var(--danger-fg)]" role="status">
          {step.error}
        </p>
      )}
    </li>
  );
}

/**
 * The agent area of the plan: follow-up controls (its children), the Pareto alternatives with a
 * «Usar esta opción» action, the «Sin asistente» comparison toggle and the collapsed-by-default
 * «Cómo lo ha decidido» trace. The buyer summary itself is shown once by BasketStep (M5).
 */
export function AgentTracePanel({
  agentRun,
  loading = false,
  withoutAgent,
  onToggleWithoutAgent,
  onApplyAlternative,
  children,
}: AgentTracePanelProps) {
  const [traceOpen, setTraceOpen] = useState(false);

  // Follow-up controls (e.g. «Pide un cambio») stay available even if the agent failed.
  if (!agentRun && !loading && !children) {
    return null;
  }

  const currentMode = agentRun?.mode ?? "";

  return (
    <section
      aria-label="Asistente de compra"
      className="flex min-w-0 flex-col gap-3 border-t border-[var(--border-subtle)] pt-3"
    >
      {loading && (
        <p role="status" className="min-w-0 text-[0.9375rem] text-[var(--ink-secondary)]">
          Revisando tu cesta con el asistente…
        </p>
      )}

      {children}

      {/* Alternative plans shown by the agent (M6) */}
      {agentRun && agentRun.alternatives_shown.length > 0 && (
        <div className="flex min-w-0 flex-col gap-2">
          <h3 className="text-[0.9375rem] font-bold text-[var(--ink-primary)]">
            Alternativas comparadas
          </h3>
          <ul className="flex min-w-0 flex-col gap-2">
            {agentRun.alternatives_shown.map((alt, index) => {
              const view = parseAlternativePlan(alt);
              const details = [
                view.costText !== null
                  ? `${view.costText}${view.costDelta ? ` (${view.costDelta})` : ""}`
                  : null,
                view.minutesText !== null
                  ? `${view.minutesText}${view.minutesDelta ? ` (${view.minutesDelta})` : ""}`
                  : null,
              ].filter((part): part is string => part !== null);

              return (
                <li
                  key={index}
                  style={{ borderLeft: "3px solid var(--savings-fg)" }}
                  className="flex min-w-0 flex-col gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-3.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="min-w-0 text-[0.9375rem] font-semibold text-[var(--ink-primary)]">
                      {view.modeLabel ? `${view.modeLabel}: ` : ""}
                      {view.storesText}
                    </p>
                    {details.length > 0 && (
                      <p className="min-w-0 text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
                        {details.join(" · ")}
                      </p>
                    )}
                    {view.reason && (
                      <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
                        {view.reason}
                      </p>
                    )}
                  </div>
                  {onApplyAlternative && (
                    <button
                      type="button"
                      disabled={loading}
                      onClick={() => onApplyAlternative(alternativeRequestMessage(alt, currentMode))}
                      className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.8125rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Usar esta opción
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Trace toggle and the «Sin asistente» comparison switch */}
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        {agentRun ? (
          <button
            type="button"
            aria-expanded={traceOpen}
            onClick={() => setTraceOpen((prev) => !prev)}
            className="flex min-h-11 min-w-0 items-center justify-between gap-2 text-left text-[0.9375rem] font-semibold text-[var(--accent-primary)]"
          >
            <span>
              Cómo lo ha decidido
              {agentRun.steps.length > 0 ? ` (${agentRun.steps.length})` : ""}
            </span>
            <span aria-hidden="true" className="text-[var(--ink-secondary)]">
              {traceOpen ? "▲" : "▼"}
            </span>
          </button>
        ) : (
          <span />
        )}

        <button
          type="button"
          role="switch"
          aria-checked={withoutAgent}
          disabled={loading}
          onClick={() => onToggleWithoutAgent(!withoutAgent)}
          className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.8125rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span>Sin asistente</span>
          <span
            aria-hidden="true"
            className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors ${
              withoutAgent ? "bg-[var(--accent-primary)]" : "bg-[var(--border-subtle)]"
            }`}
          >
            <span
              className={`inline-block h-3 w-3 transform rounded-full bg-[var(--surface-card)] shadow-xs transition-transform ${
                withoutAgent ? "translate-x-3.5" : "translate-x-0.5"
              }`}
            />
          </span>
        </button>
      </div>

      {/* Collapsed-by-default decision trace */}
      {agentRun && traceOpen && (
        <div className="flex min-w-0 flex-col gap-2.5">
          <p className="min-w-0 text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
            Política: <span className="font-semibold text-[var(--ink-primary)]">{agentRun.policy_name}</span>
            {agentRun.model_name ? ` · ${agentRun.model_name}` : ""}
            {` · ${Math.round(agentRun.total_latency_ms)} ms`}
          </p>

          {agentRun.steps.length === 0 ? (
            <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
              El plan inicial ya cubría toda la lista sin pasos adicionales.
            </p>
          ) : (
            <ol className="flex min-w-0 flex-col gap-2.5">
              {agentRun.steps.map((step) => (
                <StepCard key={step.step_number} step={step} />
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
