import { describe, expect, it } from "vitest";
import type { CartLine } from "./cart";
import { GENERIC_DEFAULTS, newId, type DraftItem } from "./draft";
import {
  createSavedList,
  DEFAULT_ROUTE_OPTIONS,
  loadCart,
  loadLists,
  loadOptions,
  loadOrigin,
  saveCart,
  saveLists,
  saveOptions,
  saveOrigin,
  SCHEMA_VERSION,
  STORAGE_KEY,
  upsertSavedList,
  type SavedList,
  type StoredOrigin,
  type StoredRouteOptions,
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
    ...GENERIC_DEFAULTS,
    ...overrides,
  };
}

function list(overrides: Partial<SavedList> = {}): SavedList {
  return {
    ...createSavedList("Semanal", "pan de molde", [item()], new Date("2026-11-13T10:00:00Z")),
    ...overrides,
  };
}

function cartLine(overrides: Partial<CartLine> = {}): CartLine {
  return {
    id: newId(),
    product_id: 1,
    name: "Leche entera 1 L",
    brand: "Pascual",
    packaging: "Botella 1 L",
    image_url: null,
    category_key: "leche-entera",
    category_name: "Leche entera",
    quantity: 2,
    accept: "exact",
    locked: false,
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

  it("validates draft items with new fields and discards invalid ones", () => {
    const storage = memoryStorage();
    const baseValidItem = item();

    // Valid item with all new fields
    const fullValidItem = item({
      productId: 101,
      accept: "exact",
      locked: true,
      imageUrl: "https://photos.test/p.png",
      options: [
        {
          category_key: "pollo_pechuga",
          name: "Pechuga de pollo",
          image_url: null,
          from_unit_price: "2.50",
          base_unit: "kg",
        },
      ],
    });

    // Valid item without new fields (legacy)
    const legacyItem = {
      id: "leg-1",
      text: "leche",
      categoryKey: "leche-entera",
      categoryName: "Leche entera",
      quantity: "1",
      unit: "l",
      brand: "Pascual",
      privateLabelOk: true,
    };

    // Invalid: options is not an array
    const invalidOptionsType = { ...baseValidItem, options: "not an array" };
    // Invalid: options array contains invalid element (missing name)
    const invalidOptionsElement = { ...baseValidItem, options: [{ category_key: "k" }] };
    // Invalid: options array contains non-string category_key
    const invalidOptionsKey = { ...baseValidItem, options: [{ category_key: 123, name: "Name" }] };
    // Invalid: productId is a float
    const invalidProductIdFloat = { ...baseValidItem, productId: 1.5 };
    // Invalid: productId is a string
    const invalidProductIdString = { ...baseValidItem, productId: "101" };
    // Invalid: accept is not exact or equivalent
    const invalidAccept = { ...baseValidItem, accept: "other" };
    // Invalid: locked is not boolean
    const invalidLocked = { ...baseValidItem, locked: "true" };
    // Invalid: imageUrl is not string or null
    const invalidImageUrl = { ...baseValidItem, imageUrl: 123 };

    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        schema_version: SCHEMA_VERSION,
        lists: [
          list({ id: "valid-full", items: [fullValidItem] }),
          list({ id: "valid-legacy", items: [legacyItem as unknown as DraftItem] }),
          list({ id: "invalid-opt-type", items: [invalidOptionsType as unknown as DraftItem] }),
          list({ id: "invalid-opt-elem", items: [invalidOptionsElement as unknown as DraftItem] }),
          list({ id: "invalid-opt-key", items: [invalidOptionsKey as unknown as DraftItem] }),
          list({ id: "invalid-prod-float", items: [invalidProductIdFloat as unknown as DraftItem] }),
          list({ id: "invalid-prod-str", items: [invalidProductIdString as unknown as DraftItem] }),
          list({ id: "invalid-accept", items: [invalidAccept as unknown as DraftItem] }),
          list({ id: "invalid-locked", items: [invalidLocked as unknown as DraftItem] }),
          list({ id: "invalid-image", items: [invalidImageUrl as unknown as DraftItem] }),
        ],
      }),
    );

    const loaded = loadLists(storage);
    expect(loaded).toHaveLength(2);
    expect(loaded.map((l) => l.id)).toEqual(["valid-full", "valid-legacy"]);
    expect(loaded[1].items[0]).toMatchObject({
      productId: null,
      accept: "equivalent",
      locked: false,
      imageUrl: null,
      options: [],
    });
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

describe("cart storage", () => {
  it("round-trips the cart next to the lists", () => {
    const storage = memoryStorage();
    const savedList = list();
    const cart = [cartLine()];

    saveLists([savedList], storage);
    saveCart(cart, storage);

    expect(loadCart(storage)).toEqual(cart);
    // Saving the cart did not drop the lists.
    expect(loadLists(storage)).toEqual([savedList]);
  });

  it("keeps the cart when the lists are saved again", () => {
    const storage = memoryStorage();
    const cart = [cartLine()];
    saveCart(cart, storage);

    saveLists([list()], storage);

    expect(loadCart(storage)).toEqual(cart);
  });

  it("migrates a version 1 payload: the lists survive, the cart starts empty", () => {
    const storage = memoryStorage();
    const legacy = { schema_version: 1, lists: [list()] };
    storage.setItem(STORAGE_KEY, JSON.stringify(legacy));

    expect(loadLists(storage)).toHaveLength(1);
    expect(loadCart(storage)).toEqual([]);
  });

  it("gives saved lines without accept or locked their old defaults", () => {
    const storage = memoryStorage();
    const concrete = {
      id: "old-concrete",
      product_id: 1,
      name: "Leche entera 1 L",
      brand: "Pascual",
      packaging: null,
      image_url: null,
      category_key: "leche-entera",
      category_name: "Leche entera",
      quantity: 1,
    };
    const generic = {
      ...concrete,
      id: "old-generic",
      product_id: null,
      brand: null,
    };
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ schema_version: SCHEMA_VERSION, lists: [], cart: [concrete, generic] }),
    );

    const loaded = loadCart(storage);

    expect(loaded[0]).toMatchObject({ accept: "exact", locked: false });
    expect(loaded[1]).toMatchObject({ accept: "equivalent", locked: false });
  });

  it("ignores cart lines that do not match the stored shape", () => {
    const storage = memoryStorage();
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        schema_version: SCHEMA_VERSION,
        lists: [],
        cart: [cartLine(), { id: "rota" }, { ...cartLine(), quantity: 0 }],
      }),
    );

    expect(loadCart(storage)).toHaveLength(1);
  });

  it("returns an empty cart when storage throws or version is unknown", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(loadCart(blocked)).toEqual([]);

    const storage = memoryStorage();
    storage.setItem(STORAGE_KEY, JSON.stringify({ schema_version: 99, lists: [], cart: [] }));
    expect(loadCart(storage)).toEqual([]);
  });

  it("does not throw when the cart cannot be written", () => {
    const storage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota");
      },
    } as unknown as Storage;

    expect(() => saveCart([cartLine()], storage)).not.toThrow();
  });
});

describe("origin and options storage (schema 3)", () => {
  const origin: StoredOrigin = {
    lat: 42.5987,
    lon: -5.5671,
    label: "Plaza Mayor, 24003 León",
  };

  const customOptions: StoredRouteOptions = {
    mode: "car",
    maxStores: 3,
    priority: "savings",
    returnToOrigin: false,
  };

  it("round-trips origin and options with schema version 3", () => {
    const storage = memoryStorage();
    saveOrigin(origin, storage);
    saveOptions(customOptions, storage);

    expect(loadOrigin(storage)).toEqual(origin);
    expect(loadOptions(storage)).toEqual(customOptions);

    const payload = JSON.parse(storage.getItem(STORAGE_KEY) ?? "{}");
    expect(payload.schema_version).toBe(3);
  });

  it("preserves lists and cart when updating origin or options", () => {
    const storage = memoryStorage();
    const savedList = list();
    const cart = [cartLine()];
    saveLists([savedList], storage);
    saveCart(cart, storage);

    saveOrigin(origin, storage);
    saveOptions(customOptions, storage);

    expect(loadLists(storage)).toEqual([savedList]);
    expect(loadCart(storage)).toEqual(cart);
    expect(loadOrigin(storage)).toEqual(origin);
    expect(loadOptions(storage)).toEqual(customOptions);
  });

  it("migrates a version 1 payload: origin is null and options use defaults", () => {
    const storage = memoryStorage();
    const legacy = { schema_version: 1, lists: [list()] };
    storage.setItem(STORAGE_KEY, JSON.stringify(legacy));

    expect(loadLists(storage)).toHaveLength(1);
    expect(loadCart(storage)).toEqual([]);
    expect(loadOrigin(storage)).toBeNull();
    expect(loadOptions(storage)).toEqual(DEFAULT_ROUTE_OPTIONS);
  });

  it("migrates a version 2 payload: lists and cart survive, origin is null, options use defaults", () => {
    const storage = memoryStorage();
    const legacy = { schema_version: 2, lists: [list()], cart: [cartLine()] };
    storage.setItem(STORAGE_KEY, JSON.stringify(legacy));

    expect(loadLists(storage)).toHaveLength(1);
    expect(loadCart(storage)).toHaveLength(1);
    expect(loadOrigin(storage)).toBeNull();
    expect(loadOptions(storage)).toEqual(DEFAULT_ROUTE_OPTIONS);
  });

  it("handles saving null origin to clear it", () => {
    const storage = memoryStorage();
    saveOrigin(origin, storage);
    expect(loadOrigin(storage)).toEqual(origin);

    saveOrigin(null, storage);
    expect(loadOrigin(storage)).toBeNull();
  });

  it("ignores corrupted origin or options and falls back to safe defaults", () => {
    const storage = memoryStorage();
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        schema_version: 3,
        lists: [],
        cart: [],
        origin: { lat: "not a number", lon: -5.5, label: 123 },
        options: { mode: "rocket", maxStores: "invalid" },
      }),
    );

    expect(loadOrigin(storage)).toBeNull();
    expect(loadOptions(storage)).toEqual(DEFAULT_ROUTE_OPTIONS);
  });
});

