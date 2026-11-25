import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { UnifiedLine } from "../listStore";
import {
  CartDrawer,
  isLineResolved,
  lineSubline,
  lineTitle,
  type CartDrawerProps,
} from "./CartDrawer";

// ProductImage is restyled in another delivery; keep its markup out of the design checks here.
vi.mock("./ProductImage", () => ({ ProductImage: () => <span data-image="" /> }));

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
    quantity: "2",
    unit: "ud",
    privateLabelOk: true,
    pinBrand: true,
    exactOnly: false,
    options: [],
    ...overrides,
  };
}

function render(overrides: Partial<CartDrawerProps> = {}): string {
  return renderToStaticMarkup(
    <CartDrawer
      open
      lines={[line()]}
      anyBrand={false}
      chainFilter={null}
      onClose={() => undefined}
      onQuantityChange={() => undefined}
      onSetPinBrand={() => undefined}
      onAnyBrandChange={() => undefined}
      onChainFilterChange={() => undefined}
      onRemove={() => undefined}
      lists={[]}
      onSaveList={() => undefined}
      onLoadList={() => undefined}
      onRenameList={() => undefined}
      onDeleteList={() => undefined}
      onEditList={() => undefined}
      onCalculate={() => undefined}
      {...overrides}
    />,
  );
}

describe("CartDrawer", () => {
  it("is a native dialog labelled by its heading, without redundant ARIA", () => {
    const html = render();
    const drawer = html.slice(0, html.indexOf("</dialog>"));
    expect(drawer).toMatch(/^<dialog /);
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(drawer)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(drawer).toContain(`<h2 id="${labelledBy}"`);
    expect(drawer).not.toContain('role="dialog"');
    expect(drawer).not.toContain("aria-modal");
    expect(drawer).not.toMatch(/<dialog[^>]*class="[^"]*\b(flex|block|grid)\b/);
  });

  it("is a side panel on desktop and a bottom sheet on mobile", () => {
    const html = render();
    const classes = /<dialog[^>]*class="([^"]*)"/.exec(html)?.[1] ?? "";
    for (const expected of [
      "mt-auto",
      "max-h-[85dvh]",
      "rounded-t-2xl",
      "sm:ml-auto",
      "sm:h-dvh",
      "sm:w-[26rem]",
      "sm:rounded-none",
    ]) {
      expect(classes).toContain(expected);
    }
  });

  it("shows the unified list with the agreed unit label and no export or import", () => {
    const html = render();
    expect(html).toContain("Tu lista");
    expect(html).toContain("Leche entera Hacendado");
    expect(html).toContain("2 envases");
    expect(html).not.toContain("Exportar");
    expect(html).not.toContain("Importar");
  });

  it("has one brand control per concrete line, with aria-pressed", () => {
    const pinned = render();
    expect(pinned).toMatch(/aria-pressed="true"[^>]*>Solo esta marca</);
    const loose = render({ lines: [line({ pinBrand: false })] });
    expect(loose).toMatch(/aria-pressed="false"[^>]*>Cualquier marca</);
    expect(loose).not.toContain("Fijar este producto");
    expect(loose).not.toMatch(/<select/);
  });

  it("says a line of shades only sells that product", () => {
    const html = render({ lines: [line({ exactOnly: true })] });
    expect(html).toContain("Solo este producto concreto");
    expect(html).not.toMatch(/aria-pressed="(true|false)"[^>]*>Solo esta marca</);
  });

  it("has the global switch with aria-checked", () => {
    expect(render({ anyBrand: true })).toMatch(
      /role="switch"[^>]*aria-checked="true"|aria-checked="true"[^>]*role="switch"/,
    );
  });

  it("offers the twelve chains as pressed toggles with a logo plate", () => {
    const html = render({ chainFilter: ["mercadona"] });
    const chainButtons = html.match(/<button[^>]*aria-label="[^"]+"[^>]*aria-pressed="(true|false)"[^>]*title=/g) ?? [];
    expect(chainButtons).toHaveLength(12);
    expect(html).toContain('aria-pressed="true"');
  });

  it("keeps Editar lista, Calcular plan and Guardar lista in the footer", () => {
    const html = render();
    expect(html).toContain(">Editar lista<");
    expect(html).toContain(">Calcular plan<");
    expect(html).toContain(">Guardar lista<");
    expect(html).not.toMatch(/window\.prompt/);
  });

  it("disables Calcular plan when the list is empty", () => {
    const html = render({ lines: [] });
    expect(html).toMatch(/disabled=""[^>]*>Calcular plan</);
    expect(html).toContain("Tu lista está vacía");
  });

  it("keeps every drawer button at least 44px tall", () => {
    const html = render();
    const drawer = html.slice(0, html.indexOf("</dialog>"));
    for (const button of drawer.match(/<button[^>]*>/g) ?? []) {
      expect(button).toContain("min-h-11");
    }
  });

  it("uses semantic tokens and no forbidden transitions or colors", () => {
    const html = render();
    expect(html).not.toMatch(/transition-all|bg-white|bg-stone-|text-slate-|#2f6f4e/);
  });
});

describe("line helpers", () => {
  it("titles a concrete line with its product and a generic one with its category", () => {
    expect(lineTitle(line())).toBe("Leche entera Hacendado");
    expect(lineTitle(line({ productId: null, text: "leche", categoryName: "Leche entera" }))).toBe(
      "Leche entera",
    );
  });

  it("explains the brand rule without repeating the noun", () => {
    expect(lineSubline(line())).toBe("Hacendado · 1 l");
    expect(lineSubline(line({ pinBrand: false }))).toBe("Cualquier marca de leche entera");
    expect(lineSubline(line({ productId: null, brand: "" }))).toBe("Cualquier marca");
    expect(lineSubline(line({ productId: null, brand: "Pascual" }))).toBe("Marca: Pascual");
  });

  it("resolves a line only when it has a product or a category and no pending choice", () => {
    expect(isLineResolved(line())).toBe(true);
    expect(isLineResolved(line({ productId: null, categoryKey: null }))).toBe(false);
    expect(isLineResolved(line({ productId: null, exactOnly: true }))).toBe(false);
    expect(
      isLineResolved(
        line({
          productId: null,
          options: [
            { category_key: "pollo", name: "Pollo", image_url: null, from_unit_price: null, base_unit: "kg", exact_only: false },
          ],
        }),
      ),
    ).toBe(false);
  });
});
