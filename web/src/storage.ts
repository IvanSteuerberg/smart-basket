// Versioned browser storage for the user's saved lists (data model, browser storage).

import type { CartLine } from "./cart";
import { isUnit, newId, withLineDefaults, type DraftItem } from "./draft";

export const STORAGE_KEY = "smart-basket.lists";
/** Version 2 added the cart next to the saved lists; version 1 is still read. */
export const SCHEMA_VERSION = 2;
const LEGACY_SCHEMA_VERSION = 1;

export interface SavedList {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  /** Raw text of the list, so it can be edited again. */
  text: string;
  items: DraftItem[];
}

interface StoredPayload {
  schema_version: number;
  lists: SavedList[];
  cart: CartLine[];
}

interface StoredStore {
  lists: SavedList[];
  cart: CartLine[];
}

function defaultStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function isDraftItem(value: unknown): value is DraftItem {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.text === "string" &&
    (value.categoryKey === null || typeof value.categoryKey === "string") &&
    typeof value.categoryName === "string" &&
    typeof value.quantity === "string" &&
    isUnit(value.unit) &&
    typeof value.brand === "string" &&
    typeof value.privateLabelOk === "boolean"
  );
}

function isSavedList(value: unknown): value is SavedList {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    typeof value.text === "string" &&
    Array.isArray(value.items) &&
    value.items.every(isDraftItem)
  );
}

/** A line saved before `accept`/`locked` existed has them missing; the guard allows that. */
type StoredCartLine = Omit<CartLine, "accept" | "locked"> &
  Partial<Pick<CartLine, "accept" | "locked">>;

function isCartLine(value: unknown): value is StoredCartLine {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    (value.product_id === null || typeof value.product_id === "number") &&
    typeof value.name === "string" &&
    (value.brand === null || typeof value.brand === "string") &&
    (value.packaging === null || typeof value.packaging === "string") &&
    (value.image_url === null || typeof value.image_url === "string") &&
    (value.category_key === null || typeof value.category_key === "string") &&
    (value.category_name === null || typeof value.category_name === "string") &&
    typeof value.quantity === "number" &&
    Number.isFinite(value.quantity) &&
    value.quantity >= 1 &&
    (value.accept === undefined || value.accept === "exact" || value.accept === "equivalent") &&
    (value.locked === undefined || typeof value.locked === "boolean")
  );
}

/** Old concrete lines read as exact, old generic ones as equivalent, and nothing as pinned. */
function withCartDefaults(line: StoredCartLine): CartLine {
  return {
    ...line,
    accept: line.accept ?? (line.product_id === null ? "equivalent" : "exact"),
    locked: line.locked ?? false,
  };
}

function readStore(storage: Storage | null): StoredStore {
  if (!storage) return { lists: [], cart: [] };
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return { lists: [], cart: [] };
    const payload: unknown = JSON.parse(raw);
    if (!isRecord(payload) || !Array.isArray(payload.lists)) {
      return { lists: [], cart: [] };
    }
    if (
      payload.schema_version !== SCHEMA_VERSION &&
      payload.schema_version !== LEGACY_SCHEMA_VERSION
    ) {
      return { lists: [], cart: [] };
    }
    return {
      lists: payload.lists
        .filter(isSavedList)
        .map((list) => ({ ...list, items: list.items.map(withLineDefaults) })),
      cart: Array.isArray(payload.cart)
        ? payload.cart.filter(isCartLine).map(withCartDefaults)
        : [],
    };
  } catch {
    return { lists: [], cart: [] };
  }
}

function writeStore(store: StoredStore, storage: Storage | null): void {
  if (!storage) return;
  const payload: StoredPayload = { schema_version: SCHEMA_VERSION, ...store };
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage full or unavailable: the content stays in memory for this session.
  }
}

export function loadLists(storage: Storage | null = defaultStorage()): SavedList[] {
  return readStore(storage).lists;
}

export function saveLists(lists: SavedList[], storage: Storage | null = defaultStorage()): void {
  writeStore({ lists, cart: readStore(storage).cart }, storage);
}

export function loadCart(storage: Storage | null = defaultStorage()): CartLine[] {
  return readStore(storage).cart;
}

export function saveCart(cart: CartLine[], storage: Storage | null = defaultStorage()): void {
  writeStore({ lists: readStore(storage).lists, cart }, storage);
}

export function createSavedList(
  name: string,
  text: string,
  items: DraftItem[],
  now: Date = new Date(),
): SavedList {
  const timestamp = now.toISOString();
  return {
    id: newId(),
    name,
    text,
    items,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

/** Adds the list or replaces the one with the same name, keeping its identity. */
export function upsertSavedList(lists: SavedList[], list: SavedList): SavedList[] {
  const index = lists.findIndex(
    (candidate) =>
      candidate.id === list.id || candidate.name.toLowerCase() === list.name.toLowerCase(),
  );
  if (index === -1) return [list, ...lists];
  const previous = lists[index];
  const next = [...lists];
  next[index] = { ...list, id: previous.id, created_at: previous.created_at };
  return next;
}
