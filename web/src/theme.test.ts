import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getResolvedTheme,
  getStoredTheme,
  setThemePreference,
  subscribeTheme,
  THEME_STORAGE_KEY,
  toggleQuickTheme,
} from "./theme";

function setup(osDark: boolean) {
  const data = new Map<string, string>();
  const localStorage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
  const meta = { content: "light dark" };
  const mediaListeners = new Set<() => void>();
  const media = {
    matches: osDark,
    addEventListener: (_: string, fn: () => void) => mediaListeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => mediaListeners.delete(fn),
  };
  const windowListeners = new Map<string, Set<(event: unknown) => void>>();
  const fakeWindow = {
    localStorage,
    matchMedia: () => media,
    addEventListener: (type: string, fn: (event: unknown) => void) => {
      windowListeners.set(type, (windowListeners.get(type) ?? new Set()).add(fn));
    },
    removeEventListener: (type: string, fn: (event: unknown) => void) => {
      windowListeners.get(type)?.delete(fn);
    },
  };
  vi.stubGlobal("window", fakeWindow);
  vi.stubGlobal("document", { querySelector: () => meta });
  return { data, meta, media, mediaListeners, windowListeners };
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("theme preference", () => {
  it("defaults to the system and resolves it from the OS", () => {
    setup(true);
    expect(getStoredTheme()).toBe("system");
    expect(getResolvedTheme()).toBe("dark");
  });

  it("stores a literal choice and updates the meta tag", () => {
    const env = setup(false);
    setThemePreference("dark");
    expect(env.data.get(THEME_STORAGE_KEY)).toBe("dark");
    expect(env.meta.content).toBe("dark");
    expect(getResolvedTheme()).toBe("dark");
    setThemePreference("system");
    expect(env.data.has(THEME_STORAGE_KEY)).toBe(false);
    expect(env.meta.content).toBe("light dark");
  });
});

describe("toggleQuickTheme", () => {
  it("stores the opposite when it differs from the OS", () => {
    const env = setup(false);
    expect(toggleQuickTheme()).toBe("dark");
    expect(env.data.get(THEME_STORAGE_KEY)).toBe("dark");
    expect(env.meta.content).toBe("dark");
  });

  it("drops the stored value when the target matches the OS", () => {
    const env = setup(false);
    setThemePreference("dark");
    expect(toggleQuickTheme()).toBe("light");
    expect(env.data.has(THEME_STORAGE_KEY)).toBe(false);
    expect(env.meta.content).toBe("light dark");
  });
});

describe("subscribeTheme", () => {
  it("notifies on OS changes without deleting the stored choice", () => {
    const env = setup(false);
    setThemePreference("light");
    const listener = vi.fn();
    const unsubscribe = subscribeTheme(listener);
    env.mediaListeners.forEach((fn) => fn());
    expect(listener).toHaveBeenCalledTimes(1);
    expect(env.data.get(THEME_STORAGE_KEY)).toBe("light");
    unsubscribe();
    expect(env.mediaListeners.size).toBe(0);
  });

  it("follows storage events from other tabs", () => {
    const env = setup(false);
    const listener = vi.fn();
    subscribeTheme(listener);
    env.data.set(THEME_STORAGE_KEY, "dark");
    env.windowListeners.get("storage")?.forEach((fn) => fn({ key: THEME_STORAGE_KEY }));
    expect(env.meta.content).toBe("dark");
    expect(listener).toHaveBeenCalled();
  });
});
