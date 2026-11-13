// Versioned browser storage for the user's saved lists (data model, browser storage).

import { isUnit, newId, type DraftItem } from "./draft";

export const STORAGE_KEY = "smart-basket.lists";
export const SCHEMA_VERSION = 1;

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

export function loadLists(storage: Storage | null = defaultStorage()): SavedList[] {
  if (!storage) return [];
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const payload: unknown = JSON.parse(raw);
    if (
      !isRecord(payload) ||
      payload.schema_version !== SCHEMA_VERSION ||
      !Array.isArray(payload.lists)
    ) {
      return [];
    }
    return payload.lists.filter(isSavedList);
  } catch {
    return [];
  }
}

export function saveLists(lists: SavedList[], storage: Storage | null = defaultStorage()): void {
  if (!storage) return;
  const payload: StoredPayload = { schema_version: SCHEMA_VERSION, lists };
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage full or unavailable: the lists stay in memory for this session.
  }
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
