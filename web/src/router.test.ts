import { describe, expect, it } from "vitest";
import {
  BASKET_HASH,
  canonicalHash,
  catalogHash,
  DEFAULT_CATALOG_FILTERS,
  parseRoute,
  productHash,
} from "./router";

function catalogRoute(section: string | null, view: "product" | "super", filters = {}) {
  return {
    name: "catalog",
    section,
    view,
    filters: { ...DEFAULT_CATALOG_FILTERS, ...filters },
  };
}

describe("parseRoute", () => {
  it("treats an empty hash and the root as the home page", () => {
    expect(parseRoute("")).toEqual({ name: "home" });
    expect(parseRoute("#")).toEqual({ name: "home" });
    expect(parseRoute("#/")).toEqual({ name: "home" });
  });

  it("parses the catalog without a section, by product by default", () => {
    expect(parseRoute("#/catalogo")).toEqual(catalogRoute(null, "product"));
    expect(parseRoute("#/catalogo/")).toEqual(catalogRoute(null, "product"));
  });

  it("parses the catalog of a section, decoding its key", () => {
    expect(parseRoute("#/catalogo/lacteos")).toEqual(catalogRoute("lacteos", "product"));
    expect(parseRoute("#/catalogo/aceites%20y%20vinagres")).toEqual(
      catalogRoute("aceites y vinagres", "product"),
    );
  });

  it("reads the view parameter of the catalog", () => {
    expect(parseRoute("#/catalogo?vista=super")).toEqual(catalogRoute(null, "super"));
    expect(parseRoute("#/catalogo/lacteos?vista=super")).toEqual(
      catalogRoute("lacteos", "super"),
    );
  });

  it("reads the catalog filters", () => {
    const hash =
      "#/catalogo/lacteos?q=leche&sub=leche_entera&cadena=mercadona,lidl&marca=Hacendado" +
      "&blanca=1&dieta=sin_gluten,vegano&oferta=1&min=1&max=3.5&cerca=1&orden=popular&pag=3";
    expect(parseRoute(hash)).toEqual(
      catalogRoute("lacteos", "product", {
        q: "leche",
        sub: "leche_entera",
        chains: ["mercadona", "lidl"],
        brand: "Hacendado",
        privateLabel: true,
        dietary: ["sin_gluten", "vegano"],
        onPromo: true,
        minPrice: 1,
        maxPrice: 3.5,
        near: true,
        sort: "popular",
        page: 3,
      }),
    );
  });

  it("falls back to defaults for invalid filter values", () => {
    const route = parseRoute("#/catalogo?orden=raro&pag=-2&min=abc&max=-1");
    expect(route).toEqual(catalogRoute(null, "product"));
  });

  it("parses a canonical product id", () => {
    expect(parseRoute("#/generico/12")).toEqual({ name: "canonical", id: 12 });
  });

  it("parses a product id", () => {
    expect(parseRoute("#/producto/12")).toEqual({ name: "product", id: 12 });
  });

  it("parses the list flow and the basket", () => {
    expect(parseRoute("#/lista")).toEqual({ name: "list" });
    expect(parseRoute(BASKET_HASH)).toEqual({ name: "basket" });
    expect(BASKET_HASH).toBe("#/cesta");
  });

  it("ignores unknown query parameters", () => {
    expect(parseRoute("#/catalogo/lacteos?foo=price")).toEqual(
      catalogRoute("lacteos", "product"),
    );
  });

  it("falls back to the home page when the hash is unknown", () => {
    expect(parseRoute("#/no-existe")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/abc")).toEqual({ name: "home" });
    expect(parseRoute("#/generico/abc")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/1/extra")).toEqual({ name: "home" });
    expect(parseRoute("#/catalogo/lacteos/extra")).toEqual({ name: "home" });
    expect(parseRoute("#/cesta/extra")).toEqual({ name: "home" });
  });
});

describe("route hashes", () => {
  it("builds section and product hashes", () => {
    expect(catalogHash(null)).toBe("#/catalogo");
    expect(catalogHash("lacteos")).toBe("#/catalogo/lacteos");
    expect(catalogHash(null, "super")).toBe("#/catalogo?vista=super");
    expect(catalogHash("lacteos", "super")).toBe("#/catalogo/lacteos?vista=super");
    expect(canonicalHash(12)).toBe("#/generico/12");
    expect(productHash(7)).toBe("#/producto/7");
  });

  it("writes only the filters that differ from the defaults", () => {
    expect(catalogHash("lacteos", "product", { sort: "relevance", page: 1 })).toBe(
      "#/catalogo/lacteos",
    );
    expect(
      catalogHash("lacteos", "product", { chains: ["lidl"], onPromo: true, page: 2 }),
    ).toBe("#/catalogo/lacteos?cadena=lidl&oferta=1&pag=2");
  });

  it("round-trips a section key with spaces", () => {
    expect(parseRoute(catalogHash("aceites y vinagres"))).toEqual(
      catalogRoute("aceites y vinagres", "product"),
    );
  });

  it("round-trips the supermarket view", () => {
    expect(parseRoute(catalogHash("lacteos", "super"))).toEqual(catalogRoute("lacteos", "super"));
  });

  it("round-trips every filter", () => {
    const filters = {
      q: "leche sin lactosa",
      sub: "leche",
      chains: ["dia", "alcampo"],
      brand: "Pascual",
      privateLabel: true,
      dietary: ["sin_lactosa"],
      onPromo: true,
      minPrice: 0.5,
      maxPrice: 4,
      near: true,
      sort: "price" as const,
      page: 4,
    };
    expect(parseRoute(catalogHash("lacteos", "super", filters))).toEqual(
      catalogRoute("lacteos", "super", filters),
    );
  });
});
