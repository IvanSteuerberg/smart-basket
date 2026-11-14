import { describe, expect, it } from "vitest";
import {
  allResolved,
  draftFromInterpreted,
  draftFromSearchResult,
  normalizeQuantity,
  toRequestItem,
  type DraftItem,
} from "./draft";
import type { InterpretedItem } from "./api";

function baseItem(overrides: Partial<DraftItem> = {}): DraftItem {
  return {
    id: "id-1",
    text: "leche",
    categoryKey: "leaf:leche",
    categoryName: "Leche",
    quantity: "2",
    unit: "l",
    brand: "",
    privateLabelOk: true,
    ...overrides,
  };
}

describe("draftFromInterpreted", () => {
  it("keeps the interpreted fields and leaves the brand empty", () => {
    const interpreted: InterpretedItem = {
      line: 1,
      text: "2 l de leche",
      item: "leche semidesnatada",
      quantity: "2",
      unit: "l",
      category_key: "leaf:leche",
      category_name: "Leche",
      brand: null,
      alternatives: [],
      resolved: true,
      needs_llm: false,
    };

    const draft = draftFromInterpreted(interpreted);

    expect(draft.text).toBe("2 l de leche");
    expect(draft.categoryKey).toBe("leaf:leche");
    expect(draft.categoryName).toBe("Leche");
    expect(draft.quantity).toBe("2");
    expect(draft.unit).toBe("l");
    expect(draft.brand).toBe("");
    expect(draft.privateLabelOk).toBe(true);
    expect(draft.id).not.toBe("");
  });

  it("keeps an unresolved line without category", () => {
    const draft = draftFromInterpreted({
      line: 2,
      text: "cosa rara",
      item: null,
      quantity: "1",
      unit: "ud",
      category_key: null,
      category_name: null,
      brand: null,
      alternatives: [],
      resolved: false,
      needs_llm: true,
    });

    expect(draft.categoryKey).toBeNull();
    expect(draft.categoryName).toBe("");
  });
});

describe("draftFromSearchResult", () => {
  it("creates a resolved line with one unit", () => {
    const draft = draftFromSearchResult({
      key: "leaf:yogur",
      name: "Yogur",
      kind: "leaf",
      path: "Lácteos › Yogur",
    });

    expect(draft.text).toBe("Yogur");
    expect(draft.categoryKey).toBe("leaf:yogur");
    expect(draft.quantity).toBe("1");
    expect(draft.unit).toBe("ud");
  });
});

describe("allResolved", () => {
  it("is false for an empty list", () => {
    expect(allResolved([])).toBe(false);
  });

  it("is false when a line has no category", () => {
    expect(allResolved([baseItem(), baseItem({ id: "id-2", categoryKey: null })])).toBe(false);
  });

  it("is true when every line has a category", () => {
    expect(allResolved([baseItem(), baseItem({ id: "id-2" })])).toBe(true);
  });
});

describe("normalizeQuantity", () => {
  it("trims and converts the decimal comma to a dot", () => {
    expect(normalizeQuantity(" 2,5 ")).toBe("2.5");
    expect(normalizeQuantity("3")).toBe("3");
  });
});

describe("toRequestItem", () => {
  it("sends the brand trimmed and null when empty", () => {
    expect(toRequestItem(baseItem({ brand: "  Pascual " })).brand).toBe("Pascual");
    expect(toRequestItem(baseItem({ brand: "   " })).brand).toBeNull();
  });

  it("normalizes the quantity and keeps the preferences", () => {
    const request = toRequestItem(baseItem({ quantity: "1,5", privateLabelOk: false }));

    expect(request.quantity).toBe("1.5");
    expect(request.private_label_ok).toBe(false);
    expect(request.category_key).toBe("leaf:leche");
  });
});
