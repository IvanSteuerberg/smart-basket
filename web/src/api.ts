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
  /** Only concrete products are bought here (shades): a list line for it needs a product. */
  exact_only: boolean;
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
  /** Only concrete products are bought in this category (shades): the user picks a product. */
  exact_only: boolean;
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
  /** Only concrete products are bought here (shades): choosing it still needs a product. */
  exact_only: boolean;
}

export interface InterpretResponse {
  items: InterpretedItem[];
  llm_used: boolean;
  degraded: boolean;
}

/** Base unit the price per unit is expressed in, as the catalog returns it. */
export type BaseUnit = "kg" | "l" | "ud";
export type ProductSort = "unit_price" | "price" | "name";
export type CanonicalSort = "relevance" | "popular" | "unit_price" | "price" | "name";

/** The catalog product a product is an option of. */
export interface CanonicalProduct {
  id: number;
  name: string;
  category_key: string;
  category_name: string;
  /** Products with shades: never swapped for another one of the canonical product. */
  exact_only: boolean;
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
  /** Null when the supermarket gives no size to compute it from. */
  unit_price: Decimal | null;
  base_unit: BaseUnit | null;
  base_quantity: Decimal | null;
  canonical: CanonicalProduct | null;
  /** Dietary claims the supermarket makes in the product name (e.g. "sin_gluten"). */
  dietary_tags?: string[];
  on_promo?: boolean;
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

/** Filters shared by the product and canonical listings. */
export interface CatalogFilterQuery {
  chains?: string[];
  brand?: string | null;
  private_label?: boolean | null;
  dietary?: string[];
  on_promo?: boolean | null;
  min_price?: number | null;
  max_price?: number | null;
  near_lat?: number | null;
  near_lon?: number | null;
  mode?: TravelMode | null;
}

export interface ProductsQuery extends CatalogFilterQuery {
  section?: string | null;
  category?: string | null;
  q?: string | null;
  sort?: ProductSort | CanonicalSort;
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
  /** Products with shades: never compared as generic, only a concrete product is bought. */
  exact_only: boolean;
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

export interface CanonicalsQuery extends CatalogFilterQuery {
  section?: string | null;
  category?: string | null;
  q?: string | null;
  chain?: string | null;
  sort?: ProductSort | CanonicalSort;
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
  /** The product has shades: it is never swapped, so the line offers no "Cambiar". */
  exact_only: boolean;
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

export interface AgentObservation {
  kind: string;
  summary: string;
  line_index?: number | null;
  details?: Record<string, unknown>;
}

export interface AgentCandidate {
  key: string;
  kind: string;
  label: string;
  args?: Record<string, unknown>;
}

export interface AgentStepResult {
  summary?: string | null;
  overridden?: boolean;
}

export interface AgentStep {
  step_number: number;
  observation: AgentObservation | null;
  candidates: AgentCandidate[];
  chosen_action: string;
  action_args: Record<string, unknown>;
  confidence: number | null;
  probabilities: Record<string, number> | null;
  retries: number;
  used_default: boolean;
  result: AgentStepResult;
  latency_ms: number;
  error: string | null;
}

export interface AgentPendingOption {
  label: string;
  canonical_id?: number;
  [k: string]: unknown;
}

export interface AgentPendingQuestion {
  line_index?: number | null;
  prompt: string;
  options?: AgentPendingOption[];
}

export type AgentRunStatus =
  | "running"
  | "waiting_shopper"
  | "completed"
  | "failed"
  | "timed_out";

export interface AgentRunResponse {
  run_id: string;
  recommendation_id: string | null;
  status: AgentRunStatus;
  policy_name: string;
  model_name: string | null;
  steps_count: number;
  total_latency_ms: number;
  buyer_summary: string | null;
  pending_question: AgentPendingQuestion | null;
  alternatives_shown: Array<Record<string, unknown>>;
  mode: string;
  excluded_chains: string[];
  recommendation: Recommendation | null;
  steps: AgentStep[];
}

export interface HabitInput {
  term: string;
  canonical_id?: number | null;
  canonical_name: string;
  count: number;
  total: number;
}

export interface AgentRunRequest {
  request: RecommendationRequest;
  recommendation_id?: string | null;
  shopper_message?: string | null;
  habits?: Record<string, HabitInput>;
  dietary_rules?: string[];
  policy?: string | null;
  /** The earlier run this one refines, so the agent keeps its context. */
  previous_run_id?: string | null;
}

/** A supermarket chain with active prices, for the catalog chain filter. */
export interface ActiveChain {
  code: string;
  name: string;
  store_count: number;
  product_count: number;
  last_price_at: string | null;
}

export interface ChainsResponse {
  chains: ActiveChain[];
}

export interface AgentAnswerRequest {
  option_index?: number | null;
  choice_label?: string | null;
  canonical_id?: number | null;
  message?: string | null;
}

/**
 * `detail` of a 422 when a generic line needs the user to choose first: `VAGUE_LINE` when the
 * category is too vague to buy, `EXACT_ONLY` when only a concrete product can be bought (shades).
 */
export interface ChoiceRequiredDetail {
  code: "VAGUE_LINE" | "EXACT_ONLY";
  line_id: number;
  category_key: string;
  message: string;
}

/** Error raised when the API answers with a non-2xx status and a `detail` message. */
export class ApiError extends Error {
  readonly status: number;
  /** The raw `detail` of the response body, when it had one (e.g. a ChoiceRequiredDetail). */
  readonly detail: unknown;

  constructor(message: string, status: number, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isChoiceRequired(
  error: unknown,
): error is ApiError & { detail: ChoiceRequiredDetail } {
  if (!(error instanceof ApiError) || error.detail === null || typeof error.detail !== "object") {
    return false;
  }
  const code = (error.detail as { code?: unknown }).code;
  return code === "VAGUE_LINE" || code === "EXACT_ONLY";
}

const NETWORK_ERROR_MESSAGE = "No hemos podido conectar con el servidor. Inténtalo en unos segundos.";

/** Spanish text for an HTTP status the backend answered without a readable `detail`. */
function describeStatus(status: number): string | null {
  switch (status) {
    case 404:
      return "No hemos encontrado lo que buscas.";
    case 429:
      return "Demasiadas peticiones seguidas. Espera unos segundos e inténtalo de nuevo.";
    case 500:
      return "Algo ha fallado en el servidor. Inténtalo de nuevo en unos minutos.";
    case 502:
    case 503:
    case 504:
      return "El servicio no responde en este momento. Inténtalo de nuevo.";
    default:
      return null;
  }
}

const GENERIC_HTTP_ERROR_MESSAGE = "No hemos podido completar la petición. Inténtalo de nuevo.";

/** A message safe to show: never a raw «HTTP 502» or «Failed to fetch». */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const detailMessage = messageOf(error.detail);
    if (detailMessage !== null) return detailMessage;
    return describeStatus(error.status) ?? GENERIC_HTTP_ERROR_MESSAGE;
  }
  if (error instanceof TypeError) return NETWORK_ERROR_MESSAGE;
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

/** Serializes the filters shared by the product and canonical listings. */
function setFilterParams(params: URLSearchParams, query: CatalogFilterQuery): void {
  if (query.chains && query.chains.length > 0) params.set("chains", query.chains.join(","));
  if (query.brand) params.set("brand", query.brand);
  if (query.private_label !== undefined && query.private_label !== null) {
    params.set("private_label", String(query.private_label));
  }
  if (query.dietary && query.dietary.length > 0) params.set("dietary", query.dietary.join(","));
  if (query.on_promo !== undefined && query.on_promo !== null) {
    params.set("on_promo", String(query.on_promo));
  }
  if (query.min_price !== undefined && query.min_price !== null) {
    params.set("min_price", String(query.min_price));
  }
  if (query.max_price !== undefined && query.max_price !== null) {
    params.set("max_price", String(query.max_price));
  }
  if (query.near_lat !== undefined && query.near_lat !== null) {
    params.set("near_lat", String(query.near_lat));
  }
  if (query.near_lon !== undefined && query.near_lon !== null) {
    params.set("near_lon", String(query.near_lon));
  }
  if (query.mode) params.set("mode", query.mode);
}

export function getChains(signal?: AbortSignal): Promise<ChainsResponse> {
  return request<ChainsResponse>("/api/chains", { signal });
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
  setFilterParams(params, query);
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
  if (query.sort) params.set("sort", query.sort);
  setFilterParams(params, query);
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

export function startAgentRun(
  body: AgentRunRequest,
  signal?: AbortSignal,
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>("/api/agent/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export function answerAgentRun(
  runId: string,
  body: AgentAnswerRequest,
  signal?: AbortSignal,
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>(`/api/agent/runs/${encodeURIComponent(runId)}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export function sendAgentMessage(
  runId: string,
  message: string,
  signal?: AbortSignal,
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>(`/api/agent/runs/${encodeURIComponent(runId)}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });
}

export function getAgentRun(runId: string, signal?: AbortSignal): Promise<AgentRunResponse> {
  return request<AgentRunResponse>(`/api/agent/runs/${encodeURIComponent(runId)}`, { signal });
}
