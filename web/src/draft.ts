// The editable line the user reviews before asking for a basket.

import type {
  Accept,
  InterpretOption,
  InterpretedItem,
  RecommendationItemRequest,
  SearchResult,
  Unit,
} from "./api";

export const UNITS: Unit[] = ["ud", "kg", "g", "l", "ml"];

export interface DraftItem {
  id: string;
  /** Original text the user wrote, or the catalog name when picked there. */
  text: string;
  categoryKey: string | null;
  categoryName: string;
  quantity: string;
  unit: Unit;
  brand: string;
  privateLabelOk: boolean;
  /** Concrete product the line was added from; null for a generic line ("Cualquier X"). */
  productId: number | null;
  /** Only meaningful with `productId`: "exact" buys that product, "equivalent" any of its canonical. */
  accept: Accept;
  /** Pinned with the padlock: the global "Me da igual la marca" switch leaves it "exact". */
  locked: boolean;
  imageUrl: string | null;
  /** Choices for a vague line ("¿Qué pollo?"); the line cannot be sent until one is chosen. */
  options: InterpretOption[];
}

export function newId(): string {
  // `randomUUID` needs a secure context; keep working when the PWA is opened by IP.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function draftFromInterpreted(item: InterpretedItem): DraftItem {
  return {
    id: newId(),
    text: item.text,
    categoryKey: item.category_key,
    categoryName: item.category_name ?? "",
    quantity: item.quantity,
    unit: item.unit,
    brand: item.brand ?? "",
    privateLabelOk: true,
    ...GENERIC_DEFAULTS,
    imageUrl: item.image_url,
    options: item.options,
  };
}

/** Defaults of a generic line, the shape every line has unless it names a product. */
export const GENERIC_DEFAULTS = {
  productId: null,
  accept: "equivalent",
  locked: false,
  imageUrl: null,
  options: [],
} as const satisfies Pick<DraftItem, "productId" | "accept" | "locked" | "imageUrl" | "options">;

/** Lines saved before the concrete-product fields existed read as generic lines. */
export function withLineDefaults(item: Omit<DraftItem, keyof typeof GENERIC_DEFAULTS> &
  Partial<DraftItem>): DraftItem {
  return { ...GENERIC_DEFAULTS, ...item, options: item.options ?? [] };
}

export function draftFromSearchResult(result: SearchResult): DraftItem {
  return {
    id: newId(),
    text: result.name,
    categoryKey: result.key,
    categoryName: result.name,
    quantity: "1",
    unit: "ud",
    brand: "",
    privateLabelOk: true,
    ...GENERIC_DEFAULTS,
  };
}

/** A vague line becomes the option the user picked: a generic line of that category. */
export function chooseOption(item: DraftItem, option: InterpretOption): DraftItem {
  return {
    ...item,
    categoryKey: option.category_key,
    categoryName: option.name,
    imageUrl: option.image_url,
    options: [],
  };
}

export function isResolved(item: DraftItem): boolean {
  return item.options.length === 0 && (item.productId !== null || item.categoryKey !== null);
}

/**
 * "Me da igual la marca": every concrete line that is not pinned accepts its whole canonical.
 * Pinned lines keep their choice (decision 0019: the line's own choice wins over the switch).
 */
export function applyAnyBrand(items: DraftItem[]): DraftItem[] {
  return items.map((item) =>
    item.productId !== null && !item.locked && item.accept === "exact"
      ? { ...item, accept: "equivalent" }
      : item,
  );
}

export function allResolved(items: DraftItem[]): boolean {
  return items.length > 0 && items.every(isResolved);
}

/** Quantities travel as decimal strings with a dot, whatever the user typed. */
export function normalizeQuantity(value: string): string {
  return value.trim().replace(",", ".");
}

export function toRequestItem(item: DraftItem): RecommendationItemRequest {
  const brand = item.brand.trim();
  const target =
    item.productId !== null
      ? { product_id: item.productId, accept: item.accept, unit: "ud" as const }
      : { category_key: item.categoryKey, accept: "equivalent" as const, unit: item.unit };
  return {
    text: item.text,
    ...target,
    quantity: normalizeQuantity(item.quantity),
    // A concrete line names its product; its brand is not a filter.
    brand: item.productId !== null || brand === "" ? null : brand,
    private_label_ok: item.privateLabelOk,
  };
}

export function isUnit(value: unknown): value is Unit {
  return typeof value === "string" && (UNITS as string[]).includes(value);
}
