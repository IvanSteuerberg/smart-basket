// Thin client of the HTTP API, the only contract with the backend (decision 0008).

export type Unit = "ud" | "kg" | "g" | "l" | "ml";
export type SearchKind = "leaf" | "group";
export type TravelMode = "walk" | "car";
export type PriorityMode = "savings" | "balanced" | "time";
export type MissingReason = "not_available" | "separate_stop" | "unreachable";

/** Decimal amounts may travel as JSON strings or numbers. */
export type Decimal = string | number;

export interface Health {
  status: "ok" | "degraded";
  version: string;
  engine_version: string;
  database: "ok" | "unavailable";
}

export interface LeafCategory {
  key: string;
  name: string;
  base_unit: string;
  products: number;
}

export interface GroupCategory {
  key: string;
  name: string;
  vague: boolean;
  products: number;
  children: LeafCategory[];
}

export interface SectionCategory {
  key: string;
  name: string;
  children: GroupCategory[];
}

export interface CategoriesResponse {
  sections: SectionCategory[];
}

export interface SearchResult {
  key: string;
  name: string;
  kind: SearchKind;
  path: string;
}

export interface SearchResponse {
  results: SearchResult[];
}

export interface InterpretedItem {
  line: number;
  text: string;
  item: string | null;
  quantity: string;
  unit: Unit;
  category_key: string | null;
  category_name: string | null;
  brand: string | null;
  alternatives: unknown[];
  resolved: boolean;
  needs_llm: boolean;
}

export interface InterpretResponse {
  items: InterpretedItem[];
  llm_used: boolean;
  degraded: boolean;
}

export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
}

export interface GeocodeResponse {
  results: GeocodeResult[];
}

export interface LatLon {
  lat: number;
  lon: number;
}

export interface RecommendationItemRequest {
  text: string;
  category_key: string | null;
  quantity: string;
  unit: Unit;
  brand: string | null;
  private_label_ok: boolean;
}

export interface RecommendationRequest {
  items: RecommendationItemRequest[];
  origin: LatLon;
  mode: TravelMode;
  max_stores: number;
  priority_mode: PriorityMode;
  return_to_origin: boolean;
  degraded: boolean;
}

export interface BasketLine {
  text: string;
  product_name: string;
  packs: number;
  quantity_bought: Decimal;
  cost: Decimal;
}

export interface BasketStore {
  store_id: string | number;
  name: string;
  chain: string;
  address: string | null;
  lat: number;
  lon: number;
  position: number;
  lines: BasketLine[];
  subtotal: Decimal;
}

export interface MissingStop {
  store_id: string | number;
  name: string;
  cost: Decimal;
  extra_minutes: Decimal;
  exceeds_max_stores: boolean;
}

export interface MissingItem {
  text: string;
  reason: MissingReason;
  stop: MissingStop | null;
}

export interface Recommendation {
  id: string | number;
  /** Null when there was nothing to buy; there is no price date then. */
  data_as_of: string | null;
  engine_version: string;
  stores: BasketStore[];
  total_cost: Decimal;
  minutes: Decimal;
  missing: MissingItem[];
  route: [number, number][];
  explanation: string;
  degraded: boolean;
}

/** Error raised when the API answers with a non-2xx status and a `detail` message. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function describeError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail) return detail;
      if (Array.isArray(detail)) {
        const messages = detail.map((entry) => {
          if (entry !== null && typeof entry === "object" && "msg" in entry) {
            return String((entry as { msg: unknown }).msg);
          }
          return String(entry);
        });
        if (messages.length > 0) return messages.join(". ");
      }
    }
  } catch {
    // The body was not JSON; fall back to the status code.
  }
  return `HTTP ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    throw new ApiError(await detailOf(response), response.status);
  }
  return (await response.json()) as T;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal, headers: { Accept: "application/json" } });
  if (!response.ok && response.status !== 503) {
    throw new ApiError(await detailOf(response), response.status);
  }
  return (await response.json()) as Health;
}

export function getCategories(signal?: AbortSignal): Promise<CategoriesResponse> {
  return request<CategoriesResponse>("/api/categories", { signal });
}

export function searchProducts(query: string, signal?: AbortSignal): Promise<SearchResult[]> {
  const path = `/api/search?q=${encodeURIComponent(query)}`;
  return request<SearchResponse>(path, { signal }).then((body) => body.results);
}

export function interpretText(text: string, signal?: AbortSignal): Promise<InterpretResponse> {
  return request<InterpretResponse>("/api/interpret", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
}

export function geocode(query: string, signal?: AbortSignal): Promise<GeocodeResult[]> {
  const path = `/api/geocode?q=${encodeURIComponent(query)}`;
  return request<GeocodeResponse>(path, { signal }).then((body) => body.results);
}

export function requestRecommendation(
  body: RecommendationRequest,
  signal?: AbortSignal,
): Promise<Recommendation> {
  return request<Recommendation>("/api/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}
