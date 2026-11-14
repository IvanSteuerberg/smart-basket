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
  /** Photo of the cheapest product per unit of its category, if any. */
  image_url: string | null;
  /** Choices for a vague term ("pollo", "fruta"); empty when the line is not vague. */
  options: InterpretOption[];
}

/** One choice offered for a vague line, shown as a chip with a photo. */
export interface InterpretOption {
  category_key: string;
  name: string;
  image_url: string | null;
  from_unit_price: Decimal | null;
  base_unit: BaseUnit;
}

export interface InterpretResponse {
  items: InterpretedItem[];
  llm_used: boolean;
  degraded: boolean;
}

/** Base unit the price per unit is expressed in, as the catalog returns it. */
export type BaseUnit = "kg" | "l" | "ud";
export type ProductSort = "unit_price" | "price" | "name";

/** The catalog product a product is an option of. */
export interface CanonicalProduct {
  id: number;
  name: string;
  category_key: string;
  category_name: string;
}

export interface Product {
  id: number;
  name: string;
  brand: string | null;
  private_label: boolean;
  packaging: string | null;
  image_url: string | null;
  chain: string;
  price: Decimal;
  unit_price: Decimal;
  base_unit: BaseUnit;
  base_quantity: Decimal | null;
  canonical: CanonicalProduct | null;
}

export interface ProductDetail extends Product {
  /** Other products of the same canonical, cheapest per unit first. */
  alternatives: Product[];
}

/** A top-level section of the catalog, with a representative photo. */
export interface CatalogSection {
  key: string;
  name: string;
  products: number;
  image_url: string | null;
}

export interface SectionsResponse {
  sections: CatalogSection[];
}

export interface ProductsPage {
  items: Product[];
  total: number;
  page: number;
  size: number;
}

export interface ProductsQuery {
  section?: string | null;
  category?: string | null;
  q?: string | null;
  sort?: ProductSort;
  page?: number;
  size?: number;
}

/** A generic product (canonical) as a catalog card: no brand or size. */
export interface CanonicalCard {
  id: number;
  name: string;
  category_key: string;
  category_name: string;
  /** Photo of its cheapest product per unit. */
  image_url: string | null;
  from_price: Decimal;
  from_unit_price: Decimal;
  base_unit: BaseUnit;
  /** Number of concrete products of this canonical. */
  product_count: number;
  /** Chain codes that sell it, e.g. "mercadona". */
  chains: string[];
}

export interface CanonicalDetail extends CanonicalCard {
  /** Its concrete products, cheapest per unit first. */
  products: Product[];
}

export interface CanonicalsPage {
  items: CanonicalCard[];
  total: number;
  page: number;
  size: number;
}

export interface CanonicalsQuery {
  section?: string | null;
  category?: string | null;
  q?: string | null;
  chain?: string | null;
  page?: number;
  size?: number;
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

/** "exact": that product; "equivalent": any product of its canonical. */
export type Accept = "exact" | "equivalent";

/**
 * A list line. It carries either `category_key` (generic) or `product_id`
 * (concrete), never both. With `product_id`, `quantity` is the number of packs
 * and `unit` is "ud". A generic line only accepts "equivalent".
 */
export interface RecommendationItemRequest {
  text: string;
  category_key?: string | null;
  product_id?: number | null;
  accept?: Accept;
  /** Variant keys (e.g. "sin_lactosa"); when absent the server reads them from `text`. */
  variants?: string[] | null;
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
  /** Chain codes to shop in ("Comprar solo en..."); absent or empty means every chain. */
  chains?: string[] | null;
}

export interface BasketLine {
  /** Index of the line in the request `items`. */
  line_id: number;
  text: string;
  product_id: number;
  canonical_id: number | null;
  product_name: string;
  brand: string | null;
  image_url: string | null;
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
  line_id: number;
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
  /** What the basket would save with every "exact" line as "equivalent"; null when nothing. */
  flex_savings: FlexSavings | null;
}

export interface FlexSavings {
  total: Decimal;
  lines: { line_id: number; savings: Decimal }[];
}

/** `detail` of a 422 when a line is still vague and must be resolved first. */
export interface VagueLineDetail {
  code: "VAGUE_LINE";
  line_id: number;
  category_key: string;
  message: string;
}

/** Error raised when the API answers with a non-2xx status and a `detail` message. */
export class ApiError extends Error {
  readonly status: number;
  /** The raw `detail` of the response body, when it had one (e.g. a VagueLineDetail). */
  readonly detail: unknown;

  constructor(message: string, status: number, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isVagueLine(error: unknown): error is ApiError & { detail: VagueLineDetail } {
  if (!(error instanceof ApiError) || error.detail === null || typeof error.detail !== "object") {
    return false;
  }
  return (error.detail as { code?: unknown }).code === "VAGUE_LINE";
}

export function describeError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

async function errorOf(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === "object" && "detail" in body) {
      detail = (body as { detail: unknown }).detail;
    }
  } catch {
    // The body was not JSON; fall back to the status code.
  }
  return new ApiError(messageOf(detail) ?? `HTTP ${response.status}`, response.status, detail);
}

function messageOf(detail: unknown): string | null {
  if (typeof detail === "string" && detail) return detail;
  if (detail !== null && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => {
      if (entry !== null && typeof entry === "object" && "msg" in entry) {
        return String((entry as { msg: unknown }).msg);
      }
      return String(entry);
    });
    if (messages.length > 0) return messages.join(". ");
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    throw await errorOf(response);
  }
  return (await response.json()) as T;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal, headers: { Accept: "application/json" } });
  if (!response.ok && response.status !== 503) {
    throw await errorOf(response);
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

export function getSections(signal?: AbortSignal): Promise<SectionsResponse> {
  return request<SectionsResponse>("/api/sections", { signal });
}

export function getProducts(
  query: ProductsQuery = {},
  signal?: AbortSignal,
): Promise<ProductsPage> {
  const params = new URLSearchParams();
  if (query.section) params.set("section", query.section);
  if (query.category) params.set("category", query.category);
  if (query.q) params.set("q", query.q);
  if (query.sort) params.set("sort", query.sort);
  if (query.page !== undefined) params.set("page", String(query.page));
  if (query.size !== undefined) params.set("size", String(query.size));
  const search = params.toString();
  return request<ProductsPage>(`/api/products${search === "" ? "" : `?${search}`}`, { signal });
}

export function getProduct(id: number, signal?: AbortSignal): Promise<ProductDetail> {
  return request<ProductDetail>(`/api/products/${id}`, { signal });
}

export function getCanonicals(
  query: CanonicalsQuery = {},
  signal?: AbortSignal,
): Promise<CanonicalsPage> {
  const params = new URLSearchParams();
  if (query.section) params.set("section", query.section);
  if (query.category) params.set("category", query.category);
  if (query.q) params.set("q", query.q);
  if (query.chain) params.set("chain", query.chain);
  if (query.page !== undefined) params.set("page", String(query.page));
  if (query.size !== undefined) params.set("size", String(query.size));
  const search = params.toString();
  return request<CanonicalsPage>(`/api/canonicals${search === "" ? "" : `?${search}`}`, {
    signal,
  });
}

export function getCanonical(id: number, signal?: AbortSignal): Promise<CanonicalDetail> {
  return request<CanonicalDetail>(`/api/canonicals/${id}`, { signal });
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
