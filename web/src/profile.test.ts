import { describe, expect, it } from "vitest";
import {
  appendEvent,
  emptyProfile,
  exportProfile,
  importProfile,
  indexedDbProfileStore,
  livePreferences,
  memoryProfileStore,
  removePreference,
  setPreference,
  uuidv7,
  type ChoiceEvent,
  type PreferenceInput,
} from "./profile";

const NOW = new Date("2026-11-14T10:00:00Z");
const LATER = new Date("2026-11-15T10:00:00Z");

const pin: PreferenceInput = {
  scope_kind: "category",
  scope_key: "leche-entera",
  kind: "brand_pin",
  value: { product_id: 1, brand: "Pascual" },
};

const anyBrand: PreferenceInput = {
  scope_kind: "global",
  scope_key: "any_brand",
  kind: "any_brand",
  value: true,
};

const event: ChoiceEvent = {
  id: "event-1",
  term: "Leche entera",
  action: "pinned",
  canonical_id: 10,
  product_id: 1,
  brand: "Pascual",
  chain: null,
  date: NOW.toISOString(),
};

describe("uuidv7", () => {
  it("builds a version 7 uuid", () => {
    expect(uuidv7(NOW.getTime())).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("sorts by time, also within the same millisecond", () => {
    const first = uuidv7(NOW.getTime());
    const second = uuidv7(NOW.getTime());
    const later = uuidv7(LATER.getTime());

    expect(first < second).toBe(true);
    expect(second < later).toBe(true);
  });
});

describe("setPreference", () => {
  it("inserts one live row with an explicit origin", () => {
    const profile = setPreference(emptyProfile(), pin, NOW);

    expect(profile.preferences).toHaveLength(1);
    expect(profile.preferences[0]).toMatchObject({
      ...pin,
      origin: "explicit",
      created_at: NOW.toISOString(),
      updated_at: NOW.toISOString(),
      deleted_at: null,
    });
  });

  it("updates the same live row instead of duplicating it", () => {
    const first = setPreference(emptyProfile(), pin, NOW);
    const updated = setPreference(first, { ...pin, value: { product_id: 2, brand: "Dia" } }, LATER);

    expect(updated.preferences).toHaveLength(1);
    expect(updated.preferences[0].id).toBe(first.preferences[0].id);
    expect(updated.preferences[0].value).toEqual({ product_id: 2, brand: "Dia" });
    expect(updated.preferences[0].created_at).toBe(NOW.toISOString());
    expect(updated.preferences[0].updated_at).toBe(LATER.toISOString());
  });

  it("inserts a new row when the previous one was tombstoned", () => {
    const inserted = setPreference(emptyProfile(), pin, NOW);
    const removed = removePreference(
      inserted,
      { scope_kind: pin.scope_kind, scope_key: pin.scope_key, kind: pin.kind },
      LATER,
    );
    const again = setPreference(removed, pin, LATER);

    expect(again.preferences).toHaveLength(2);
    expect(livePreferences(again)).toHaveLength(1);
  });
});

describe("removePreference", () => {
  it("tombstones the live row and keeps it in the profile", () => {
    const profile = setPreference(emptyProfile(), anyBrand, NOW);
    const removed = removePreference(
      profile,
      { scope_kind: "global", scope_key: "any_brand", kind: "any_brand" },
      LATER,
    );

    expect(removed.preferences).toHaveLength(1);
    expect(removed.preferences[0].deleted_at).toBe(LATER.toISOString());
    expect(livePreferences(removed)).toEqual([]);
  });

  it("is a no-op when no live row matches", () => {
    const profile = setPreference(emptyProfile(), pin, NOW);
    const removed = removePreference(
      profile,
      { scope_kind: "chain", scope_key: "mercadona", kind: "chain_include" },
      LATER,
    );

    expect(removed).toBe(profile);
  });
});

describe("exportProfile and importProfile", () => {
  it("round-trips the profile", () => {
    const profile = appendEvent(setPreference(emptyProfile(), pin, NOW), event);
    const imported = importProfile(exportProfile(profile));

    expect(imported.preferences).toHaveLength(1);
    expect(imported.preferences[0].value).toEqual(pin.value);
    expect(imported.events).toHaveLength(1);
  });

  it("returns the current profile when the JSON is broken", () => {
    const current = setPreference(emptyProfile(), pin, NOW);
    expect(importProfile("{not json", current)).toBe(current);
  });

  it("discards preferences and events that do not match the shape", () => {
    const payload = JSON.stringify({
      schema_version: 1,
      preferences: [
        {
          id: "p1",
          scope_kind: "chain",
          scope_key: "mercadona",
          kind: "chain_include",
          value: true,
          origin: "explicit",
          consent_ref: null,
          created_at: NOW.toISOString(),
          updated_at: NOW.toISOString(),
          deleted_at: null,
        },
        { id: "p2", scope_kind: "inventado", scope_key: "x", kind: "brand_pin", value: 1 },
        { id: "p3", kind: "brand_pin" },
      ],
      events: [event, { id: "bad" }],
    });

    const imported = importProfile(payload);

    expect(imported.preferences).toHaveLength(1);
    expect(imported.preferences[0].scope_key).toBe("mercadona");
    expect(imported.events).toHaveLength(1);
  });

  it("marks imported preferences that did not exist as imported", () => {
    const current = setPreference(emptyProfile(), pin, NOW);
    const incoming = setPreference(emptyProfile(), anyBrand, LATER);

    const merged = importProfile(exportProfile(incoming), current);

    expect(merged.preferences).toHaveLength(2);
    const imported = merged.preferences.find((candidate) => candidate.kind === "any_brand");
    expect(imported?.origin).toBe("imported");
    const existing = merged.preferences.find((candidate) => candidate.kind === "brand_pin");
    expect(existing?.origin).toBe("explicit");
  });

  it("updates an existing preference without changing its identity or origin", () => {
    const current = setPreference(emptyProfile(), pin, NOW);
    const incoming = setPreference(
      emptyProfile(),
      { ...pin, value: { product_id: 2, brand: "Dia" } },
      LATER,
    );

    const merged = importProfile(exportProfile(incoming), current);

    expect(merged.preferences).toHaveLength(1);
    expect(merged.preferences[0].id).toBe(current.preferences[0].id);
    expect(merged.preferences[0].origin).toBe("explicit");
    expect(merged.preferences[0].value).toEqual({ product_id: 2, brand: "Dia" });
  });

  it("unions events by id", () => {
    const current = appendEvent(emptyProfile(), event);
    const other: ChoiceEvent = { ...event, id: "event-2", action: "accepted" };
    const incoming = appendEvent(appendEvent(emptyProfile(), event), other);

    const merged = importProfile(exportProfile(incoming), current);

    expect(merged.events.map((entry) => entry.id)).toEqual(["event-1", "event-2"]);
  });
});

describe("memoryProfileStore", () => {
  it("loads what was saved", async () => {
    const store = memoryProfileStore();
    const profile = setPreference(emptyProfile(), pin, NOW);

    await store.save(profile);

    await expect(store.load()).resolves.toEqual(profile);
  });
});

describe("indexedDbProfileStore", () => {
  it("falls back to memory when IndexedDB is not available", async () => {
    const store = indexedDbProfileStore();
    const profile = setPreference(emptyProfile(), pin, NOW);

    await expect(store.save(profile)).resolves.toBeUndefined();
    await expect(store.load()).resolves.toEqual(profile);
  });
});
