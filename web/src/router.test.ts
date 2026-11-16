import { describe, expect, it } from "vitest";
import { canonicalHash, catalogHash, parseRoute, productHash } from "./router";

describe("parseRoute", () => {
  it("treats an empty hash and the root as the home page", () => {
    expect(parseRoute("")).toEqual({ name: "home" });
    expect(parseRoute("#")).toEqual({ name: "home" });
    expect(parseRoute("#/")).toEqual({ name: "home" });
  });

  it("parses the catalog without a section, by product by default", () => {
    expect(parseRoute("#/catalogo")).toEqual({
      name: "catalog",
      section: null,
      view: "product",
    });
    expect(parseRoute("#/catalogo/")).toEqual({
      name: "catalog",
      section: null,
      view: "product",
    });
  });

  it("parses the catalog of a section, decoding its key", () => {
    expect(parseRoute("#/catalogo/lacteos")).toEqual({
      name: "catalog",
      section: "lacteos",
      view: "product",
    });
    expect(parseRoute("#/catalogo/aceites%20y%20vinagres")).toEqual({
      name: "catalog",
      section: "aceites y vinagres",
      view: "product",
    });
  });

  it("reads the view parameter of the catalog", () => {
    expect(parseRoute("#/catalogo?vista=super")).toEqual({
      name: "catalog",
      section: null,
      view: "super",
    });
    expect(parseRoute("#/catalogo/lacteos?vista=super")).toEqual({
      name: "catalog",
      section: "lacteos",
      view: "super",
    });
  });

  it("parses a canonical product id", () => {
    expect(parseRoute("#/generico/12")).toEqual({ name: "canonical", id: 12 });
  });

  it("parses a product id", () => {
    expect(parseRoute("#/producto/12")).toEqual({ name: "product", id: 12 });
  });

  it("parses the list flow", () => {
    expect(parseRoute("#/lista")).toEqual({ name: "list" });
  });

  it("ignores other query parameters", () => {
    expect(parseRoute("#/catalogo/lacteos?sort=price")).toEqual({
      name: "catalog",
      section: "lacteos",
      view: "product",
    });
  });

  it("falls back to the home page when the hash is unknown", () => {
    expect(parseRoute("#/no-existe")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/abc")).toEqual({ name: "home" });
    expect(parseRoute("#/generico/abc")).toEqual({ name: "home" });
    expect(parseRoute("#/producto/1/extra")).toEqual({ name: "home" });
    expect(parseRoute("#/catalogo/lacteos/extra")).toEqual({ name: "home" });
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

  it("round-trips a section key with spaces", () => {
    const hash = catalogHash("aceites y vinagres");
    expect(parseRoute(hash)).toEqual({
      name: "catalog",
      section: "aceites y vinagres",
      view: "product",
    });
  });

  it("round-trips the supermarket view", () => {
    expect(parseRoute(catalogHash("lacteos", "super"))).toEqual({
      name: "catalog",
      section: "lacteos",
      view: "super",
    });
  });
});
