import { describe, expect, it } from "vitest";
import {
  allResolved,
  applyAnyBrand,
  chooseOption,
  isResolved,
  markChoiceRequired,
  draftFromInterpreted,
  draftFromSearchResult,
  normalizeQuantity,
  GENERIC_DEFAULTS,
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
    ...GENERIC_DEFAULTS,
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
      exact_only: false,
      image_url: null,
      options: [],
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

  it("keeps the exact_only flag and leaves such a line unresolved until it has a product", () => {
    const draft = draftFromInterpreted({
      line: 1,
      text: "tinte",
      item: "tinte",
      quantity: "1",
      unit: "ud",
      category_key: "tinte",
      category_name: "Tinte de pelo",
      brand: null,
      alternatives: [],
      resolved: false,
      needs_llm: false,
      exact_only: true,
      image_url: null,
      options: [],
    });

    expect(draft.exactOnly).toBe(true);
    expect(isResolved(draft)).toBe(false);
    expect(isResolved({ ...draft, productId: 5, accept: "exact" })).toBe(true);
    expect(applyAnyBrand([{ ...draft, productId: 5, accept: "exact" }])[0]?.accept).toBe("exact");
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
      exact_only: false,
      image_url: null,
      options: [],
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
      exact_only: false,
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

describe("concrete lines and vague options", () => {
  const option = {
    category_key: "pollo_pechuga",
    name: "Pechuga de pollo",
    image_url: "https://example.test/pechuga.jpg",
    from_unit_price: "6.50",
    base_unit: "kg" as const,
    exact_only: false,
  };

  it("keeps a vague line unresolved until an option is chosen", () => {
    const vague = baseItem({ categoryKey: "pollo", options: [option] });
    expect(isResolved(vague)).toBe(false);

    const chosen = chooseOption(vague, option);
    expect(isResolved(chosen)).toBe(true);
    expect(chosen.categoryKey).toBe("pollo_pechuga");
    expect(chosen.imageUrl).toBe(option.image_url);
    expect(toRequestItem(chosen).category_key).toBe("pollo_pechuga");
  });

  it("keeps a line unresolved when the chosen option or search result has shades", () => {
    const vague = baseItem({ categoryKey: "maquillaje", options: [option] });
    const chosen = chooseOption(vague, { ...option, category_key: "labios", exact_only: true });
    expect(chosen.exactOnly).toBe(true);
    expect(chosen.productId).toBeNull();
    expect(isResolved(chosen)).toBe(false);

    const found = draftFromSearchResult({
      key: "tinte",
      name: "Tinte",
      kind: "leaf",
      path: "Cuidado personal",
      exact_only: true,
    });
    expect(found.exactOnly).toBe(true);
    expect(isResolved(found)).toBe(false);
  });

  it("marks the line a 422 refused according to its code", () => {
    const line = baseItem({ categoryKey: "tinte", productId: 3, options: [option] });

    expect(markChoiceRequired(line, "EXACT_ONLY")).toMatchObject({
      productId: null,
      exactOnly: true,
    });
    expect(markChoiceRequired(line, "VAGUE_LINE")).toMatchObject({
      categoryKey: null,
      productId: null,
      options: [],
    });
  });

  it("turns unpinned exact lines into equivalent ones and leaves pinned ones", () => {
    const loose = baseItem({ id: "a", productId: 7, accept: "exact" });
    const pinned = baseItem({ id: "b", productId: 8, accept: "exact", locked: true });
    const generic = baseItem({ id: "c" });

    const [a, b, c] = applyAnyBrand([loose, pinned, generic]);
    expect(a?.accept).toBe("equivalent");
    expect(b?.accept).toBe("exact");
    expect(c).toBe(generic);
  });

  it("sends a generic line by category, always equivalent", () => {
    const request = toRequestItem(baseItem({ accept: "exact" }));
    expect(request.category_key).toBe("leaf:leche");
    expect(request.product_id).toBeUndefined();
    expect(request.accept).toBe("equivalent");
  });
});
