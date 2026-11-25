import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ActiveChain, SectionCategory } from "../api";
import { DEFAULT_CATALOG_FILTERS, type CatalogFilters as Filters } from "../router";
import {
  activeFilterChips,
  CatalogFilterFields,
  CatalogFilters,
  clearedFilters,
  countActiveFilters,
} from "./CatalogFilters";

const categories: SectionCategory[] = [
  {
    key: "lacteos",
    name: "Lácteos",
    children: [
      {
        key: "leches",
        name: "Leches",
        vague: false,
        products: 10,
        children: [{ key: "leche_entera", name: "Leche entera", base_unit: "l", products: 5 }],
      },
    ],
  },
  {
    key: "bebidas",
    name: "Bebidas",
    children: [
      {
        key: "aguas",
        name: "Aguas",
        vague: false,
        products: 3,
        children: [{ key: "agua_mineral", name: "Agua mineral", base_unit: "l", products: 3 }],
      },
    ],
  },
];

const chains: ActiveChain[] = [
  { code: "mercadona", name: "Mercadona", store_count: 3, product_count: 100, last_price_at: null },
  { code: "dia", name: "Dia", store_count: 2, product_count: 80, last_price_at: null },
];

function filters(overrides: Partial<Filters> = {}): Filters {
  return { ...DEFAULT_CATALOG_FILTERS, ...overrides };
}

function fields(overrides: Partial<Filters> = {}, hasOrigin = true, section: string | null = null) {
  return renderToStaticMarkup(
    <CatalogFilterFields
      idPrefix="t"
      section={section}
      filters={filters(overrides)}
      categories={categories}
      chains={chains}
      hasOrigin={hasOrigin}
      onChange={() => undefined}
    />,
  );
}

describe("CatalogFilterFields", () => {
  it("offers every filter of the catalog", () => {
    const html = fields();
    for (const text of [
      "Subcategoría",
      "Supermercados",
      "Marca",
      "Solo marca blanca",
      "Sin gluten",
      "Sin lactosa",
      "Vegano",
      "Vegetariano",
      "Solo ofertas",
      "Precio (€)",
      "Cerca de mí",
    ]) {
      expect(html).toContain(text);
    }
  });

  it("always shows the dietary notice", () => {
    expect(fields()).toContain(
      "Comprueba siempre la etiqueta del fabricante. El filtro se basa en el nombre publicado por el supermercado.",
    );
  });

  it("limits the sub-categories to the active section", () => {
    const all = fields();
    expect(all).toContain("Leches");
    expect(all).toContain("Aguas");
    const only = fields({}, true, "bebidas");
    expect(only).toContain("Aguas");
    expect(only).not.toContain("Leches");
  });

  it("marks the selected chains with aria-pressed", () => {
    const html = fields({ chains: ["dia"] });
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('aria-pressed="false"');
  });

  it("asks for an address, with a link to the list, when there is no origin", () => {
    const html = fields({}, false);
    expect(html).toContain('href="#/lista"');
    expect(html).toContain("disabled");
    expect(fields({}, true)).not.toContain('href="#/lista"');
  });
});

describe("CatalogFilters", () => {
  function render(value: Filters) {
    return renderToStaticMarkup(
      <CatalogFilters
        section={null}
        filters={value}
        categories={categories}
        chains={chains}
        hasOrigin
        onChange={() => undefined}
        onClear={() => undefined}
      />,
    );
  }

  it("counts the active filters in the mobile button", () => {
    expect(render(filters({ onPromo: true, dietary: ["sin_gluten"] }))).toContain("Filtros (2)");
    expect(render(filters())).not.toContain("Filtros (");
  });

  it("renders a native dialog labelled by its title, with no redundant roles", () => {
    const html = render(filters());
    expect(html).toContain("<dialog");
    expect(html).toContain("aria-labelledby");
    expect(html).not.toContain('role="dialog"');
    expect(html).not.toContain("aria-modal");
  });

  it("uses semantic tokens only", () => {
    expect(render(filters({ onPromo: true }))).not.toMatch(
      /bg-white|bg-stone-|text-slate-|text-red-700|#2f6f4e|transition-all/,
    );
  });
});

describe("filter helpers", () => {
  it("counts filters but not sorting, search or page", () => {
    expect(countActiveFilters(filters({ q: "leche", sort: "price", page: 3 }))).toBe(0);
    expect(
      countActiveFilters(
        filters({ sub: "leches", chains: ["dia", "lidl"], minPrice: 1, maxPrice: 3, near: true }),
      ),
    ).toBe(6);
  });

  it("builds one removable chip per active filter", () => {
    const chips = activeFilterChips(
      filters({ sub: "leches", chains: ["dia", "lidl"], brand: " Pascual ", dietary: ["sin_lactosa"] }),
      categories,
      chains,
    );
    expect(chips.map((chip) => chip.label)).toEqual([
      "Leches",
      "Dia",
      "lidl",
      "Marca: Pascual",
      "Sin lactosa",
    ]);
    expect(chips[1].patch).toEqual({ chains: ["lidl"] });
    expect(chips[0].patch).toEqual({ sub: null });
  });

  it("clears the filters but keeps search and sorting", () => {
    expect(clearedFilters(filters({ q: "leche", sort: "price", onPromo: true, sub: "x" }))).toEqual({
      ...DEFAULT_CATALOG_FILTERS,
      q: "leche",
      sort: "price",
    });
  });
});
