import { describe, expect, it } from "vitest";
import {
  anyBrandOf,
  maxStoresLabel,
  pinBrandLabel,
  quantityLabel,
  unresolvedAlert,
} from "./texts";

describe("quantityLabel (B12)", () => {
  it("spells units out in singular and plural", () => {
    expect(quantityLabel("1", "ud", false)).toBe("1 unidad");
    expect(quantityLabel("2", "ud", false)).toBe("2 unidades");
  });

  it("calls the packs of a concrete product «envases»", () => {
    expect(quantityLabel("1", "ud", true)).toBe("1 envase");
    expect(quantityLabel("3", "ud", true)).toBe("3 envases");
  });

  it("shows weight and volume with their unit and a decimal comma", () => {
    expect(quantityLabel("2", "l", false)).toBe("2 l");
    expect(quantityLabel("500", "g", false)).toBe("500 g");
    expect(quantityLabel("1.5", "kg", false)).toBe("1,5 kg");
    expect(quantityLabel("250", "ml", false)).toBe("250 ml");
  });
});

describe("B5 agreement", () => {
  it("builds the brand rule with «marca» as the head noun", () => {
    expect(anyBrandOf("Leche entera")).toBe("Cualquier marca de leche entera");
    expect(anyBrandOf("Huevos")).toBe("Cualquier marca de huevos");
    expect(anyBrandOf("  ")).toBe("Cualquier marca");
  });

  it("labels the brand control by its state", () => {
    expect(pinBrandLabel(true, "Hacendado")).toBe("Solo esta marca");
    expect(pinBrandLabel(true, "")).toBe("Solo este producto");
    expect(pinBrandLabel(false, "Hacendado")).toBe("Cualquier marca");
  });

  it("agrees the unresolved warning in number", () => {
    expect(unresolvedAlert(1)).toBe("Resuelve la línea marcada antes de calcular tu plan.");
    expect(unresolvedAlert(3)).toBe("Resuelve las 3 líneas marcadas antes de calcular tu plan.");
  });

  it("agrees «tienda» with the limit", () => {
    expect(maxStoresLabel(1)).toBe("Hasta 1 tienda");
    expect(maxStoresLabel(3)).toBe("Hasta 3 tiendas");
  });
});
