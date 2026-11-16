// The shopper's local profile (decision 0019): explicit preferences and an event history.
// It lives in the browser; the same shape is later stored in PostgreSQL.

export type ScopeKind = "term" | "category" | "chain" | "global";
export type PreferenceKind =
  | "brand_pin"
  | "term_choice"
  | "chain_include"
  | "chain_exclude"
  | "dietary_rule"
  | "seasonal_rule"
  | "any_brand";

export interface Preference {
  id: string;
  scope_kind: ScopeKind;
  scope_key: string;
  kind: PreferenceKind;
  value: unknown;
  origin: "explicit" | "imported";
  consent_ref: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface ChoiceEvent {
  id: string;
  term: string;
  action: "accepted" | "replaced" | "removed" | "pinned";
  canonical_id: number | null;
  product_id: number | null;
  brand: string | null;
  chain: string | null;
  date: string;
}

export interface Profile {
  schema_version: 1;
  preferences: Preference[];
  events: ChoiceEvent[];
}

export interface ProfileStore {
  load(): Promise<Profile>;
  save(profile: Profile): Promise<void>;
}

/** The fields that identify a preference; the value is the only part that changes. */
export type PreferenceKey = Pick<Preference, "scope_kind" | "scope_key" | "kind">;
export type PreferenceInput = PreferenceKey & { value: unknown };

const SCOPE_KINDS: ScopeKind[] = ["term", "category", "chain", "global"];
const PREFERENCE_KINDS: PreferenceKind[] = [
  "brand_pin",
  "term_choice",
  "chain_include",
  "chain_exclude",
  "dietary_rule",
  "seasonal_rule",
  "any_brand",
];
const EVENT_ACTIONS: ChoiceEvent["action"][] = ["accepted", "replaced", "removed", "pinned"];

export function emptyProfile(): Profile {
  return { schema_version: 1, preferences: [], events: [] };
}

// --- uuidv7 ---------------------------------------------------------------

let lastUuidTime = -1;
let uuidSequence = 0;

function randomBytes(bytes: Uint8Array<ArrayBuffer>): void {
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
    return;
  }
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Math.floor(Math.random() * 256);
  }
}

/**
 * A small uuidv7: the 48-bit millisecond timestamp first, so ids sort by time.
 * Within the same millisecond a 12-bit counter keeps the order.
 */
export function uuidv7(now: number = Date.now()): string {
  const time = Math.max(0, Math.floor(now));
  if (time === lastUuidTime) {
    uuidSequence = (uuidSequence + 1) & 0xfff;
  } else {
    lastUuidTime = time;
    uuidSequence = 0;
  }

  const bytes = new Uint8Array(16);
  randomBytes(bytes);
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = (time / 2 ** (8 * (5 - index))) & 0xff;
  }
  bytes[6] = 0x70 | ((uuidSequence >> 8) & 0x0f);
  bytes[7] = uuidSequence & 0xff;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return (
    `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-` +
    `${hex.slice(16, 20)}-${hex.slice(20, 32)}`
  );
}

// --- preference operations ------------------------------------------------

function sameKey(a: PreferenceKey, b: PreferenceKey): boolean {
  return a.scope_kind === b.scope_kind && a.scope_key === b.scope_key && a.kind === b.kind;
}

/** Inserts or updates the single live row for a (scope, key, kind) triple. */
export function setPreference(profile: Profile, input: PreferenceInput, now: Date): Profile {
  const timestamp = now.toISOString();
  const index = profile.preferences.findIndex(
    (candidate) => candidate.deleted_at === null && sameKey(candidate, input),
  );
  if (index !== -1) {
    const preferences = profile.preferences.map((candidate, position) =>
      position === index ? { ...candidate, value: input.value, updated_at: timestamp } : candidate,
    );
    return { ...profile, preferences };
  }
  const preference: Preference = {
    id: uuidv7(now.getTime()),
    scope_kind: input.scope_kind,
    scope_key: input.scope_key,
    kind: input.kind,
    value: input.value,
    origin: "explicit",
    consent_ref: null,
    created_at: timestamp,
    updated_at: timestamp,
    deleted_at: null,
  };
  return { ...profile, preferences: [...profile.preferences, preference] };
}

/** Tombstones the live rows that match a key; it is a no-op when there are none. */
export function removePreference(profile: Profile, key: PreferenceKey, now: Date): Profile {
  const timestamp = now.toISOString();
  let changed = false;
  const preferences = profile.preferences.map((candidate) => {
    if (candidate.deleted_at !== null || !sameKey(candidate, key)) return candidate;
    changed = true;
    return { ...candidate, updated_at: timestamp, deleted_at: timestamp };
  });
  return changed ? { ...profile, preferences } : profile;
}

export function livePreferences(profile: Profile): Preference[] {
  return profile.preferences.filter((preference) => preference.deleted_at === null);
}

export function appendEvent(profile: Profile, event: ChoiceEvent): Profile {
  return { ...profile, events: [...profile.events, event] };
}

export function exportProfile(profile: Profile): string {
  return JSON.stringify(profile, null, 2);
}

// --- validation -----------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || typeof value === "number";
}

function isPreference(value: unknown): value is Preference {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    (SCOPE_KINDS as string[]).includes(value.scope_kind as string) &&
    typeof value.scope_key === "string" &&
    (PREFERENCE_KINDS as string[]).includes(value.kind as string) &&
    Object.prototype.hasOwnProperty.call(value, "value") &&
    (value.origin === "explicit" || value.origin === "imported") &&
    isNullableString(value.consent_ref) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    isNullableString(value.deleted_at)
  );
}

function isChoiceEvent(value: unknown): value is ChoiceEvent {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.term === "string" &&
    (EVENT_ACTIONS as string[]).includes(value.action as string) &&
    isNullableNumber(value.canonical_id) &&
    isNullableNumber(value.product_id) &&
    isNullableString(value.brand) &&
    isNullableString(value.chain) &&
    typeof value.date === "string"
  );
}

/** Reads a parsed payload, dropping whatever does not match the profile shape. */
function profileFrom(value: unknown): Profile {
  if (!isRecord(value)) return emptyProfile();
  const preferences = Array.isArray(value.preferences)
    ? value.preferences.filter(isPreference)
    : [];
  const events = Array.isArray(value.events) ? value.events.filter(isChoiceEvent) : [];
  return { schema_version: 1, preferences, events };
}

/**
 * Merges an exported profile into the current one: live preferences are matched
 * by (scope, key, kind), so imported rows that did not exist are marked as
 * imported; events are a union by id.
 */
export function importProfile(json: string, current: Profile = emptyProfile()): Profile {
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return current;
  }
  if (!isRecord(parsed)) return current;

  const preferences = [...current.preferences];
  for (const imported of profileFrom(parsed).preferences) {
    if (imported.deleted_at !== null) {
      const live = preferences.findIndex(
        (candidate) => candidate.deleted_at === null && sameKey(candidate, imported),
      );
      if (live !== -1) {
        const existing = preferences[live];
        preferences[live] = {
          ...existing,
          updated_at: imported.updated_at,
          deleted_at: imported.deleted_at,
        };
      } else if (!preferences.some((candidate) => candidate.id === imported.id)) {
        preferences.push({ ...imported, origin: "imported" });
      }
      continue;
    }

    const live = preferences.findIndex(
      (candidate) => candidate.deleted_at === null && sameKey(candidate, imported),
    );
    if (live !== -1) {
      const existing = preferences[live];
      preferences[live] = {
        ...imported,
        id: existing.id,
        origin: existing.origin,
        consent_ref: existing.consent_ref,
        created_at: existing.created_at,
      };
    } else if (!preferences.some((candidate) => candidate.id === imported.id)) {
      preferences.push({ ...imported, origin: "imported" });
    }
  }

  const seen = new Set(current.events.map((event) => event.id));
  const events = [...current.events];
  for (const event of profileFrom(parsed).events) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    events.push(event);
  }

  return { schema_version: 1, preferences, events };
}

// --- stores ---------------------------------------------------------------

export function memoryProfileStore(initial: Profile = emptyProfile()): ProfileStore {
  let current = initial;
  return {
    load: () => Promise.resolve(current),
    save: (profile) => {
      current = profile;
      return Promise.resolve();
    },
  };
}

const DB_NAME = "smart-basket";
const DB_STORE = "profile";
const DB_KEY = "profile";

function openProfileDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const factory = typeof indexedDB === "undefined" ? undefined : indexedDB;
    if (!factory) {
      reject(new Error("IndexedDB is not available"));
      return;
    }
    const request = factory.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(DB_STORE)) {
        request.result.createObjectStore(DB_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB open failed"));
    request.onblocked = () => reject(new Error("IndexedDB is blocked"));
  });
}

function readStoredProfile(database: IDBDatabase): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(DB_STORE, "readonly");
    const request = transaction.objectStore(DB_STORE).get(DB_KEY);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB read failed"));
  });
}

function writeStoredProfile(database: IDBDatabase, profile: Profile): Promise<void> {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(DB_STORE, "readwrite");
    transaction.objectStore(DB_STORE).put(profile, DB_KEY);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("IndexedDB write failed"));
    transaction.onabort = () => reject(transaction.error ?? new Error("IndexedDB write aborted"));
  });
}

/**
 * IndexedDB-backed store with a memory fallback: in private mode, or when the
 * database is blocked, the app keeps working for the session.
 */
export function indexedDbProfileStore(): ProfileStore {
  const fallback = memoryProfileStore();
  let database: Promise<IDBDatabase> | null = null;

  function connect(): Promise<IDBDatabase> {
    if (database === null) {
      database = openProfileDb().catch((error: unknown) => {
        database = null;
        throw error;
      });
    }
    return database;
  }

  return {
    async load() {
      try {
        return profileFrom(await readStoredProfile(await connect()));
      } catch {
        return fallback.load();
      }
    },
    async save(profile) {
      try {
        await writeStoredProfile(await connect(), profile);
      } catch {
        await fallback.save(profile);
      }
    },
  };
}

let persistenceRequested = false;

/** Asks the browser to keep the site data; best effort and at most once. */
export function requestPersistence(): void {
  if (persistenceRequested) return;
  persistenceRequested = true;
  try {
    const storage = typeof navigator === "undefined" ? undefined : navigator.storage;
    if (storage && typeof storage.persist === "function") {
      void storage.persist().catch(() => undefined);
    }
  } catch {
    // Requesting persistence is optional.
  }
}
