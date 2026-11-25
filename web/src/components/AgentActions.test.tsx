import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentRunResponse } from "../api";
import {
  AgentActions,
  CHANGE_EXAMPLES,
  optionLabelWithPrice,
  type AgentActionsProps,
} from "./AgentActions";

function waitingRun(options: unknown[]): AgentRunResponse {
  return {
    run_id: "run-1",
    recommendation_id: "1",
    status: "waiting_shopper",
    policy_name: "default",
    model_name: null,
    steps_count: 0,
    total_latency_ms: 10,
    buyer_summary: null,
    pending_question: {
      line_index: 0,
      prompt: "¿Qué plátanos prefieres?",
      options: options as NonNullable<AgentRunResponse["pending_question"]>["options"],
    },
    alternatives_shown: [],
    mode: "walk",
    excluded_chains: [],
    recommendation: null,
    steps: [],
  };
}

function sampleRun(): AgentRunResponse {
  return waitingRun([]);
}

function render(overrides: Partial<AgentActionsProps> = {}): string {
  return renderToStaticMarkup(
    <AgentActions
      agentRun={sampleRun()}
      loading={false}
      withoutAgent={false}
      onAnswerQuestion={() => undefined}
      onRequestChange={() => false}
      {...overrides}
    />,
  );
}

describe("AgentActions", () => {
  it("asks the pending question at body size with clickable option buttons (C3)", () => {
    const html = render({
      agentRun: waitingRun([
        { label: "Plátano de Canarias", price: "1.99", canonical_id: 11 },
        { label: "Plátano pequeño", price: "1.55" },
      ]),
    });
    expect(html).toContain("¿Qué plátanos prefieres?");
    expect(html).toContain("Plátano de Canarias · 1,99 €");
    expect(html).toContain("Plátano pequeño · 1,55 €");
    const optionButtons = html.match(/<button[^>]*>Plátano[^<]*<\/button>/g) ?? [];
    expect(optionButtons.length).toBe(2);
    for (const button of optionButtons) expect(button).toContain("min-h-11");
  });

  it("always offers a compact free answer next to the options (C3)", () => {
    const html = render({
      agentRun: waitingRun([{ label: "Plátano de Canarias" }]),
    });
    expect(html).toMatch(/aria-label="Respuesta al asistente"/);
    expect(html).toContain(">Responder<");
    expect(html).toMatch(/placeholder="O escribe tu respuesta…"/);
  });

  it("has a «Pide un cambio» form with a full-height input and send button (C3)", () => {
    const html = render();
    expect(html).toContain("Pide un cambio");
    expect(html).toMatch(/<input[^>]*id="agent-change-request"[^>]*min-h-11/);
    expect(html).toContain(">Pedir<");
    const submit = html.match(/<button[^>]*type="submit"[^>]*>Pedir</) ?? [];
    expect(submit.length).toBeGreaterThan(0);
    expect(submit[0]).toContain("min-h-11");
  });

  it("shows quick example chips that discover the agent's abilities (C3)", () => {
    const html = render();
    for (const example of CHANGE_EXAMPLES) {
      expect(html).toContain(`>${example}<`);
    }
    expect(CHANGE_EXAMPLES.length).toBeGreaterThanOrEqual(3);
    expect(CHANGE_EXAMPLES.length).toBeLessThanOrEqual(4);
  });

  it("explains why it is disabled without the agent, at 13px or more", () => {
    const html = render({ withoutAgent: true });
    expect(html).toContain("El asistente de compra está desactivado");
    expect(html).toMatch(/text-\[0\.8125rem\][^>]*>El asistente/);
  });

  it("keeps every control at least 44px tall", () => {
    const html = render({
      agentRun: waitingRun([{ label: "Plátano de Canarias" }]),
    });
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toContain("min-h-11");
  });

  it("never renders tiny 0.7rem or 0.65rem text or banned colours", () => {
    const html = render({ error: "Sin conexión" });
    expect(html).not.toMatch(/text-\[0\.(7|65)rem\]/);
    expect(html).not.toMatch(/transition-all/);
    expect(html).not.toMatch(/bg-white|bg-stone-|text-slate-/);
    expect(html).not.toMatch(/—| – /);
    expect(html).toContain('role="alert"');
  });
});

describe("optionLabelWithPrice", () => {
  it("appends the price when the label lacks it", () => {
    expect(optionLabelWithPrice({ label: "Plátanos", price: "1.99" })).toBe(
      "Plátanos · 1,99 €",
    );
    expect(optionLabelWithPrice({ label: "Plátanos", price: 2 })).toBe("Plátanos · 2,00 €");
  });

  it("keeps a label that already carries its price", () => {
    expect(
      optionLabelWithPrice({ label: "Mantener el plan actual (16,96 €)", price: "16.96" }),
    ).toBe("Mantener el plan actual (16,96 €)");
  });

  it("returns the plain label without a readable price", () => {
    expect(optionLabelWithPrice({ label: "Plátanos" })).toBe("Plátanos");
    expect(optionLabelWithPrice({ label: "Plátanos", price: "n/a" })).toBe("Plátanos");
  });
});
