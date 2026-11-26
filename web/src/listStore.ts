// One list model for everything the user wants to buy (I17 M1): products picked in the catalog
// (specific or generic) and lines interpreted from text live in the same shape. A single brand
// switch (`pinBrand`) replaces the old `accept` + `locked` pair.

import type { InterpretOption, Unit } from "./api";
import { MAX_QUANTITY, MIN_QUANTITY, type CartLine } from "./cart";
import { GENERIC_DEFAULTS, newId, type DraftItem } from "./draft";

export interface UnifiedLine {
  id: string;
  /** What the user wrote, or the catalog name when picked there. */
  text: string;
  categoryKey: string | null;
  categoryName: string;
  /** Concrete product the line was added from; null for a generic line ("Cualquier X"). */
  productId: number | null;
  /** Brand typed by the user (generic text line) or of the picked product. */
  brand: string;
  packaging: string | null;
  imageUrl: string | null;
  /** Decimal string with a dot; for a concrete product it is the number of packs. */
  quantity: string;
  unit: Unit;
  privateLabelOk: boolean;
  /** The user wants exactly this product (brand included); false accepts any of its category. */
  pinBrand: boolean;
  /** The category only sells concrete products (shades): the line is always pinned. */
  exactOnly: boolean;
  /** Choices for a vague line ("¿Qué pollo?"); empty once resolved. */
  options: InterpretOption[];
}

export type ListAction =
  | { type: "add"; line: UnifiedLine }
  | { type: "replace"; lines: UnifiedLine[] }
  | { type: "update"; id: string; patch: Partial<Omit<UnifiedLine, "id">> }
  | { type: "setQuantity"; id: string; quantity: string }
  | { type: "setPinBrand"; id: string; pinBrand: boolean }
  | { type: "remove"; id: string }
  | { type: "clear" };

function parseQuantity(value: string): number {
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/** Packs and units are whole numbers within the cart limits; other units keep their decimals. */
function normalizeQuantity(quantity: string, unit: Unit): string {
  const parsed = parseQuantity(quantity);
  if (!Number.isFinite(parsed)) return String(MIN_QUANTITY);
  if (unit === "ud") return String(Math.min(MAX_QUANTITY, Math.max(MIN_QUANTITY, Math.round(parsed))));
  return String(Math.max(0, parsed));
}

/** A pinned line (or one of shades) buys exactly its product; the others accept any of its category. */
function pinned(line: Pick<UnifiedLine, "pinBrand" | "exactOnly">): boolean {
  return line.exactOnly || line.pinBrand;
}

function sameLine(a: UnifiedLine, b: UnifiedLine): boolean {
  if (a.unit !== b.unit) return false;
  if (a.productId !== null || b.productId !== null) return a.productId === b.productId;
  // Text lines without a category are never merged: the user has not resolved them yet.
  return a.categoryKey !== null && a.categoryKey === b.categoryKey;
}

export function listReducer(lines: UnifiedLine[], action: ListAction): UnifiedLine[] {
  switch (action.type) {
    case "add": {
      const index = lines.findIndex((line) => sameLine(line, action.line));
      if (index === -1) {
        return [
          ...lines,
          { ...action.line, quantity: normalizeQuantity(action.line.quantity, action.line.unit) },
        ];
      }
      return lines.map((line, position) => {
        if (position !== index) return line;
        const total = parseQuantity(line.quantity) + parseQuantity(action.line.quantity);
        return { ...line, quantity: normalizeQuantity(String(total), line.unit) };
      });
    }
    case "replace":
      return action.lines;
    case "update":
      return lines.map((line) =>
        line.id === action.id ? { ...line, ...action.patch, id: line.id } : line,
      );
    case "setQuantity":
      return lines.map((line) =>
        line.id === action.id
          ? { ...line, quantity: normalizeQuantity(action.quantity, line.unit) }
          : line,
      );
    case "setPinBrand":
      return lines.map((line) =>
        line.id === action.id && !line.exactOnly ? { ...line, pinBrand: action.pinBrand } : line,
      );
    case "remove":
      return lines.filter((line) => line.id !== action.id);
    case "clear":
      return [];
  }
}

/** A line of the old cart: a concrete line that accepted only itself reads as pinned. */
function fromCartLine(line: CartLine): UnifiedLine {
  const concrete = line.product_id !== null;
  return {
    id: line.id,
    text: line.name,
    categoryKey: line.category_key,
    categoryName: line.category_name ?? line.name,
    productId: line.product_id,
    brand: concrete ? (line.brand ?? "") : "",
    packaging: line.packaging,
    imageUrl: line.image_url,
    quantity: String(line.quantity),
    unit: "ud",
    privateLabelOk: true,
    pinBrand: concrete && (line.locked || line.accept === "exact"),
    exactOnly: line.exact_only,
    options: [],
  };
}

function fromDraftItem(item: DraftItem): UnifiedLine {
  const concrete = item.productId !== null;
  return {
    id: item.id,
    text: item.text,
    categoryKey: item.categoryKey,
    categoryName: item.categoryName,
    productId: item.productId,
    brand: item.brand,
    packaging: null,
    imageUrl: item.imageUrl,
    quantity: item.quantity,
    unit: item.unit,
    privateLabelOk: item.privateLabelOk,
    pinBrand: concrete && (item.locked || item.accept === "exact"),
    exactOnly: item.exactOnly,
    options: item.options,
  };
}

/** Merges the legacy cart and the text draft into one list; the cart lines come first. */
export function migrateCartToUnified(
  cart: CartLine[],
  draftItems: DraftItem[] = [],
): UnifiedLine[] {
  return [...cart.map(fromCartLine), ...draftItems.map(fromDraftItem)];
}

/** The editable lines the recommender flow sends; `locked` mirrors the single brand switch. */
export function toDraftItems(lines: UnifiedLine[]): DraftItem[] {
  return lines.map((line) => {
    const exact = line.productId !== null && pinned(line);
    return {
      id: line.id || newId(),
      text: line.text,
      categoryKey: line.categoryKey,
      categoryName: line.categoryName,
      quantity: line.quantity,
      unit: line.productId !== null ? "ud" : line.unit,
      brand: line.brand,
      privateLabelOk: line.privateLabelOk,
      ...GENERIC_DEFAULTS,
      productId: line.productId,
      accept: exact ? "exact" : "equivalent",
      locked: exact && line.pinBrand,
      imageUrl: line.imageUrl,
      options: line.options,
      exactOnly: line.exactOnly,
    };
  });
}

/** Units in the list, the number the header shows; a line by weight or volume counts as one. */
export function unifiedLineCount(lines: UnifiedLine[]): number {
  return lines.reduce((total, line) => {
    if (line.unit !== "ud") return total + 1;
    const parsed = parseQuantity(line.quantity);
    return total + (Number.isFinite(parsed) && parsed >= MIN_QUANTITY ? Math.round(parsed) : 1);
  }, 0);
}
