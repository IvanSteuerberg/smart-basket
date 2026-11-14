// The cart is the user's list: catalog products added before choosing an origin.

import type { Accept, CanonicalCard, Product } from "./api";
import { GENERIC_DEFAULTS, newId, type DraftItem } from "./draft";

export const MIN_QUANTITY = 1;
export const MAX_QUANTITY = 99;

export interface CartLine {
  id: string;
  /** Product the line was added from; null when the line is generic. */
  product_id: number | null;
  name: string;
  brand: string | null;
  packaging: string | null;
  image_url: string | null;
  /** Category of the canonical product, the one sent when computing the basket. */
  category_key: string | null;
  category_name: string | null;
  quantity: number;
  /** "exact" buys this product; "equivalent" accepts any product of its canonical. */
  accept: Accept;
  /** Pinned with the padlock: the global "Me da igual la marca" switch leaves it exact. */
  locked: boolean;
}

export type CartAction =
  | { type: "add"; line: CartLine }
  | { type: "setQuantity"; id: string; quantity: number }
  | { type: "setAccept"; id: string; accept: Accept }
  | { type: "toggleLock"; id: string }
  | { type: "anyBrand" }
  | { type: "remove"; id: string }
  | { type: "clear" };

export function isGenericLine(line: CartLine): boolean {
  return line.product_id === null;
}

export function clampQuantity(quantity: number): number {
  if (!Number.isFinite(quantity)) return MIN_QUANTITY;
  return Math.min(MAX_QUANTITY, Math.max(MIN_QUANTITY, Math.round(quantity)));
}

function sameLine(a: CartLine, b: CartLine): boolean {
  if (a.product_id !== null || b.product_id !== null) return a.product_id === b.product_id;
  return a.category_key === b.category_key;
}

export function cartReducer(lines: CartLine[], action: CartAction): CartLine[] {
  switch (action.type) {
    case "add": {
      const quantity = clampQuantity(action.line.quantity);
      const index = lines.findIndex((line) => sameLine(line, action.line));
      if (index === -1) return [...lines, { ...action.line, quantity }];
      return lines.map((line, position) =>
        position === index
          ? { ...line, quantity: clampQuantity(line.quantity + quantity) }
          : line,
      );
    }
    case "setQuantity":
      return lines.map((line) =>
        line.id === action.id ? { ...line, quantity: clampQuantity(action.quantity) } : line,
      );
    case "setAccept":
      return lines.map((line) =>
        line.id === action.id ? { ...line, accept: action.accept } : line,
      );
    case "toggleLock":
      return lines.map((line) =>
        line.id === action.id
          ? { ...line, locked: !line.locked, accept: line.locked ? line.accept : "exact" }
          : line,
      );
    case "anyBrand":
      // Same rule as `applyAnyBrand` in draft.ts: pinned lines keep their choice.
      return lines.map((line) =>
        line.product_id !== null && !line.locked && line.accept === "exact"
          ? { ...line, accept: "equivalent" }
          : line,
      );
    case "remove":
      return lines.filter((line) => line.id !== action.id);
    case "clear":
      return [];
  }
}

/** Total number of units in the cart, the number the header shows. */
export function cartItemCount(lines: CartLine[]): number {
  return lines.reduce((total, line) => total + line.quantity, 0);
}

/** A specific product: its own brand and packaging, its canonical for the basket. */
export function specificLine(product: Product, anyBrand = false): CartLine {
  return {
    id: newId(),
    product_id: product.id,
    name: product.name,
    brand: product.brand,
    packaging: product.packaging,
    image_url: product.image_url,
    category_key: product.canonical?.category_key ?? null,
    category_name: product.canonical?.name ?? null,
    quantity: MIN_QUANTITY,
    accept: anyBrand ? "equivalent" : "exact",
    locked: false,
  };
}

/** «Cualquier …»: any product of the canonical, keeping the photo it was added from. */
export function genericLine(product: Product): CartLine | null {
  if (product.canonical === null) return null;
  return {
    id: newId(),
    product_id: null,
    name: product.canonical.name,
    brand: null,
    packaging: null,
    image_url: product.image_url,
    category_key: product.canonical.category_key,
    category_name: product.canonical.name,
    quantity: MIN_QUANTITY,
    accept: "equivalent",
    locked: false,
  };
}

/** A generic line added from a canonical card: no concrete product, any of the canonical. */
export function canonicalLine(card: CanonicalCard): CartLine {
  return {
    id: newId(),
    product_id: null,
    name: card.name,
    brand: null,
    packaging: null,
    image_url: card.image_url,
    category_key: card.category_key,
    category_name: card.name,
    quantity: MIN_QUANTITY,
    accept: "equivalent",
    locked: false,
  };
}

/** The editable line sent to the recommender; null when the line has no category. */
export function draftItemFromCartLine(line: CartLine): DraftItem | null {
  if (line.category_key === null) return null;
  return {
    id: newId(),
    text: line.name,
    categoryKey: line.category_key,
    categoryName: line.category_name ?? line.name,
    quantity: String(line.quantity),
    unit: "ud",
    brand: isGenericLine(line) ? "" : (line.brand ?? ""),
    privateLabelOk: true,
    ...GENERIC_DEFAULTS,
    productId: line.product_id,
    accept: line.accept,
    locked: line.locked,
    imageUrl: line.image_url,
  };
}

export function draftItemsFromCart(lines: CartLine[]): DraftItem[] {
  return lines
    .map(draftItemFromCartLine)
    .filter((item): item is DraftItem => item !== null);
}
