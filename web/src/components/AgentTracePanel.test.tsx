import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentRunResponse, AgentStep } from "../api";
import {
  AgentTracePanel,
  alternativeRequestMessage,
  parseAlternativePlan,
  type AgentTracePanelProps,
} from "./AgentTracePanel";

function step(overrides: Partial<AgentStep> = {}): AgentStep {
  return {
    step_number: 1,
    observation: { kind: "shopper_request", summary: "El comprador escribe: «en coche»." },
    candidates: [
      { key: "cambiar_modo", kind: "cambiar_modo", label: "Cambiar a coche" },
      { key: "comparar_escenarios", kind: "comparar_escenarios", label: "Comparar escenarios" },
    ],
    chosen_action: "cambiar_modo",
    action_args: {},
    confidence: 0.72,
    probabilities: { cambiar_modo: 0.72, comparar_escenarios: 0.28 },
    retries: 0,
    used_default: false,
    result: { summary: "Modo cambiado a coche." },
    latency_ms: 142,
    error: null,
    ...overrides,
  };
}

function sampleRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    run_id: "run-1",
    recommendation_id: "1",
    status: "completed",
    policy_name: "gemini_decisions",
    model_name: "gemini-decision-1",
    steps_count: 1,
    total_latency_ms: 142,
    buyer_summary: "Plan revisado con el asistente.",
    pending_question: null,
    alternatives_shown: [],
    mode: "walk",
    excluded_chains: [],
    recommendation: null,
    steps: [],
    ...overrides,
  };
}

function render(overrides: Partial<AgentTracePanelProps> = {}): string {
  return renderToStaticMarkup(
    <AgentTracePanel
      agentRun={sampleRun()}
      withoutAgent={false}
      onToggleWithoutAgent={() => undefined}
      {...overrides}
    />,
  );
}

describe("AgentTracePanel", () => {
  it("never repeats the buyer summary: BasketStep owns it (M5)", () => {
    const html = render();
    expect(html).not.toContain("Plan revisado con el asistente.");
  });

  it("shows the Pareto alternatives with their deltas and reason (M6)", () => {
    const html = render({
      agentRun: sampleRun({
        alternatives_shown: [
          {
            mode: "car",
            store_names: ["Alimerka"],
            chain_codes: ["alimerka"],
            total_cost: "21.10",
            travel_minutes: "6",
            cost_delta: "4.14",
            minutes_delta: "-6",
            reason: "Una sola tienda y en coche.",
          },
        ],
      }),
      onApplyAlternative: () => undefined,
    });
    expect(html).toContain("En coche: Alimerka");
    expect(html).toContain("21,10 € (+4,14 €)");
    expect(html).toContain("6 min (-6 min)");
    expect(html).toContain("Una sola tienda y en coche.");
    expect(html).toContain("Alternativas comparadas");
  });

  it("offers «Usar esta opción» only when the host can apply it (M6)", () => {
    const withApply = render({
      agentRun: sampleRun({
        alternatives_shown: [{ store_names: ["Alimerka"], chain_codes: ["alimerka"] }],
      }),
      onApplyAlternative: () => undefined,
    });
    expect(withApply).toContain(">Usar esta opción<");
    expect(withApply).toMatch(/<button[^>]*>Usar esta opción/);

    const withoutApply = render({
      agentRun: sampleRun({
        alternatives_shown: [{ store_names: ["Alimerka"], chain_codes: ["alimerka"] }],
      }),
    });
    expect(withoutApply).not.toContain("Usar esta opción");
  });

  it("keeps the trace collapsed by default and shows its step count (M6)", () => {
    const html = render({ agentRun: sampleRun({ steps: [step()] }) });
    expect(html).toContain("Cómo lo ha decidido (1)");
    expect(html).toMatch(/aria-expanded="false"/);
    expect(html).not.toContain("Política:");
    expect(html).not.toContain("Paso 1");
  });

  it("hides the trace button only when there is no run to explain", () => {
    const withoutRun = render({
      agentRun: null,
      children: <p>Sin agente</p>,
    });
    expect(withoutRun).not.toContain("Cómo lo ha decidido");
    expect(withoutRun).toContain("Sin asistente");
  });

  it("keeps every control at least 44px tall and free of banned styles", () => {
    const html = render({
      agentRun: sampleRun({
        steps: [step()],
        alternatives_shown: [{ store_names: ["Alimerka"], chain_codes: ["alimerka"] }],
      }),
      onApplyAlternative: () => undefined,
    });
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toContain("min-h-11");
    expect(html).not.toMatch(/transition-all/);
    expect(html).not.toMatch(/bg-white|bg-stone-|text-slate-/);
    expect(html).not.toMatch(/text-\[0\.(7|65)rem\]/);
    expect(html).not.toMatch(/—| – /);
  });
});

describe("parseAlternativePlan", () => {
  it("reads mode, costs, minutes, deltas and reason", () => {
    const view = parseAlternativePlan({
      mode: "car",
      store_names: ["Mercadona", "Alcampo"],
      total_cost: "18.20",
      travel_minutes: "9",
      cost_delta: "1.24",
      minutes_delta: "-3",
      reason: "Cerca de tu casa.",
    });
    expect(view.storesText).toBe("Mercadona, Alcampo");
    expect(view.modeLabel).toBe("En coche");
    expect(view.costText).toBe("18,20 €");
    expect(view.minutesText).toBe("9 min");
    expect(view.costDelta).toBe("+1,24 €");
    expect(view.minutesDelta).toBe("-3 min");
    expect(view.reason).toBe("Cerca de tu casa.");
  });

  it("drops deltas that are missing or zero", () => {
    expect(parseAlternativePlan({ cost_delta: "0" }).costDelta).toBeNull();
    expect(parseAlternativePlan({ minutes_delta: 0 }).minutesDelta).toBeNull();
    expect(parseAlternativePlan({}).costDelta).toBeNull();
    expect(parseAlternativePlan({}).reason).toBeNull();
  });

  it("falls back to a generic title without store names", () => {
    expect(parseAlternativePlan({}).storesText).toBe("Plan alternativo");
  });
});

describe("alternativeRequestMessage", () => {
  it("asks for the mode change when the alternative uses another one", () => {
    expect(alternativeRequestMessage({ mode: "car" }, "walk")).toBe("cambia a coche");
    expect(alternativeRequestMessage({ mode: "walk" }, "car")).toBe("cambia a ir a pie");
    expect(alternativeRequestMessage({ mode: "walk" }, "walk")).not.toContain("cambia");
  });

  it("asks for the single chain by its display name", () => {
    expect(alternativeRequestMessage({ chain_codes: ["alimerka"] }, "walk")).toBe(
      "haz la compra solo en Alimerka",
    );
  });

  it("combines mode and chain in one request", () => {
    expect(
      alternativeRequestMessage({ mode: "car", chain_codes: ["mercadona"] }, "walk"),
    ).toBe("cambia a coche, haz la compra solo en Mercadona");
  });

  it("asks for a multi-chain alternative so both chains are applied", () => {
    expect(
      alternativeRequestMessage({ chain_codes: ["alcampo", "dia"] }, "walk"),
    ).toBe("usa esta opción: haz la compra solo en Alcampo y Dia");
  });

  it("falls back to the store names when there is nothing to switch", () => {
    expect(
      alternativeRequestMessage({ store_names: ["Alimerka", "Mercadona"] }, "walk"),
    ).toBe("usa esta opción: haz la compra en Alimerka y Mercadona");
    expect(alternativeRequestMessage({}, "walk")).toBe("usa esta opción");
  });
});
