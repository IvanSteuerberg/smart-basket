import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { catalogHash, DEFAULT_CATALOG_FILTERS, parseRoute } from "../router";
import { CatalogPage, filterQuery, type CatalogPageProps } from "./CatalogPage";

function props(overrides: Partial<CatalogPageProps> = {}): CatalogPageProps {
  return {
    section: null,
    view: "product",
    filters: DEFAULT_CATALOG_FILTERS,
    sections: [{ key: "lacteos", name: "Lácteos", products: 4, image_url: null }],
    sectionsError: null,
    query: "",
    activeChains: [
      { code: "dia", name: "Dia", store_count: 1, product_count: 2, last_price_at: null },
    ],
    origin: null,
    mode: "walk",
    lines: [],
    onQueryChange: () => undefined,
    onAdd: () => undefined,
    onAddCanonical: () => undefined,
    onUpdateLineQuantity: () => undefined,
    onRemoveLine: () => undefined,
    ...overrides,
  };
}

function render(overrides: Partial<CatalogPageProps> = {}): string {
  return renderToStaticMarkup(<CatalogPage {...props(overrides)} />);
}

describe("CatalogPage", () => {
  it("toggles the view with a connected segmented group", () => {
    const html = render();
    expect(html).toContain('role="group"');
    expect(html).toContain('aria-label="Vista del catálogo"');
    expect(html).toContain("Por producto");
    expect(html).toContain("Por supermercado");
    expect(html).toContain('aria-pressed="true"');
  });

  it("shows the filters and the sort in both views", () => {
    for (const view of ["product", "super"] as const) {
      const html = render({ view });
      expect(html).toContain("Subcategoría");
      expect(html).toContain("Solo ofertas");
      expect(html).toContain("Nombre (A a Z)");
      expect(html).toContain("Más barato por unidad");
    }
  });

  it("shows active filter chips and a clear button", () => {
    const html = render({ filters: { ...DEFAULT_CATALOG_FILTERS, onPromo: true, chains: ["dia"] } });
    expect(html).toContain("Quitar filtro: Solo ofertas");
    expect(html).toContain("Quitar filtro: Dia");
    expect(html).toContain("Limpiar filtros");
    expect(html).toContain("Filtros (2)");
  });

  it("shows no chips without active filters", () => {
    const html = render();
    expect(html).not.toContain("Quitar filtro");
    expect(html).not.toContain("Filtros activos");
  });

  it("keeps the filters when switching section", () => {
    const html = render({ filters: { ...DEFAULT_CATALOG_FILTERS, onPromo: true } });
    expect(html).toContain(`href="${catalogHash("lacteos", "product", { onPromo: true })}"`);
  });

  it("uses semantic tokens only and no long dashes", () => {
    const html = render({ filters: { ...DEFAULT_CATALOG_FILTERS, onPromo: true } });
    expect(html).not.toMatch(/bg-white|bg-stone-|text-slate-|text-red-700|#2f6f4e|transition-all/);
    expect(html).not.toContain("—");
    expect(html).not.toContain(" – ");
  });
});

describe("filterQuery", () => {
  it("maps the URL filters to the API", () => {
    const query = filterQuery(
      {
        ...DEFAULT_CATALOG_FILTERS,
        sub: "leches",
        chains: ["dia"],
        brand: " Pascual ",
        privateLabel: true,
        dietary: ["sin_gluten"],
        onPromo: true,
        minPrice: 1,
        maxPrice: 5,
      },
      null,
      "walk",
    );
    expect(query).toEqual({
      category: "leches",
      chains: ["dia"],
      brand: "Pascual",
      private_label: true,
      dietary: ["sin_gluten"],
      on_promo: true,
      min_price: 1,
      max_price: 5,
      near_lat: null,
      near_lon: null,
      mode: null,
    });
  });

  it("sends the saved origin and the mode only when «Cerca de mí» is on", () => {
    const origin = { lat: 42.6, lon: -5.57, label: "Casa" };
    const near = filterQuery({ ...DEFAULT_CATALOG_FILTERS, near: true }, origin, "car");
    expect(near.near_lat).toBe(42.6);
    expect(near.near_lon).toBe(-5.57);
    expect(near.mode).toBe("car");
    expect(filterQuery(DEFAULT_CATALOG_FILTERS, origin, "car").near_lat).toBeNull();
    // No saved origin: nothing to send even with the filter on.
    expect(filterQuery({ ...DEFAULT_CATALOG_FILTERS, near: true }, null, "car").near_lat).toBeNull();
  });
});

describe("catalog URL", () => {
  it("round-trips every filter so a reload keeps the view (A8)", () => {
    const filters = {
      ...DEFAULT_CATALOG_FILTERS,
      sub: "leches",
      chains: ["dia", "lidl"],
      brand: "Pascual",
      privateLabel: true,
      dietary: ["sin_gluten", "sin_lactosa"],
      onPromo: true,
      minPrice: 1,
      maxPrice: 4.5,
      near: true,
      sort: "popular" as const,
    };
    const route = parseRoute(catalogHash("lacteos", "super", filters));
    expect(route).toEqual({ name: "catalog", section: "lacteos", view: "super", filters });
  });
});
