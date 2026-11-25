// Tiny hash router: the app has a handful of pages and no server-side routes.

import { useSyncExternalStore } from "react";
import type { CanonicalSort } from "./api";

/** The catalog can be browsed by generic product (default) or by supermarket. */
export type CatalogView = "product" | "super";

/** Catalog filters kept in the URL so a filtered view can be shared and survives a reload. */
export interface CatalogFilters {
  q: string;
  /** Sub-category (group or leaf key) inside the section. */
  sub: string | null;
  chains: string[];
  brand: string;
  privateLabel: boolean;
  dietary: string[];
  onPromo: boolean;
  minPrice: number | null;
  maxPrice: number | null;
  /** Only products in stores near the saved origin. */
  near: boolean;
  sort: CanonicalSort;
  page: number;
}

export const DEFAULT_CATALOG_FILTERS: CatalogFilters = {
  q: "",
  sub: null,
  chains: [],
  brand: "",
  privateLabel: false,
  dietary: [],
  onPromo: false,
  minPrice: null,
  maxPrice: null,
  near: false,
  sort: "relevance",
  page: 1,
};

const CANONICAL_SORTS: CanonicalSort[] = ["relevance", "popular", "unit_price", "price", "name"];

export type Route =
  | { name: "home" }
  | { name: "catalog"; section: string | null; view: CatalogView; filters: CatalogFilters }
  | { name: "canonical"; id: number }
  | { name: "product"; id: number }
  | { name: "list" }
  | { name: "basket" };

export const HOME_HASH = "#/";
export const CATALOG_HASH = "#/catalogo";
export const LIST_HASH = "#/lista";
export const BASKET_HASH = "#/cesta";

/** Only the filters that differ from the defaults are written, so plain URLs stay clean. */
export function catalogHash(
  section: string | null,
  view: CatalogView = "product",
  filters: Partial<CatalogFilters> = {},
): string {
  const base = section === null ? CATALOG_HASH : `${CATALOG_HASH}/${encodeURIComponent(section)}`;
  const f = { ...DEFAULT_CATALOG_FILTERS, ...filters };
  const params = new URLSearchParams();
  if (view === "super") params.set("vista", "super");
  if (f.q.trim() !== "") params.set("q", f.q.trim());
  if (f.sub) params.set("sub", f.sub);
  if (f.chains.length > 0) params.set("cadena", f.chains.join(","));
  if (f.brand.trim() !== "") params.set("marca", f.brand.trim());
  if (f.privateLabel) params.set("blanca", "1");
  if (f.dietary.length > 0) params.set("dieta", f.dietary.join(","));
  if (f.onPromo) params.set("oferta", "1");
  if (f.minPrice !== null) params.set("min", String(f.minPrice));
  if (f.maxPrice !== null) params.set("max", String(f.maxPrice));
  if (f.near) params.set("cerca", "1");
  if (f.sort !== DEFAULT_CATALOG_FILTERS.sort) params.set("orden", f.sort);
  if (f.page > 1) params.set("pag", String(f.page));
  const query = params.toString();
  return query === "" ? base : `${base}?${query}`;
}

export function canonicalHash(id: number): string {
  return `#/generico/${id}`;
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

function list(value: string | null): string[] {
  return (value ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

function price(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseFilters(params: URLSearchParams): CatalogFilters {
  const sort = params.get("orden") as CanonicalSort | null;
  const page = Number(params.get("pag"));
  return {
    q: params.get("q")?.trim() ?? "",
    sub: params.get("sub") || null,
    chains: list(params.get("cadena")),
    brand: params.get("marca")?.trim() ?? "",
    privateLabel: params.get("blanca") === "1",
    dietary: list(params.get("dieta")),
    onPromo: params.get("oferta") === "1",
    minPrice: price(params.get("min")),
    maxPrice: price(params.get("max")),
    near: params.get("cerca") === "1",
    sort: sort !== null && CANONICAL_SORTS.includes(sort) ? sort : DEFAULT_CATALOG_FILTERS.sort,
    page: Number.isInteger(page) && page > 1 ? page : 1,
  };
}

/** Unknown hashes fall back to the home page. */
export function parseRoute(hash: string): Route {
  const path = hash.startsWith("#") ? hash.slice(1) : hash;
  const [rawPath, query = ""] = path.split("?");
  const clean = rawPath.replace(/\/+$/, "");
  const parts = clean.split("/").filter((part) => part !== "").map(decode);

  if (parts.length === 0) return { name: "home" };
  if (parts[0] === "catalogo" && parts.length <= 2) {
    const params = new URLSearchParams(query);
    const view: CatalogView = params.get("vista") === "super" ? "super" : "product";
    return { name: "catalog", section: parts[1] ?? null, view, filters: parseFilters(params) };
  }
  if (parts[0] === "generico" && parts.length === 2 && /^\d+$/.test(parts[1])) {
    return { name: "canonical", id: Number(parts[1]) };
  }
  if (parts[0] === "producto" && parts.length === 2 && /^\d+$/.test(parts[1])) {
    return { name: "product", id: Number(parts[1]) };
  }
  if (parts[0] === "lista" && parts.length === 1) return { name: "list" };
  if (parts[0] === "cesta" && parts.length === 1) return { name: "basket" };
  return { name: "home" };
}

export function navigate(hash: string): void {
  window.location.hash = hash;
}

/** Updates the hash without adding a history entry (filters changing while typing). */
export function replaceHash(hash: string): void {
  const url = `${window.location.pathname}${window.location.search}${hash}`;
  window.history.replaceState(window.history.state, "", url);
  // `replaceState` fires no `hashchange`, so tell the router subscribers by hand.
  window.dispatchEvent(new HashChangeEvent("hashchange"));
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
