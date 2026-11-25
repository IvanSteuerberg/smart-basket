import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AgentRunResponse, BasketLine, BasketStore, Recommendation } from "../api";
import type { StoredOrigin } from "../storage";
import {
  BasketStep,
  formatBoughtLine,
  formatStoreHeading,
  shouldShowBrand,
  type BasketStepProps,
} from "./BasketStep";

// Leaflet needs a browser; the step only embeds the map.
vi.mock("./MapView", () => ({ MapView: () => <div data-map="" /> }));

const ORIGIN: StoredOrigin = { lat: 42.5987, lon: -5.5671, label: "Av. de Ordoño II 10, León" };

function line(overrides: Partial<BasketLine> = {}): BasketLine {
  return {
    line_id: 0,
    text: "1 kg de plátanos",
    product_id: 101,
    canonical_id: 11,
    exact_only: false,
    product_name: "Plátano de Canarias",
    brand: null,
    image_url: null,
    packs: 1,
    quantity_bought: "1",
    cost: "1.99",
    ...overrides,
  };
}

function store(overrides: Partial<BasketStore> = {}): BasketStore {
  return {
    store_id: 1,
    name: "Alimerka",
    chain: "Alimerka",
    address: "Av. de Ordoño II 28",
    lat: 42.5989,
    lon: -5.5672,
    position: 1,
    lines: [line()],
    subtotal: "1.99",
    ...overrides,
  };
}

function sampleRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: 1,
    data_as_of: "2026-11-20T10:00:00",
    engine_version: "1",
    stores: [store()],
    total_cost: "16.96",
    minutes: "12",
    missing: [],
    route: [
      [42.5987, -5.5671],
      [42.5989, -5.5672],
    ],
    explanation: "Dos tiendas a pie: lo más barato con tu lista.",
    degraded: false,
    flex_savings: null,
    ...overrides,
  };
}

function sampleAgentRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    run_id: "run-1",
    recommendation_id: "1",
    status: "completed",
    policy_name: "default",
    model_name: null,
    steps_count: 0,
    total_latency_ms: 120,
    buyer_summary: "He afinado tu plan con el asistente.",
    pending_question: null,
    alternatives_shown: [],
    mode: "walk",
    excluded_chains: [],
    recommendation: null,
    steps: [],
    ...overrides,
  };
}

function render(overrides: Partial<BasketStepProps> = {}): string {
  return renderToStaticMarkup(
    <BasketStep
      recommendation={sampleRecommendation()}
      origin={ORIGIN}
      onBack={() => undefined}
      onNewList={() => undefined}
      onApplyAnyBrand={() => undefined}
      onChangeProduct={() => undefined}
      {...overrides}
    />,
  );
}

const BANNED_PATTERNS: [string, RegExp][] = [
  ["transition-all", /transition-all/],
  ["transition: all", /transition:\s*all/],
  ["bg-white", /bg-white/],
  ["bg-stone-*", /bg-stone-/],
  ["text-slate-*", /text-slate-/],
  ["hardcoded green", /#2f6f4e/i],
  ["em dash", /—/],
  ["spaced en dash", / – /],
];

describe("BasketStep", () => {
  it("is titled «Tu plan de compra» with a big tabular total (M1)", () => {
    const html = render();
    expect(html).toContain("Tu plan de compra");
    expect(html).not.toContain("Tu cesta");
    expect(html).toMatch(/tabular-nums[^>]*>.*16,96 €/s);
  });

  it("aligns the total to the left below 640px and to the right above (A6)", () => {
    const html = render();
    expect(html).toMatch(/text-left tabular-nums[^>]*sm:text-right/);
  });

  it("shields every row that can squeeze with min-w-0 (A6)", () => {
    const html = render();
    const rows = html.match(/class="[^"]*\bflex\b[^"]*justify-between[^"]*"/g) ?? [];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) expect(row).toContain("min-w-0");
  });

  it("keeps every control at least 44px tall", () => {
    const html = render();
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toContain("min-h-11");
  });

  it("shows the store heading without a duplicated chain name (B4)", () => {
    const html = render();
    expect(html).toContain("1. Alimerka");
    expect(html).not.toContain("Alimerka – Alimerka");

    const carrefour = render({
      recommendation: sampleRecommendation({
        stores: [store({ name: "Espacio León", chain: "Carrefour" })],
      }),
    });
    expect(carrefour).toContain("1. Carrefour, Espacio León");
  });

  it("shows one summary, never the buyer summary and the explanation twice (M5)", () => {
    const explanation = "Dos tiendas a pie: lo más barato con tu lista.";
    const summary = "He afinado tu plan con el asistente.";

    const withAgent = render({ agentRun: sampleAgentRun({ buyer_summary: summary }) });
    expect(withAgent.match(new RegExp(summary, "g")) ?? []).toHaveLength(1);
    expect(withAgent).not.toContain(explanation);

    const withoutAgentToggle = render({
      agentRun: sampleAgentRun({ buyer_summary: summary }),
      withoutAgent: true,
      onToggleWithoutAgent: () => undefined,
    });
    expect(withoutAgentToggle).toContain(explanation);
    expect(withoutAgentToggle).not.toContain(summary);

    const noAgent = render();
    expect(noAgent.match(new RegExp(explanation, "g")) ?? []).toHaveLength(1);
  });

  it("prints the bought amount naturally: no «envase» on bulk fruit (B13)", () => {
    const html = render();
    expect(html).toContain("1 kg de plátanos");
    expect(html).not.toContain("envase");
  });

  it("shows the brand only when the product name does not carry it (B4)", () => {
    const withBrand = render({
      recommendation: sampleRecommendation({
        stores: [
          store({
            lines: [
              line({ product_name: "Leche semidesnatada Hacendado", brand: "Hacendado" }),
              line({ product_name: "Leche entera", brand: "Pascual", text: "1 l" }),
            ],
          }),
        ],
      }),
    });
    expect(withBrand).not.toContain("· Hacendado");
    expect(withBrand).toContain("· Pascual");
  });

  it.each(BANNED_PATTERNS)("never uses %s", (_name, pattern) => {
    expect(render({ agentRun: sampleAgentRun() })).not.toMatch(pattern);
  });
});

describe("formatStoreHeading (B4)", () => {
  it("drops the chain when the store name already is the chain", () => {
    expect(formatStoreHeading(1, "Alimerka", "Alimerka")).toBe("1. Alimerka");
    expect(formatStoreHeading(2, "Carrefour", "Carrefour")).toBe("2. Carrefour");
  });

  it("keeps both when the name adds something the chain lacks", () => {
    expect(formatStoreHeading(1, "Carrefour", "Espacio León")).toBe("1. Carrefour, Espacio León");
    expect(formatStoreHeading(3, "Mercadona", "Av. de Ordoño II 28")).toBe(
      "3. Mercadona, Av. de Ordoño II 28",
    );
  });

  it("folds case and accents when comparing", () => {
    expect(formatStoreHeading(1, "Alimerka", "ALIMERKA Av. de Ordoño")).toBe(
      "1. ALIMERKA Av. de Ordoño",
    );
    expect(formatStoreHeading(1, "Día", "DIA Ramón y Cajal")).toBe("1. DIA Ramón y Cajal");
  });

  it("falls back to the chain when the name is empty", () => {
    expect(formatStoreHeading(1, "Gadis", "  ")).toBe("1. Gadis");
  });

  it("never joins names with a dash", () => {
    for (const chain of ["Alimerka", "Carrefour", "E.Leclerc"]) {
      expect(formatStoreHeading(1, chain, "Sucursal centro")).not.toMatch(/–|—/);
    }
  });
});

describe("shouldShowBrand (B4)", () => {
  it("hides the brand already inside the product name, insensitive to case and accents", () => {
    expect(shouldShowBrand("Leche semidesnatada Hacendado", "Hacendado")).toBe(false);
    expect(shouldShowBrand("Leche HACENDADO 1 l", "Hacendado")).toBe(false);
    expect(shouldShowBrand("Jamon serrano gran reserva", "Jamón Serrano")).toBe(false);
  });

  it("shows a brand the product name does not carry", () => {
    expect(shouldShowBrand("Leche entera", "Pascual")).toBe(true);
  });

  it("hides an empty brand", () => {
    expect(shouldShowBrand("Leche entera", null)).toBe(false);
    expect(shouldShowBrand("Leche entera", "   ")).toBe(false);
  });
});

describe("formatBoughtLine (B13)", () => {
  it("keeps the clean weight text for bulk fruit, without «envase»", () => {
    expect(formatBoughtLine({ text: "1 kg de plátanos", packs: 1, quantity_bought: "1.23" })).toBe(
      "1 kg de plátanos",
    );
    expect(formatBoughtLine({ text: "medio kilo de tomates", packs: 1, quantity_bought: "0.5" })).toBe(
      "medio kilo de tomates",
    );
  });

  it("treats a fractional bought amount as bulk even without a unit in the text", () => {
    expect(formatBoughtLine({ text: "plátanos", packs: 1, quantity_bought: "1.23" })).toBe(
      "plátanos",
    );
  });

  it("counts the packs of packaged products", () => {
    expect(formatBoughtLine({ text: "3 yogures", packs: 2, quantity_bought: "2" })).toBe(
      "2 envases",
    );
    expect(formatBoughtLine({ text: "1 docena de huevos", packs: 1, quantity_bought: "12" })).toBe(
      "1 envase",
    );
    expect(formatBoughtLine({ text: "2 l de leche", packs: 2, quantity_bought: "2" })).toBe(
      "2 envases",
    );
  });

  it("falls back to the bought amount when the text is empty and the line is bulk", () => {
    expect(formatBoughtLine({ text: "", packs: 1, quantity_bought: "1.5" })).toBe("1,5");
  });

  it("treats a missing pack count as a single pack", () => {
    expect(formatBoughtLine({ text: "pan de molde", packs: 0, quantity_bought: "1" })).toBe(
      "1 envase",
    );
  });
});
