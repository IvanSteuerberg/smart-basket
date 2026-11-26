import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { UnifiedLine } from "../listStore";
import { DEFAULT_ROUTE_OPTIONS } from "../storage";
import { ListStep, optionPatch, wholeQuantity, type ListStepProps } from "./ListStep";

// Leaflet needs a browser; the list screen only embeds the origin bar.
vi.mock("./MapView", () => ({ MapView: () => <div data-map="" /> }));
// ProductImage is restyled in another delivery; keep its markup out of the design checks here.
vi.mock("./ProductImage", () => ({ ProductImage: () => <span data-image="" /> }));

const ORIGIN = { lat: 42.6, lon: -5.57, label: "Av. de Ordoño II" };

function line(overrides: Partial<UnifiedLine> = {}): UnifiedLine {
  return {
    id: "l1",
    text: "Leche entera Hacendado",
    categoryKey: "leche-entera",
    categoryName: "Leche entera",
    productId: 7,
    brand: "Hacendado",
    packaging: "1 l",
    imageUrl: null,
    quantity: "1",
    unit: "ud",
    privateLabelOk: true,
    pinBrand: true,
    exactOnly: false,
    options: [],
    ...overrides,
  };
}

const VAGUE = line({
  id: "vague",
  text: "pollo",
  categoryKey: null,
  categoryName: "",
  productId: null,
  brand: "",
  pinBrand: false,
  options: [
    { category_key: "pollo-entero", name: "Pollo entero", image_url: null, from_unit_price: "4.5", base_unit: "kg", exact_only: false },
  ],
});

function render(overrides: Partial<ListStepProps> = {}): string {
  return renderToStaticMarkup(
    <ListStep
      lines={[line()]}
      anyBrand={false}
      onAnyBrandChange={() => undefined}
      onUpdateLine={() => undefined}
      onRemoveLine={() => undefined}
      onSetPinBrand={() => undefined}
      onChooseInCatalog={() => undefined}
      text=""
      onTextChange={() => undefined}
      onAddText={() => undefined}
      onCalculate={() => undefined}
      calculating={false}
      interpreting={false}
      interpretError={null}
      calcError={null}
      degraded={false}
      notice={null}
      lists={[]}
      onSaveList={() => undefined}
      onLoadList={() => undefined}
      onRenameList={() => undefined}
      onDeleteList={() => undefined}
      origin={ORIGIN}
      onOriginChange={() => undefined}
      options={DEFAULT_ROUTE_OPTIONS}
      onOptionsChange={() => undefined}
      originOpen={false}
      onToggleOriginOpen={() => undefined}
      {...overrides}
    />,
  );
}

describe("ListStep", () => {
  it("puts the origin bar above the lines", () => {
    const html = render();
    expect(html.indexOf("Desde: Av. de Ordoño II")).toBeGreaterThan(-1);
    expect(html.indexOf("Desde: Av. de Ordoño II")).toBeLessThan(html.indexOf("Tu lista"));
  });

  it("shows the lines with their unit spelled out and a single brand control", () => {
    const html = render();
    expect(html).toContain("Leche entera Hacendado");
    expect(html).toMatch(/aria-pressed="true"[^>]*>Solo esta marca</);
    expect(html).not.toContain("Este producto");
    expect(html).not.toContain("Fijar este producto");
    expect(html).toContain("Cantidad de Leche entera Hacendado: 1 envase");
  });

  it("offers a unit selector on generic lines", () => {
    const html = render({
      lines: [line({ productId: null, text: "leche", quantity: "2", unit: "l", brand: "" })],
    });
    expect(html).toMatch(/<select[^>]*aria-label="Unidad"/);
    for (const unit of ["ud", "kg", "g", "l", "ml"]) expect(html).toContain(`>${unit}</option>`);
    expect(html).toContain("2 l");
    expect(html).toContain("Cualquier marca");
  });

  it("has the global switch and the add and calculate buttons", () => {
    const html = render({ anyBrand: true });
    expect(html).toMatch(/aria-checked="true"/);
    expect(html).toContain("Me da igual la marca");
    expect(html).toContain(">Añadir a la lista<");
    expect(html).toContain(">Calcular plan<");
  });

  it("marks lines to resolve and warns with the right number after an attempt (A5)", () => {
    const html = render({
      lines: [line(), VAGUE],
      notice: { kind: "unresolved", tick: 1 },
    });
    expect(html).toContain("data-unresolved");
    expect(html).toMatch(/role="alert"[^>]*>Resuelve la línea marcada antes de calcular tu plan\.</);
    expect(html).toContain("¿Qué pollo?");
    const two = render({
      lines: [VAGUE, { ...VAGUE, id: "v2" }],
      notice: { kind: "unresolved", tick: 1 },
    });
    expect(two).toContain("Resuelve las 2 líneas marcadas antes de calcular tu plan.");
  });

  it("does not warn before any attempt", () => {
    expect(render({ lines: [VAGUE] })).not.toContain("Resuelve");
  });

  it("asks for the origin when it is missing", () => {
    const html = render({ origin: null, notice: { kind: "origin", tick: 1 } });
    expect(html).toContain("Indica desde dónde sales para calcular tu plan.");
    expect(html).toContain("¿Desde dónde sales?");
  });

  it("writes the free text with the page font", () => {
    const html = render({ text: "pan" });
    const textarea = /<textarea[^>]*>/.exec(html)?.[0] ?? "";
    expect(textarea).toContain("font-sans");
    expect(textarea).not.toMatch(/font-mono/);
  });

  it("opens the saved lists dialog instead of using window.prompt", () => {
    const html = render();
    expect(html).toContain(">Listas guardadas<");
    expect(html).toMatch(/<dialog /);
    expect(html).not.toMatch(/window\.prompt|window\.confirm/);
  });

  it("keeps touch targets and design rules", () => {
    const html = render({ lines: [line(), VAGUE] });
    for (const button of html.match(/<button[^>]*>/g) ?? []) {
      expect(button).toContain("min-h-11");
    }
    expect(html).not.toMatch(/transition-all|bg-white|bg-stone-|text-slate-|#2f6f4e|—| – /);
  });
});

describe("helpers", () => {
  it("turns a chosen option into the fields of a resolved line", () => {
    expect(
      optionPatch({
        category_key: "pollo-entero",
        name: "Pollo entero",
        image_url: null,
        from_unit_price: null,
        base_unit: null,
        exact_only: false,
      } as never),
    ).toEqual({
      categoryKey: "pollo-entero",
      categoryName: "Pollo entero",
      imageUrl: null,
      options: [],
      exactOnly: false,
    });
  });

  it("keeps whole units, at least one, when a line is switched to units", () => {
    expect(wholeQuantity("2,6")).toBe("3");
    expect(wholeQuantity("0.2")).toBe("1");
    expect(wholeQuantity("abc")).toBe("1");
  });
});
