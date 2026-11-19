import { useState, type ReactNode } from "react";
import type { AgentRunResponse, AgentStep } from "../api";
import { formatEuro, formatMinutes } from "../format";

export interface AgentTracePanelProps {
  agentRun: AgentRunResponse | null;
  loading?: boolean;
  withoutAgent: boolean;
  onToggleWithoutAgent: (next: boolean) => void;
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

function parseAlternativePlan(alt: Record<string, unknown>): {
  storesText: string;
  modeLabel: string | null;
  costText: string | null;
  minutesText: string | null;
} {
  const rawStores = Array.isArray(alt.store_names)
    ? alt.store_names
    : Array.isArray(alt.stores)
      ? alt.stores
      : [];
  const storeNames = rawStores.filter((item): item is string => typeof item === "string" && item.trim() !== "");
  const storesText = storeNames.length > 0 ? storeNames.join(", ") : "Plan alternativo";

  const rawMode = typeof alt.mode === "string" ? alt.mode : null;
  const modeLabel = rawMode ? (MODE_LABELS[rawMode] ?? rawMode) : null;

  const costText = isDecimalLike(alt.total_cost) ? formatEuro(alt.total_cost) : null;

  const rawMinutes = alt.travel_minutes ?? alt.minutes;
  const minutesText = isDecimalLike(rawMinutes) ? `${formatMinutes(rawMinutes)} min` : null;

  return { storesText, modeLabel, costText, minutesText };
}

function StepCard({ step }: { step: AgentStep }) {
  const observationKind = step.observation?.kind ?? "paso";
  const observationLabel = OBSERVATION_LABELS[observationKind] ?? observationKind;

  return (
    <li className="rounded-xl border border-stone-200 bg-stone-50/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-bold text-slate-900">Paso {step.step_number}</span>
          <span className="rounded-full bg-stone-200/80 px-2 py-0.5 text-[0.7rem] font-semibold text-stone-700">
            {observationLabel}
          </span>
          {step.used_default && (
            <span className="rounded-full bg-price-soft px-2 py-0.5 text-[0.7rem] font-semibold text-price">
              Por defecto
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 text-[0.7rem] text-stone-500">
          {step.confidence !== null && (
            <span className="rounded-full bg-brand-soft px-2 py-0.5 font-semibold text-brand-dark">
              Confianza {formatPercent(step.confidence)}
            </span>
          )}
          <span className="tabular-nums">{Math.round(step.latency_ms)} ms</span>
        </div>
      </div>

      {step.observation?.summary && (
        <p className="mt-1.5 text-xs text-slate-700">{step.observation.summary}</p>
      )}

      {step.candidates.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5" aria-label="Opciones evaluadas">
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
                    ? "rounded-lg border border-brand bg-brand-soft/60 px-2.5 py-1.5 text-xs text-brand-dark"
                    : "rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-slate-700"
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={isChosen ? "font-semibold" : "font-medium"}>
                    {isChosen ? `✓ ${candidate.label}` : candidate.label}
                  </span>
                  {hasProb && (
                    <span className="shrink-0 tabular-nums text-[0.7rem] font-semibold">
                      {percent} %
                    </span>
                  )}
                </div>
                {hasProb && (
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-stone-200/80">
                    <div
                      className={isChosen ? "h-full rounded-full bg-brand" : "h-full rounded-full bg-stone-400"}
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
        <p className="mt-2 text-xs text-stone-600">
          <span className="font-semibold text-slate-700">Resultado:</span> {step.result.summary}
        </p>
      )}

      {step.error && (
        <p className="mt-1.5 text-xs font-semibold text-price" role="status">
          {step.error}
        </p>
      )}
    </li>
  );
}

/**
 * Displays the recommender agent's buyer summary, alternative plans, the «Sin agente»
 * comparison toggle, and the collapsed-by-default «Cómo lo ha decidido» decision trace.
 */
export function AgentTracePanel({
  agentRun,
  loading = false,
  withoutAgent,
  onToggleWithoutAgent,
  children,
}: AgentTracePanelProps) {
  const [traceOpen, setTraceOpen] = useState(false);

  // Follow-up controls (e.g. «Pide un cambio») stay available even if the agent failed.
  if (!agentRun && !loading && !children) {
    return null;
  }

  const summaryText = agentRun?.buyer_summary?.trim()
    ? agentRun.buyer_summary
    : loading
      ? "Revisando tu cesta con el asistente…"
      : withoutAgent
        ? "Plan base sin agente."
        : "Asistente de compra";

  return (
    <section
      aria-label="Asistente de compra"
      className="mb-4 rounded-2xl border border-stone-200 bg-white p-3.5 shadow-xs"
    >
      {/* Buyer summary line + Sin agente toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm font-medium text-slate-800">{summaryText}</p>

        <button
          type="button"
          role="switch"
          aria-checked={withoutAgent}
          disabled={loading}
          onClick={() => onToggleWithoutAgent(!withoutAgent)}
          className="inline-flex shrink-0 items-center gap-2 rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition-colors hover:border-stone-300 hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span>Sin agente</span>
          <span
            aria-hidden="true"
            className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${
              withoutAgent ? "bg-brand" : "bg-stone-300"
            }`}
          >
            <span
              className={`inline-block h-3 w-3 transform rounded-full bg-white shadow-xs transition-transform ${
                withoutAgent ? "translate-x-3.5" : "translate-x-0.5"
              }`}
            />
          </span>
        </button>
      </div>

      {children}

      {/* Alternative plans shown by the agent */}
      {agentRun && agentRun.alternatives_shown.length > 0 && (
        <div className="mt-3 border-t border-stone-100 pt-3">
          <h3 className="text-[0.7rem] font-bold uppercase tracking-wide text-stone-500">
            Alternativas comparadas
          </h3>
          <ul className="mt-1.5 flex flex-col gap-1.5">
            {agentRun.alternatives_shown.map((alt, index) => {
              const { storesText, modeLabel, costText, minutesText } = parseAlternativePlan(alt);
              return (
                <li
                  key={index}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-stone-200 bg-stone-50/70 px-3 py-2 text-xs"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {modeLabel && (
                      <span className="shrink-0 rounded-full bg-brand-soft px-2 py-0.5 text-[0.65rem] font-semibold text-brand-dark">
                        {modeLabel}
                      </span>
                    )}
                    <span className="truncate font-semibold text-slate-800">{storesText}</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-2.5 tabular-nums">
                    {costText && <span className="font-bold text-slate-900">{costText}</span>}
                    {minutesText && <span className="text-stone-500">{minutesText}</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Collapsed-by-default decision trace */}
      {agentRun && (
        <div className="mt-3 border-t border-stone-100 pt-2.5">
          <button
            type="button"
            aria-expanded={traceOpen}
            onClick={() => setTraceOpen((prev) => !prev)}
            className="flex w-full items-center justify-between text-left text-xs font-semibold text-brand hover:text-brand-dark"
          >
            <span>
              Cómo lo ha decidido
              {agentRun.steps.length > 0 ? ` (${agentRun.steps.length})` : ""}
            </span>
            <span aria-hidden="true" className="text-stone-400">
              {traceOpen ? "▲" : "▼"}
            </span>
          </button>

          {traceOpen && (
            <div className="mt-3 flex flex-col gap-2.5">
              <p className="text-[0.7rem] text-stone-500">
                Política: <span className="font-semibold text-slate-700">{agentRun.policy_name}</span>
                {agentRun.model_name ? ` · ${agentRun.model_name}` : ""}
                {` · ${Math.round(agentRun.total_latency_ms)} ms`}
              </p>

              {agentRun.steps.length === 0 ? (
                <p className="text-xs text-stone-500">
                  El plan inicial ya cubría toda la lista sin pasos adicionales.
                </p>
              ) : (
                <ol className="flex flex-col gap-2.5">
                  {agentRun.steps.map((step) => (
                    <StepCard key={step.step_number} step={step} />
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
