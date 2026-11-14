import { describe, expect, it } from "vitest";
import type { CanonicalCard, Product } from "./api";
import {
  canonicalLine,
  cartItemCount,
  cartReducer,
  clampQuantity,
  draftItemFromCartLine,
  draftItemsFromCart,
  genericLine,
  MAX_QUANTITY,
  specificLine,
  type CartLine,
} from "./cart";
import { toRequestItem } from "./draft";

function product(overrides: Partial<Product> = {}): Product {
  return {
    id: 1,
    name: "Leche entera 1 L",
    brand: "Pascual",
    private_label: false,
    packaging: "Botella 1 L",
    image_url: "https://photos.test/leche.png",
    chain: "mercadona",
    price: "1.15",
    unit_price: "1.15",
    base_unit: "l",
    base_quantity: "1",
    canonical: {
      id: 10,
      name: "Leche entera",
      category_key: "leche-entera",
      category_name: "Leche entera",
    },
    ...overrides,
  };
}

function line(overrides: Partial<CartLine> = {}): CartLine {
  return { ...specificLine(product()), ...overrides };
}

describe("specificLine", () => {
  it("keeps the product identity and its canonical category", () => {
    const added = specificLine(product());

    expect(added.product_id).toBe(1);
    expect(added.name).toBe("Leche entera 1 L");
    expect(added.brand).toBe("Pascual");
    expect(added.packaging).toBe("Botella 1 L");
    expect(added.category_key).toBe("leche-entera");
    expect(added.quantity).toBe(1);
  });

  it("keeps the product even when it has no canonical", () => {
    const added = specificLine(product({ canonical: null }));

    expect(added.product_id).toBe(1);
    expect(added.category_key).toBeNull();
    expect(added.category_name).toBeNull();
  });
});

describe("genericLine", () => {
  it("uses the canonical name and category, with the photo it was added from", () => {
    const added = genericLine(product());

    expect(added).not.toBeNull();
    expect(added?.product_id).toBeNull();
    expect(added?.name).toBe("Leche entera");
    expect(added?.category_key).toBe("leche-entera");
    expect(added?.image_url).toBe("https://photos.test/leche.png");
    expect(added?.brand).toBeNull();
  });

  it("is not possible without a canonical", () => {
    expect(genericLine(product({ canonical: null }))).toBeNull();
  });
});

describe("accept mode and padlock", () => {
  it("adds a specific product as exact, or as equivalent while the switch is on", () => {
    expect(specificLine(product()).accept).toBe("exact");
    expect(specificLine(product()).locked).toBe(false);
    expect(specificLine(product(), true).accept).toBe("equivalent");
  });

  it("adds a generic line as equivalent", () => {
    expect(genericLine(product())?.accept).toBe("equivalent");
  });

  it("builds a generic line from a canonical card", () => {
    const card: CanonicalCard = {
      id: 10,
      name: "Leche entera",
      category_key: "leche-entera",
      category_name: "Leche entera",
      image_url: "https://photos.test/leche.png",
      from_price: "1.05",
      from_unit_price: "1.05",
      base_unit: "l",
      product_count: 4,
      chains: ["mercadona", "dia"],
    };

    const added = canonicalLine(card);

    expect(added.product_id).toBeNull();
    expect(added.name).toBe("Leche entera");
    expect(added.category_key).toBe("leche-entera");
    expect(added.image_url).toBe(card.image_url);
    expect(added.accept).toBe("equivalent");
    expect(added.locked).toBe(false);
  });

  it("changes the accept mode of one line", () => {
    const current = [line({ id: "a" }), line({ id: "b", product_id: 2 })];
    const next = cartReducer(current, { type: "setAccept", id: "a", accept: "equivalent" });

    expect(next[0].accept).toBe("equivalent");
    expect(next[1].accept).toBe("exact");
  });

  it("pins a line as this product and releases it without touching its choice", () => {
    const current = [line({ id: "a", accept: "equivalent" })];
    const pinned = cartReducer(current, { type: "toggleLock", id: "a" });

    expect(pinned[0].locked).toBe(true);
    expect(pinned[0].accept).toBe("exact");

    const released = cartReducer(
      cartReducer(pinned, { type: "setAccept", id: "a", accept: "equivalent" }),
      { type: "toggleLock", id: "a" },
    );
    expect(released[0].locked).toBe(false);
    expect(released[0].accept).toBe("equivalent");
  });

  it("leaves pinned and generic lines alone when any brand is on", () => {
    const current = [
      line({ id: "a" }),
      line({ id: "b", product_id: 2, locked: true }),
      line({ id: "c", product_id: null, category_key: "pan" }),
    ];
    const next = cartReducer(current, { type: "anyBrand" });

    expect(next[0].accept).toBe("equivalent");
    expect(next[1].accept).toBe("exact");
    expect(next[2]).toBe(current[2]);
  });
});

describe("cartReducer", () => {
  it("appends a new line with a quantity of one", () => {
    const next = cartReducer([], { type: "add", line: line({ id: "a" }) });

    expect(next).toHaveLength(1);
    expect(next[0].quantity).toBe(1);
  });

  it("increments the same specific product instead of repeating it", () => {
    const first = line({ id: "a", quantity: 2 });
    const next = cartReducer([first], { type: "add", line: line({ id: "b" }) });

    expect(next).toHaveLength(1);
    expect(next[0].id).toBe("a");
    expect(next[0].quantity).toBe(3);
  });

  it("merges generic lines of the same category", () => {
    const first = line({ id: "a", product_id: null, category_key: "leche-entera" });
    const next = cartReducer([first], {
      type: "add",
      line: line({ id: "b", product_id: null, category_key: "leche-entera" }),
    });

    expect(next).toHaveLength(1);
    expect(next[0].quantity).toBe(2);
  });

  it("keeps a generic line and a specific line apart", () => {
    const generic = line({ id: "a", product_id: null });
    const next = cartReducer([generic], { type: "add", line: line({ id: "b" }) });

    expect(next).toHaveLength(2);
  });

  it("sets a quantity and never goes below one", () => {
    const current = [line({ id: "a" })];
    expect(cartReducer(current, { type: "setQuantity", id: "a", quantity: 4 })[0].quantity).toBe(4);
    expect(cartReducer(current, { type: "setQuantity", id: "a", quantity: 0 })[0].quantity).toBe(1);
  });

  it("removes a line and clears the cart", () => {
    const current = [line({ id: "a" }), line({ id: "b", product_id: 2 })];
    expect(cartReducer(current, { type: "remove", id: "a" })).toHaveLength(1);
    expect(cartReducer(current, { type: "clear" })).toEqual([]);
  });
});

describe("clampQuantity", () => {
  it("keeps whole units within the allowed range", () => {
    expect(clampQuantity(2.4)).toBe(2);
    expect(clampQuantity(-3)).toBe(1);
    expect(clampQuantity(MAX_QUANTITY + 10)).toBe(MAX_QUANTITY);
    expect(clampQuantity(Number.NaN)).toBe(1);
  });
});

describe("cartItemCount", () => {
  it("adds up the units of every line", () => {
    expect(cartItemCount([line({ quantity: 2 }), line({ id: "b", quantity: 3 })])).toBe(5);
    expect(cartItemCount([])).toBe(0);
  });
});

describe("draftItemsFromCart", () => {
  it("sends a specific line as that product, exact, in packs", () => {
    const source = line({ quantity: 2 });
    const draft = draftItemFromCartLine(source);

    expect(draft).not.toBeNull();
    expect(draft?.categoryKey).toBe("leche-entera");
    expect(draft?.categoryName).toBe("Leche entera");
    const request = toRequestItem(draft!);
    expect(request.product_id).toBe(source.product_id);
    expect(request.accept).toBe("exact");
    expect(request.category_key).toBeUndefined();
    expect(request.brand).toBeNull();
    expect(request.quantity).toBe("2");
    expect(request.unit).toBe("ud");
  });

  it("carries the accept mode and the padlock of the line", () => {
    const draft = draftItemFromCartLine(line({ accept: "equivalent", locked: true }));

    expect(draft?.accept).toBe("equivalent");
    expect(draft?.locked).toBe(true);
    expect(toRequestItem(draft!).accept).toBe("equivalent");
  });

  it("sends a generic line without a brand", () => {
    const draft = draftItemFromCartLine(
      line({ product_id: null, name: "Leche entera", brand: null }),
    );

    expect(draft?.categoryKey).toBe("leche-entera");
    expect(draft?.text).toBe("Leche entera");
    expect(toRequestItem(draft!).brand).toBeNull();
  });

  it("drops lines without a category", () => {
    const classified = line({ id: "a" });
    const unclassified = line({ id: "b", product_id: 2, category_key: null });

    expect(draftItemsFromCart([classified, unclassified])).toHaveLength(1);
    expect(draftItemsFromCart([unclassified])).toEqual([]);
  });
});
