// Versioned browser storage for the user's saved lists (data model, browser storage).

import type { PriorityMode, TravelMode } from "./api";
import type { CartLine } from "./cart";
import { isUnit, newId, withLineDefaults, type DraftItem } from "./draft";

export const STORAGE_KEY = "smart-basket.lists";
/** Version 3 added origin and route options; versions 1 and 2 are still read. */
export const SCHEMA_VERSION = 3;
const LEGACY_SCHEMA_VERSIONS = [1, 2];

export interface SavedList {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  /** Raw text of the list, so it can be edited again. */
  text: string;
  items: DraftItem[];
}

export interface StoredOrigin {
  lat: number;
  lon: number;
  label: string;
}

export interface StoredRouteOptions {
  mode: TravelMode;
  maxStores: number;
  priority: PriorityMode;
  returnToOrigin: boolean;
}

export const DEFAULT_ROUTE_OPTIONS: StoredRouteOptions = {
  mode: "walk",
  maxStores: 2,
  priority: "balanced",
  returnToOrigin: true,
};

interface StoredPayload {
  schema_version: number;
  lists: SavedList[];
  cart: CartLine[];
  origin: StoredOrigin | null;
  options: StoredRouteOptions;
}

interface StoredStore {
  lists: SavedList[];
  cart: CartLine[];
  origin: StoredOrigin | null;
  options: StoredRouteOptions;
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

function isStoredOrigin(value: unknown): value is StoredOrigin {
  if (!isRecord(value)) return false;
  return (
    typeof value.lat === "number" &&
    Number.isFinite(value.lat) &&
    typeof value.lon === "number" &&
    Number.isFinite(value.lon) &&
    typeof value.label === "string"
  );
}

function isStoredRouteOptions(value: unknown): value is StoredRouteOptions {
  if (!isRecord(value)) return false;
  const modes: TravelMode[] = ["walk", "car"];
  const priorities: PriorityMode[] = ["savings", "balanced", "time"];
  return (
    typeof value.mode === "string" &&
    modes.includes(value.mode as TravelMode) &&
    typeof value.maxStores === "number" &&
    Number.isFinite(value.maxStores) &&
    typeof value.priority === "string" &&
    priorities.includes(value.priority as PriorityMode) &&
    typeof value.returnToOrigin === "boolean"
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
  const empty: StoredStore = {
    lists: [],
    cart: [],
    origin: null,
    options: DEFAULT_ROUTE_OPTIONS,
  };
  if (!storage) return empty;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return empty;
    const payload: unknown = JSON.parse(raw);
    if (!isRecord(payload) || !Array.isArray(payload.lists)) {
      return empty;
    }
    if (
      payload.schema_version !== SCHEMA_VERSION &&
      !LEGACY_SCHEMA_VERSIONS.includes(payload.schema_version as number)
    ) {
      return empty;
    }
    return {
      lists: payload.lists
        .filter(isSavedList)
        .map((list) => ({ ...list, items: list.items.map(withLineDefaults) })),
      cart: Array.isArray(payload.cart)
        ? payload.cart.filter(isCartLine).map(withCartDefaults)
        : [],
      origin: isStoredOrigin(payload.origin) ? payload.origin : null,
      options: isStoredRouteOptions(payload.options) ? payload.options : DEFAULT_ROUTE_OPTIONS,
    };
  } catch {
    return empty;
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
  const current = readStore(storage);
  writeStore({ ...current, lists }, storage);
}

export function loadCart(storage: Storage | null = defaultStorage()): CartLine[] {
  return readStore(storage).cart;
}

export function saveCart(cart: CartLine[], storage: Storage | null = defaultStorage()): void {
  const current = readStore(storage);
  writeStore({ ...current, cart }, storage);
}

export function loadOrigin(storage: Storage | null = defaultStorage()): StoredOrigin | null {
  return readStore(storage).origin;
}

export function saveOrigin(
  origin: StoredOrigin | null,
  storage: Storage | null = defaultStorage(),
): void {
  const current = readStore(storage);
  writeStore({ ...current, origin }, storage);
}

export function loadOptions(storage: Storage | null = defaultStorage()): StoredRouteOptions {
  return readStore(storage).options;
}

export function saveOptions(
  options: StoredRouteOptions,
  storage: Storage | null = defaultStorage(),
): void {
  const current = readStore(storage);
  writeStore({ ...current, options }, storage);
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
