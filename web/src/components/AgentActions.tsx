import { useState, type FormEvent } from "react";
import type { AgentAnswerRequest, AgentRunResponse } from "../api";

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

/**
 * Follow-up shopper controls for the agent: answers its pending question (option buttons or a
 * free-text fallback) and asks for changes in plain language («Pide un cambio»).
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

  const pendingQuestion =
    agentRun?.status === "waiting_shopper" ? agentRun.pending_question : null;
  const options = pendingQuestion?.options ?? [];
  const questionBusy = loading || answering;
  const changeDisabled = withoutAgent || loading || changeText.trim() === "";

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

  async function handleChangeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = changeText.trim();
    if (message === "" || changeDisabled) return;
    const accepted = await onRequestChange(message);
    if (accepted) setChangeText("");
  }

  return (
    <div className="mt-3 flex flex-col gap-3">
      {pendingQuestion && (
        <div className="rounded-xl border border-brand/30 bg-brand-soft/40 p-3">
          <p className="text-xs font-semibold text-brand-dark">{pendingQuestion.prompt}</p>

          {options.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
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
                  className="rounded-lg border border-brand bg-white px-3 py-1.5 text-xs font-semibold text-brand transition-colors hover:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {option.label}
                </button>
              ))}
            </div>
          ) : (
            <form onSubmit={handleAnswerSubmit} className="mt-2 flex items-center gap-2">
              <input
                type="text"
                value={answerText}
                onChange={(event) => setAnswerText(event.target.value)}
                disabled={questionBusy}
                aria-label="Respuesta al asistente"
                placeholder="Escribe tu respuesta…"
                className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 placeholder:text-stone-400 focus:border-brand focus:outline-hidden disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={questionBusy || answerText.trim() === ""}
                className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
              >
                Responder
              </button>
            </form>
          )}
        </div>
      )}

      <form
        onSubmit={handleChangeSubmit}
        className="rounded-xl border border-stone-200 bg-stone-50/60 p-3"
      >
        <label
          htmlFor="agent-change-request"
          className="block text-xs font-semibold text-slate-700"
        >
          Pide un cambio
        </label>
        <div className="mt-1.5 flex items-center gap-2">
          <input
            id="agent-change-request"
            type="text"
            value={changeText}
            onChange={(event) => setChangeText(event.target.value)}
            disabled={withoutAgent || loading}
            placeholder="Ej.: ¿y si voy en coche?, quita el pan, sin Lidl…"
            className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 placeholder:text-stone-400 focus:border-brand focus:outline-hidden disabled:cursor-not-allowed disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={changeDisabled}
            className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Pensando…" : "Pedir"}
          </button>
        </div>
        {withoutAgent && (
          <p className="mt-1.5 text-[0.7rem] text-stone-500">
            Activa el agente para pedir cambios en texto libre.
          </p>
        )}
      </form>

      {error && (
        <p className="text-xs font-semibold text-price" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
