import { describe, expect, it } from "vitest";
import { toRequestItem, GENERIC_DEFAULTS, type DraftItem } from "./draft";
import type { CartLine } from "./cart";
import {
  listReducer,
  migrateCartToUnified,
  toDraftItems,
  unifiedLineCount,
  type UnifiedLine,
} from "./listStore";

function line(overrides: Partial<UnifiedLine> = {}): UnifiedLine {
  return {
    id: "l1",
    text: "Leche entera",
    categoryKey: "leche-entera",
    categoryName: "Leche entera",
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

function cartLine(overrides: Partial<CartLine> = {}): CartLine {
  return {
    id: "c1",
    product_id: 5,
    name: "Leche Pascual 1 L",
    brand: "Pascual",
    packaging: "1 L",
    image_url: null,
    category_key: "leche-entera",
    category_name: "Leche entera",
    quantity: 2,
    accept: "exact",
    locked: false,
    exact_only: false,
    ...overrides,
  };
}

function draftItem(overrides: Partial<DraftItem> = {}): DraftItem {
  return {
    id: "d1",
    text: "arroz",
    categoryKey: "arroz",
    categoryName: "Arroz",
    quantity: "500",
    unit: "g",
    brand: "",
    privateLabelOk: true,
    ...GENERIC_DEFAULTS,
    ...overrides,
  };
}

describe("listReducer", () => {
  it("merges the same generic category and sums quantities", () => {
    const once = listReducer([], { type: "add", line: line() });
    const twice = listReducer(once, { type: "add", line: line({ id: "l2", quantity: "2" }) });
    expect(twice).toHaveLength(1);
    expect(twice[0].quantity).toBe("3");
  });

  it("keeps a concrete product apart from its generic category", () => {
    const lines = listReducer(
      listReducer([], { type: "add", line: line() }),
      { type: "add", line: line({ id: "l2", productId: 9, pinBrand: true }) },
    );
    expect(lines).toHaveLength(2);
  });

  it("clamps pack quantities and keeps decimals for weights", () => {
    const packs = listReducer([line()], { type: "setQuantity", id: "l1", quantity: "500" });
    expect(packs[0].quantity).toBe("99");
    const kilos = listReducer([line({ unit: "kg" })], {
      type: "setQuantity",
      id: "l1",
      quantity: "1,5",
    });
    expect(kilos[0].quantity).toBe("1.5");
  });

  it("never unpins a line of shades", () => {
    const lines = listReducer([line({ productId: 1, exactOnly: true, pinBrand: true })], {
      type: "setPinBrand",
      id: "l1",
      pinBrand: false,
    });
    expect(lines[0].pinBrand).toBe(true);
  });

  it("removes, updates and clears", () => {
    const lines = [line(), line({ id: "l2" })];
    expect(listReducer(lines, { type: "remove", id: "l1" })).toHaveLength(1);
    expect(listReducer(lines, { type: "update", id: "l2", patch: { text: "x" } })[1].text).toBe("x");
    expect(listReducer(lines, { type: "clear" })).toEqual([]);
  });
});

describe("migrateCartToUnified", () => {
  it("merges cart lines and draft items into one list", () => {
    const lines = migrateCartToUnified([cartLine()], [draftItem()]);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatchObject({ productId: 5, pinBrand: true, quantity: "2", unit: "ud" });
    expect(lines[1]).toMatchObject({ productId: null, pinBrand: false, unit: "g" });
  });

  it("reads generic cart lines as not pinned", () => {
    const [generic] = migrateCartToUnified([
      cartLine({ product_id: null, brand: null, accept: "equivalent" }),
    ]);
    expect(generic).toMatchObject({ productId: null, pinBrand: false, brand: "" });
  });
});

describe("toDraftItems", () => {
  it("maps the brand switch to accept and locked", () => {
    const [pinnedItem, anyBrand, generic] = toDraftItems([
      line({ productId: 5, pinBrand: true }),
      line({ id: "l2", productId: 5, pinBrand: false }),
      line({ id: "l3" }),
    ]);
    expect(pinnedItem).toMatchObject({ accept: "exact", locked: true });
    expect(anyBrand).toMatchObject({ accept: "equivalent", locked: false });
    expect(generic).toMatchObject({ accept: "equivalent", locked: false, productId: null });
  });

  it("sends a shades line as exact and builds a valid request item", () => {
    const [item] = toDraftItems([line({ productId: 7, exactOnly: true, quantity: "2" })]);
    expect(item.accept).toBe("exact");
    expect(toRequestItem(item)).toMatchObject({ product_id: 7, accept: "exact", unit: "ud" });
  });
});

describe("unifiedLineCount", () => {
  it("adds packs and counts a weighed line once", () => {
    expect(unifiedLineCount([])).toBe(0);
    expect(
      unifiedLineCount([line({ quantity: "3" }), line({ id: "l2", unit: "kg", quantity: "1.5" })]),
    ).toBe(4);
  });
});
