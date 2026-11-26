import { useState, type FormEvent } from "react";
import type { AgentAnswerRequest, AgentPendingOption, AgentRunResponse } from "../api";
import { formatEuro, parseDecimal } from "../format";

export interface AgentActionsProps {
  agentRun: AgentRunResponse | null;
  loading: boolean;
  withoutAgent: boolean;
  error?: string | null;
  /** Sends the shopper's reply to the agent's pending question. */
  onAnswerQuestion: (answer: AgentAnswerRequest) => void | Promise<void>;
  /** Sends a free-text change request; resolves to true when the agent accepted it. */
  onRequestChange: (message: string) => boolean | Promise<boolean>;
}

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3.5 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS;
const PRIMARY =
  "inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS;
const INPUT =
  "min-h-11 w-full min-w-0 flex-1 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 font-sans text-[0.9375rem] text-[var(--ink-primary)] outline-none focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50";

/** Chips that show what the agent can do (C3); each one sends its request directly. */
export const CHANGE_EXAMPLES = [
  "Solo 1 tienda",
  "En coche",
  "Explicar el plan",
  "Sin Lidl",
] as const;

/** «Mantener el plan actual (16,96 €)» already carries its price; «Plátanos» may add one. */
export function optionLabelWithPrice(option: AgentPendingOption): string {
  const price = option.price;
  if (typeof price !== "string" && typeof price !== "number") return option.label;
  if (!Number.isFinite(parseDecimal(price))) return option.label;
  const euro = formatEuro(price);
  if (euro === "" || option.label.includes(euro)) return option.label;
  return `${option.label} · ${euro}`;
}

/**
 * Follow-up shopper controls for the agent: answers its pending question with clickable
 * options or free text, and asks for changes in plain language («Pide un cambio») with quick
 * example chips that make the agent's abilities discoverable (C3).
 */
export function AgentActions({
  agentRun,
  loading,
  withoutAgent,
  error = null,
  onAnswerQuestion,
  onRequestChange,
}: AgentActionsProps) {
  const [answerText, setAnswerText] = useState("");
  const [changeText, setChangeText] = useState("");
  const [answering, setAnswering] = useState(false);
  const [applyingExample, setApplyingExample] = useState(false);

  const pendingQuestion =
    agentRun?.status === "waiting_shopper" ? agentRun.pending_question : null;
  const options = pendingQuestion?.options ?? [];
  const questionBusy = loading || answering;
  const changeBusy = loading || applyingExample;
  const changeDisabled = withoutAgent || changeBusy || changeText.trim() === "";

  async function submitAnswer(answer: AgentAnswerRequest) {
    if (questionBusy) return;
    setAnswering(true);
    try {
      await onAnswerQuestion(answer);
      setAnswerText("");
    } finally {
      setAnswering(false);
    }
  }

  function handleAnswerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = answerText.trim();
    if (message === "") return;
    void submitAnswer({ message });
  }

  async function requestChange(message: string): Promise<void> {
    const accepted = await onRequestChange(message);
    if (accepted) setChangeText("");
  }

  async function handleChangeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = changeText.trim();
    if (message === "" || changeDisabled) return;
    await requestChange(message);
  }

  async function handleExampleChip(message: string) {
    if (withoutAgent || changeBusy) return;
    setChangeText(message);
    setApplyingExample(true);
    try {
      await requestChange(message);
    } finally {
      setApplyingExample(false);
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {pendingQuestion && (
        <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-[var(--accent-soft)] p-3.5">
          <p className="min-w-0 text-[0.9375rem] font-semibold text-[var(--ink-primary)]">
            {pendingQuestion.prompt}
          </p>

          {options.length > 0 && (
            <div className="flex min-w-0 flex-wrap gap-2">
              {options.map((option, index) => (
                <button
                  key={`${option.label}-${index}`}
                  type="button"
                  disabled={questionBusy}
                  onClick={() =>
                    void submitAnswer({
                      option_index: index,
                      choice_label: option.label,
                      canonical_id: option.canonical_id ?? null,
                    })
                  }
                  className={BUTTON}
                >
                  {optionLabelWithPrice(option)}
                </button>
              ))}
            </div>
          )}

          {/* A compact free answer, for anything the options do not cover. */}
          <form onSubmit={handleAnswerSubmit} className="flex min-w-0 items-center gap-2">
            <input
              type="text"
              value={answerText}
              onChange={(event) => setAnswerText(event.target.value)}
              disabled={questionBusy}
              aria-label="Respuesta al asistente"
              placeholder="O escribe tu respuesta…"
              className={INPUT}
            />
            <button
              type="submit"
              disabled={questionBusy || answerText.trim() === ""}
              className={`${PRIMARY} shrink-0`}
            >
              Responder
            </button>
          </form>
        </div>
      )}

      <form
        onSubmit={handleChangeSubmit}
        className="flex min-w-0 flex-col gap-2 rounded-xl bg-[var(--surface-elevated)] p-3.5"
      >
        <label
          htmlFor="agent-change-request"
          className="min-w-0 text-[0.9375rem] font-semibold text-[var(--ink-primary)]"
        >
          Pide un cambio
        </label>
        <div className="flex min-w-0 items-center gap-2">
          <input
            id="agent-change-request"
            type="text"
            value={changeText}
            onChange={(event) => setChangeText(event.target.value)}
            disabled={withoutAgent || loading}
            placeholder="Ej.: ¿y si voy en coche?, quita el pan, sin Lidl…"
            className={INPUT}
          />
          <button type="submit" disabled={changeDisabled} className={`${PRIMARY} shrink-0`}>
            {loading ? "Pensando…" : "Pedir"}
          </button>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          {CHANGE_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              disabled={withoutAgent || changeBusy}
              onClick={() => void handleExampleChip(example)}
              className={BUTTON}
            >
              {example}
            </button>
          ))}
        </div>
        {withoutAgent && (
          <p className="min-w-0 text-[0.8125rem] text-[var(--ink-secondary)]">
            El asistente de compra está desactivado. Desactiva «Sin asistente» para pedir
            cambios con texto libre.
          </p>
        )}
      </form>

      {error && (
        <p className="min-w-0 text-[0.9375rem] font-semibold text-[var(--danger-fg)]" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
