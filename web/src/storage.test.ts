import { describe, expect, it } from "vitest";
import { newId, type DraftItem } from "./draft";
import {
  createSavedList,
  loadLists,
  saveLists,
  SCHEMA_VERSION,
  STORAGE_KEY,
  upsertSavedList,
  type SavedList,
} from "./storage";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(key) ?? null,
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => {
      data.delete(key);
    },
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  } as Storage;
}

function item(overrides: Partial<DraftItem> = {}): DraftItem {
  return {
    id: newId(),
    text: "pan de molde",
    categoryKey: "leaf:pan",
    categoryName: "Pan de molde",
    quantity: "1",
    unit: "ud",
    brand: "",
    privateLabelOk: true,
    ...overrides,
  };
}

function list(overrides: Partial<SavedList> = {}): SavedList {
  return {
    ...createSavedList("Semanal", "pan de molde", [item()], new Date("2026-11-13T10:00:00Z")),
    ...overrides,
  };
}

describe("loadLists", () => {
  it("returns an empty list when nothing is stored", () => {
    expect(loadLists(memoryStorage())).toEqual([]);
  });

  it("returns an empty list when the JSON is broken", () => {
    const storage = memoryStorage();
    storage.setItem(STORAGE_KEY, "{not json");
    expect(loadLists(storage)).toEqual([]);
  });

  it("returns an empty list when the schema version is unknown", () => {
    const storage = memoryStorage();
    storage.setItem(STORAGE_KEY, JSON.stringify({ schema_version: 99, lists: [list()] }));
    expect(loadLists(storage)).toEqual([]);
  });

  it("ignores entries that do not match the stored shape", () => {
    const storage = memoryStorage();
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        schema_version: SCHEMA_VERSION,
        lists: [list(), { name: "rota" }, { ...list(), items: [{ text: "sin id" }] }],
      }),
    );
    expect(loadLists(storage)).toHaveLength(1);
  });

  it("returns an empty list when storage throws", () => {
    const storage = {
      getItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(loadLists(storage)).toEqual([]);
  });
});

describe("saveLists", () => {
  it("round-trips the lists with the schema version", () => {
    const storage = memoryStorage();
    const saved = [list()];

    saveLists(saved, storage);

    const payload = JSON.parse(storage.getItem(STORAGE_KEY) ?? "{}");
    expect(payload.schema_version).toBe(SCHEMA_VERSION);
    expect(loadLists(storage)).toEqual(saved);
  });

  it("does not throw when storage is full", () => {
    const storage = {
      setItem: () => {
        throw new Error("quota");
      },
    } as unknown as Storage;
    expect(() => saveLists([list()], storage)).not.toThrow();
  });
});

describe("upsertSavedList", () => {
  it("prepends a new list", () => {
    const existing = list({ id: "a", name: "Semanal" });
    const next = upsertSavedList([existing], list({ id: "b", name: "Fiesta" }));

    expect(next.map((entry) => entry.name)).toEqual(["Fiesta", "Semanal"]);
  });

  it("replaces the list with the same name, keeping its identity", () => {
    const existing = list({
      id: "a",
      name: "Semanal",
      text: "viejo",
      created_at: "2026-11-01T00:00:00.000Z",
    });
    const updated = list({ id: "b", name: "semanal", text: "nuevo" });

    const next = upsertSavedList([existing], updated);

    expect(next).toHaveLength(1);
    expect(next[0].id).toBe("a");
    expect(next[0].created_at).toBe("2026-11-01T00:00:00.000Z");
    expect(next[0].text).toBe("nuevo");
  });
});

describe("createSavedList", () => {
  it("sets the same timestamp for creation and update", () => {
    const created = createSavedList("Semanal", "pan", [], new Date("2026-11-13T10:00:00Z"));

    expect(created.created_at).toBe("2026-11-13T10:00:00.000Z");
    expect(created.updated_at).toBe(created.created_at);
    expect(created.id).not.toBe("");
  });
});
