import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Product } from "../api";
import type { UnifiedLine } from "../listStore";
import {
  changeLineQuantity,
  findCanonicalLine,
  findProductLine,
  lineQuantity,
  ProductCard,
} from "./ProductCard";

function product(overrides: Partial<Product> = {}): Product {
  return {
    id: 7,
    name: "Leche entera 1 l",
    brand: "Hacendado",
    private_label: true,
    packaging: "1 l",
    image_url: null,
    chain: "mercadona",
    price: "0.89",
    unit_price: "0.89",
    base_unit: "l",
    base_quantity: "1",
    canonical: null,
    ...overrides,
  };
}

function line(overrides: Partial<UnifiedLine> = {}): UnifiedLine {
  return {
    id: "l1",
    text: "Leche",
    categoryKey: "leche",
    categoryName: "Leche",
    productId: null,
    brand: "",
    packaging: null,
    imageUrl: null,
    quantity: "1",
    unit: "ud",
    privateLabelOk: true,
    pinBrand: false,
    exactOnly: false,
    options: [],
    ...overrides,
  };
}

function render(props: Partial<Parameters<typeof ProductCard>[0]> = {}): string {
  return renderToStaticMarkup(<ProductCard product={product()} onAdd={() => undefined} {...props} />);
}

describe("ProductCard", () => {
  it("shows the chain and the brand together (M7)", () => {
    const html = render();
    expect(html).toContain("Hacendado");
    expect(html).toContain("--logo-plate");
  });

  it("shows the chain alone when there is no brand", () => {
    const html = render({ product: product({ brand: null }) });
    expect(html).toContain("--logo-plate");
    expect(html).not.toContain("Hacendado");
  });

  it("offers «Añadir» when the product is not in the list", () => {
    const html = render();
    expect(html).toContain("Añadir");
    expect(html).not.toContain("Una unidad más");
  });

  it("replaces «Añadir» with a stepper when it is in the list (M8)", () => {
    const html = render({ quantityInList: 3, onQuantityChange: () => undefined });
    expect(html).not.toContain(">Añadir<");
    expect(html).toContain("Una unidad más de Leche entera 1 l");
    expect(html).toContain("Una unidad menos de Leche entera 1 l");
    expect(html).toContain("min-h-11");
    expect(html).toContain("tabular-nums");
    expect(html).toContain(">3<");
  });

  it("labels the minus button as a removal at one unit", () => {
    const html = render({ quantityInList: 1, onQuantityChange: () => undefined });
    expect(html).toContain("Quitar Leche entera 1 l de tu lista");
  });

  it("has a polite live region", () => {
    expect(render()).toContain('aria-live="polite"');
  });

  it("marks a promotion with the savings tokens", () => {
    const html = render({ product: product({ on_promo: true }) });
    expect(html).toContain("Oferta");
    expect(html).toContain("--savings-bg");
    expect(render()).not.toContain("Oferta");
  });

  it("uses semantic tokens only", () => {
    const html = render({ product: product({ on_promo: true }) });
    expect(html).not.toMatch(/bg-white|bg-stone-|text-slate-|text-red-700|#2f6f4e|transition-all/);
  });
});

describe("list helpers", () => {
  it("finds the line of a concrete product and of a generic one", () => {
    const lines = [line({ id: "a", productId: 7 }), line({ id: "b", categoryKey: "yogur" })];
    expect(findProductLine(lines, 7)?.id).toBe("a");
    expect(findProductLine(lines, 8)).toBeNull();
    expect(findCanonicalLine(lines, "yogur")?.id).toBe("b");
    expect(findCanonicalLine(lines, "leche")).toBeNull();
  });

  it("reads the quantity as whole units", () => {
    expect(lineQuantity(null)).toBe(0);
    expect(lineQuantity(line({ quantity: "2" }))).toBe(2);
  });

  it("removes the line when going under one", () => {
    const calls: string[] = [];
    const update = (id: string, quantity: string) => calls.push(`update ${id} ${quantity}`);
    const remove = (id: string) => calls.push(`remove ${id}`);
    changeLineQuantity(line(), 0, update, remove);
    changeLineQuantity(line(), 4, update, remove);
    expect(calls).toEqual(["remove l1", "update l1 4"]);
  });
});
