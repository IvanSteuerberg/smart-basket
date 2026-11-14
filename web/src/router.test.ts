import { describe, expect, it } from "vitest";
import { catalogHash, parseRoute, productHash } from "./router";

describe("parseRoute", () => {
  it("treats an empty hash and the root as the home page", () => {
    expect(parseRoute("")).toEqual({ name: "home" });
    expect(parseRoute("#")).toEqual({ name: "home" });
    expect(parseRoute("#/")).toEqual({ name: "home" });
  });

  it("parses the catalog without a section", () => {
    expect(parseRoute("#/catalogo")).toEqual({ name: "catalog", section: null });
    expect(parseRoute("#/catalogo/")).toEqual({ name: "catalog", section: null });
  });

  it("parses the catalog of a section, decoding its key", () => {
    expect(parseRoute("#/catalogo/lacteos")).toEqual({ name: "catalog", section: "lacteos" });
    expect(parseRoute("#/catalogo/aceites%20y%20vinagres")).toEqual({
      name: "catalog",
      section: "aceites y vinagres",
    });
  });

  it("parses a product id", () => {
    expect(parseRoute("#/producto/12")).toEqual({ name: "product", id: 12 });
  });

  it("parses the list flow", () => {
    expect(parseRoute("#/lista")).toEqual({ name: "list" });
  });

  it("ignores a query string", () => {
    expect(parseRoute("#/catalogo/lacteos?sort=price")).toEqual({
      name: "catalog",
      section: "lacteos",
    });
  });

  it("falls back to the home page when the hash is unknown", () => {
    expect(parseRoute("#/no-existe")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/abc")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/1/extra")).toEqual({ name: "home" });
    expect(parseRoute("#/catalogo/lacteos/extra")).toEqual({ name: "home" });
  });
});

describe("route hashes", () => {
  it("builds section and product hashes", () => {
    expect(catalogHash(null)).toBe("#/catalogo");
    expect(catalogHash("lacteos")).toBe("#/catalogo/lacteos");
    expect(productHash(7)).toBe("#/producto/7");
  });

  it("round-trips a section key with spaces", () => {
    const hash = catalogHash("aceites y vinagres");
    expect(parseRoute(hash)).toEqual({ name: "catalog", section: "aceites y vinagres" });
  });
});
