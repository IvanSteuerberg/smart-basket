// Light/dark theme. The browser stays the source of truth: the page declares
// `<meta name="color-scheme">` and CSS reacts to it. A stored choice exists only while the user
// disagrees with the OS preference (dark-mode-toggle divergence rule).

import { useSyncExternalStore } from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "color-scheme";
const SYSTEM_SCHEME = "light dark";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function schemeMeta(): HTMLMetaElement | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
}

function osPrefersDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(DARK_QUERY).matches
    : false;
}

export function getStoredTheme(): ThemePreference {
  try {
    const value = storage()?.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

/** The theme the page is rendering right now. */
export function getResolvedTheme(): ResolvedTheme {
  const stored = getStoredTheme();
  return stored === "system" ? (osPrefersDark() ? "dark" : "light") : stored;
}

/** Applies a preference to the meta tag and the storage. "system" forgets any stored choice. */
export function setThemePreference(preference: ThemePreference): void {
  const meta = schemeMeta();
  try {
    if (preference === "system") storage()?.removeItem(THEME_STORAGE_KEY);
    else storage()?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage unavailable: the choice applies to this page only.
  }
  if (meta) meta.content = preference === "system" ? SYSTEM_SCHEME : preference;
  notify();
}

/**
 * Quick toggle: go to the opposite of what is rendered. If that matches the OS preference the
 * stored value is dropped (the page follows the system again); otherwise it is stored literally.
 */
export function toggleQuickTheme(): ResolvedTheme {
  const target: ResolvedTheme = getResolvedTheme() === "dark" ? "light" : "dark";
  const osTheme: ResolvedTheme = osPrefersDark() ? "dark" : "light";
  setThemePreference(target === osTheme ? "system" : target);
  return target;
}

const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

/**
 * Calls the listener when the stored choice changes (other tabs included) or the OS preference
 * flips. A stored value is never deleted because the OS changed.
 */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  const media = typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(DARK_QUERY)
    : null;
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
    const meta = schemeMeta();
    const stored = getStoredTheme();
    if (meta) meta.content = stored === "system" ? SYSTEM_SCHEME : stored;
    listener();
  };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  media?.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
    media?.removeEventListener("change", listener);
  };
}

export interface ThemeState {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => ResolvedTheme;
}

/** Snapshot string so `useSyncExternalStore` compares by value. */
function snapshot(): string {
  return `${getStoredTheme()}|${getResolvedTheme()}`;
}

export function useTheme(): ThemeState {
  const value = useSyncExternalStore(subscribeTheme, snapshot, () => "system|light");
  const [preference, resolved] = value.split("|") as [ThemePreference, ResolvedTheme];
  return { preference, resolved, setPreference: setThemePreference, toggle: toggleQuickTheme };
}
