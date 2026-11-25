import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_ROUTE_OPTIONS } from "../storage";
import { OriginStep, originSummary, type OriginStepProps } from "./OriginStep";

// Leaflet needs a browser; the step only embeds the map.
vi.mock("./MapView", () => ({ MapView: () => <div data-map="" /> }));

const ORIGIN = { lat: 42.6, lon: -5.57, label: "Av. de Ordoño II" };

function render(overrides: Partial<OriginStepProps> = {}): string {
  return renderToStaticMarkup(
    <OriginStep
      origin={ORIGIN}
      onOriginChange={() => undefined}
      options={DEFAULT_ROUTE_OPTIONS}
      onOptionsChange={() => undefined}
      open
      onToggleOpen={() => undefined}
      {...overrides}
    />,
  );
}

describe("OriginStep", () => {
  it("folds into one row with the origin, the mode and the store limit", () => {
    const html = render({ open: false });
    expect(html).toContain("Desde: Av. de Ordoño II · A pie · Hasta 2 tiendas");
    expect(html).toMatch(/min-h-11[^>]*>Cambiar</);
    expect(html).not.toContain("data-map");
  });

  it("opens by itself when there is no origin yet", () => {
    const html = render({ origin: null, open: false });
    expect(html).toContain("¿Desde dónde sales?");
    expect(html).toContain("data-map");
  });

  it("keeps the chosen address visible in the search field (B6)", () => {
    const html = render();
    expect(html).toMatch(/type="search"[^>]*value="Av\. de Ordoño II"|value="Av\. de Ordoño II"[^>]*type="search"/);
  });

  it("uses connected segmented groups for mode, stores and priority", () => {
    const html = render();
    expect(html.match(/role="group"/g)).toHaveLength(3);
    for (const label of ["A pie", "En coche", "Ahorrar", "Equilibrado", "Tiempo"]) {
      expect(html).toMatch(new RegExp(`aria-pressed="(true|false)"[^>]*>${label}<`));
    }
    for (const count of ["1", "2", "3"]) {
      expect(html).toMatch(new RegExp(`aria-pressed="(true|false)"[^>]*>${count}<`));
    }
    expect(html).toMatch(/aria-pressed="true"[^>]*>2</);
    expect(html).not.toContain('type="radio"');
    expect(html).not.toMatch(/<select/);
  });

  it("offers the round trip as a touch-sized checkbox", () => {
    const html = render();
    expect(html).toMatch(/<label[^>]*min-h-11[^>]*>.*Volver al punto de salida<\/label>/);
    expect(html).toContain("checked");
  });

  it("keeps every button at least 44px tall and avoids legacy colors", () => {
    const html = render();
    for (const button of html.match(/<button[^>]*>/g) ?? []) {
      expect(button).toContain("min-h-11");
    }
    expect(html).not.toMatch(/transition-all|bg-white|bg-stone-|text-slate-|#2f6f4e/);
  });
});

describe("originSummary", () => {
  it("agrees «tienda» with the limit", () => {
    expect(originSummary(ORIGIN, { ...DEFAULT_ROUTE_OPTIONS, maxStores: 1, mode: "car" })).toBe(
      "Desde: Av. de Ordoño II · En coche · Hasta 1 tienda",
    );
  });
});
