// The editable line the user reviews before asking for a basket.

import type {
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
  };
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
  };
}

export function isResolved(item: DraftItem): boolean {
  return item.categoryKey !== null;
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
  return {
    text: item.text,
    category_key: item.categoryKey,
    quantity: normalizeQuantity(item.quantity),
    unit: item.unit,
    brand: brand === "" ? null : brand,
    private_label_ok: item.privateLabelOk,
  };
}

export function isUnit(value: unknown): value is Unit {
  return typeof value === "string" && (UNITS as string[]).includes(value);
}
