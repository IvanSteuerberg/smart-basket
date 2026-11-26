import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Product } from "../api";
import {
  ProductAlternativesModal,
  ProductOptionRow,
  type ProductAlternativesModalProps,
  type ProductOptionRowProps,
} from "./ProductAlternativesModal";

function product(overrides: Partial<Product> = {}): Product {
  return {
    id: 101,
    name: "Plátano de Canarias",
    brand: "Hacendado",
    private_label: true,
    packaging: "Bolsa 1 kg",
    image_url: null,
    chain: "Mercadona",
    price: "1.99",
    unit_price: "1.99",
    base_unit: "kg",
    base_quantity: "1",
    canonical: null,
    ...overrides,
  };
}

function renderRow(overrides: Partial<ProductOptionRowProps> = {}): string {
  return renderToStaticMarkup(
    <ProductOptionRow
      product={product()}
      plannedChains={["mercadona"]}
      onSelect={() => undefined}
      {...overrides}
    />,
  );
}

function render(overrides: Partial<ProductAlternativesModalProps> = {}): string {
  return renderToStaticMarkup(
    <ProductAlternativesModal
      open
      canonicalId={11}
      lineId={0}
      currentProductId={101}
      plannedChains={["mercadona"]}
      onSelect={() => undefined}
      onClose={() => undefined}
      {...overrides}
    />,
  );
}

describe("ProductAlternativesModal", () => {
  it("is a native dialog labelled by its heading, without redundant ARIA (M3)", () => {
    const html = render();
    expect(html).toMatch(/^<dialog /);
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(html).toContain(`<h2 id="${labelledBy}"`);
    expect(html).not.toContain('role="dialog"');
    expect(html).not.toContain("aria-modal");
    expect(html).not.toMatch(/<dialog[^>]*class="[^"]*\b(flex|block|grid)\b/);
  });

  it("offers both tabs in a connected segmented control (M3)", () => {
    const html = render();
    expect(html).toContain('role="group"');
    expect(html).toContain("Mismo producto");
    expect(html).toContain("Otras opciones parecidas");
    const pressed = html.match(/aria-pressed="(true|false)"/g) ?? [];
    expect(pressed).toHaveLength(2);
    expect(pressed[0]).toBe('aria-pressed="true"');
  });

  it("opens on the first tab and says it is loading the products", () => {
    const html = render();
    expect(html).toContain("Cargando opciones…");
    expect(html).not.toContain("Buscando opciones parecidas…");
  });

  it("keeps every control at least 44px tall", () => {
    const html = render();
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toContain("min-h-11");
  });

  it("never renders banned styles or dashes in its copy", () => {
    const html = render();
    expect(html).not.toMatch(/transition-all/);
    expect(html).not.toMatch(/bg-white|bg-stone-|text-slate-/);
    expect(html).not.toMatch(/text-\[0\.(7|65)rem\]/);
    expect(html).not.toMatch(/—| – /);
  });
});

describe("ProductOptionRow (M3)", () => {
  it("shows the chain and the brand together, never one instead of the other", () => {
    const html = renderRow();
    expect(html).toContain("Hacendado · Mercadona");
    const withoutBrand = renderRow({ product: product({ brand: null }) });
    expect(withoutBrand).toContain("Mercadona");
    expect(withoutBrand).not.toContain("·");
  });

  it("warns when the product belongs to a chain outside the plan", () => {
    const outside = renderRow({
      product: product({ chain: "Alimerka", brand: null }),
      plannedChains: ["mercadona"],
    });
    expect(outside).toContain("Otra cadena: puede añadir o cambiar tiendas en tu plan");

    const inside = renderRow({ plannedChains: ["alimerka", "mercadona"] });
    expect(inside).not.toContain("Otra cadena");
  });

  it("marks the product already in the plan with a clear label", () => {
    const current = renderRow({ current: true });
    expect(current).toContain("En tu plan actual");
    expect(current).toMatch(/border-\[var\(--accent-primary\)\]/);

    const other = renderRow({ current: false });
    expect(other).not.toContain("En tu plan actual");
  });

  it("prints price and unit price in tabular digits", () => {
    const html = renderRow();
    expect(html).toContain("1,99 €");
    expect(html).toContain("1,99 €/kg");
    expect(html).toMatch(/tabular-nums[^>]*>1,99 €/s);
  });

  it("keeps the select button at least 44px tall", () => {
    const html = renderRow();
    expect(html).toMatch(/<button[^>]*min-h-11[^>]*>/);
  });
});
