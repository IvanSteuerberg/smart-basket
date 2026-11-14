// Tiny hash router: the app has a handful of pages and no server-side routes.

import { useSyncExternalStore } from "react";

export type Route =
  | { name: "home" }
  | { name: "catalog"; section: string | null }
  | { name: "product"; id: number }
  | { name: "list" };

export const HOME_HASH = "#/";
export const CATALOG_HASH = "#/catalogo";
export const LIST_HASH = "#/lista";

export function catalogHash(section: string | null): string {
  return section === null ? CATALOG_HASH : `${CATALOG_HASH}/${encodeURIComponent(section)}`;
}

export function productHash(id: number): string {
  return `#/producto/${id}`;
}

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/** Unknown hashes fall back to the home page. */
export function parseRoute(hash: string): Route {
  const path = hash.startsWith("#") ? hash.slice(1) : hash;
  const clean = path.split("?")[0].replace(/\/+$/, "");
  const parts = clean.split("/").filter((part) => part !== "").map(decode);

  if (parts.length === 0) return { name: "home" };
  if (parts[0] === "catalogo" && parts.length <= 2) {
    return { name: "catalog", section: parts[1] ?? null };
  }
  if (parts[0] === "producto" && parts.length === 2 && /^\d+$/.test(parts[1])) {
    return { name: "product", id: Number(parts[1]) };
  }
  if (parts[0] === "lista" && parts.length === 1) return { name: "list" };
  return { name: "home" };
}

export function navigate(hash: string): void {
  window.location.hash = hash;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function currentHash(): string {
  return typeof window === "undefined" ? "" : window.location.hash;
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, currentHash, () => "");
  return parseRoute(hash);
}
