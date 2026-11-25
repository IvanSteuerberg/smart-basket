import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CanonicalCard as CardData } from "../api";
import { CanonicalCard, canonicalCountLabel } from "./CanonicalCard";

function card(overrides: Partial<CardData> = {}): CardData {
  return {
    id: 5,
    name: "Leche entera",
    category_key: "leche_entera",
    category_name: "Leche entera",
    image_url: null,
    from_price: "0.89",
    from_unit_price: "0.89",
    base_unit: "l",
    product_count: 12,
    chains: ["mercadona", "dia", "lidl"],
    exact_only: false,
    ...overrides,
  };
}

function render(props: Partial<Parameters<typeof CanonicalCard>[0]> = {}): string {
  return renderToStaticMarkup(<CanonicalCard card={card()} onAdd={() => undefined} {...props} />);
}

describe("CanonicalCard", () => {
  it("shows the lowest price per unit and the labelled counter", () => {
    const html = render();
    expect(html).toContain("desde 0,89");
    expect(html).toContain("12 productos en 3 tiendas");
    expect(html).toContain("tabular-nums");
  });

  it("builds the counter label", () => {
    expect(canonicalCountLabel(card({ product_count: 1, chains: ["dia"] }))).toBe(
      "1 producto en 1 tienda",
    );
    expect(canonicalCountLabel(card({ chains: [] }))).toBe("12 productos");
  });

  it("offers «Añadir» when it is not in the list", () => {
    expect(render()).toContain("Añadir");
  });

  it("shows an accessible stepper when it is in the list as a generic line (M8)", () => {
    const html = render({ quantityInList: 2, onQuantityChange: () => undefined });
    expect(html).not.toContain(">Añadir<");
    expect(html).toContain("Una unidad más de Leche entera");
    expect(html).toContain("min-h-11");
    expect(html).toContain(">2<");
  });

  it("links to the options when only a concrete product can be bought", () => {
    const html = render({
      card: card({ exact_only: true }),
      quantityInList: 2,
      onQuantityChange: () => undefined,
    });
    expect(html).toContain("Ver opciones");
    expect(html).toContain('href="#/generico/5"');
    expect(html).not.toContain("Una unidad más");
  });

  it("uses semantic tokens only", () => {
    expect(render()).not.toMatch(/bg-white|bg-stone-|text-slate-|text-red-700|#2f6f4e|transition-all/);
  });
});
