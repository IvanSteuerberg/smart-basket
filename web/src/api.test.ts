import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  answerAgentRun,
  ApiError,
  describeError,
  getCanonicals,
  getChains,
  getProducts,
  sendAgentMessage,
  geocode,
  getAgentRun,
  interpretText,
  isChoiceRequired,
  requestRecommendation,
  searchProducts,
  startAgentRun,
  type AgentRunRequest,
  type AgentRunResponse,
  type RecommendationRequest,
} from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("isChoiceRequired", () => {
  it("recognizes the 422 of a generic line that needs a choice, vague or with shades", async () => {
    const detail = {
      code: "EXACT_ONLY",
      line_id: 1,
      category_key: "tinte",
      message: "Elige el producto concreto.",
    };
    fetchMock.mockResolvedValue(jsonResponse({ detail }, 422));

    const error = await requestRecommendation({} as RecommendationRequest).catch(
      (cause: unknown) => cause,
    );

    expect(isChoiceRequired(error)).toBe(true);
    expect(isChoiceRequired(new ApiError("otro", 422, { code: "VAGUE_LINE" }))).toBe(true);
    expect(isChoiceRequired(new ApiError("otro", 422, { code: "OTHER" }))).toBe(false);
    expect(isChoiceRequired(new Error("boom"))).toBe(false);
  });
});

describe("searchProducts", () => {
  it("encodes the query and returns the results", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ results: [{ key: "leaf:pan", name: "Pan", kind: "leaf", path: "Panadería" }] }),
    );

    const results = await searchProducts("pan de molde");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search?q=pan%20de%20molde",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
    expect(results).toHaveLength(1);
    expect(results[0].key).toBe("leaf:pan");
  });
});

describe("interpretText", () => {
  it("posts the text as JSON", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], llm_used: true, degraded: false }),
    );

    await interpretText("2 l de leche");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(fetchMock.mock.calls[0][0]).toBe("/api/interpret");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ text: "2 l de leche" }));
  });
});

describe("API errors", () => {
  it("shows the Spanish detail of a 422 answer", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "La lista está vacía." }, 422));

    const request: RecommendationRequest = {
      items: [],
      origin: { lat: 42.5987, lon: -5.5671 },
      mode: "walk",
      max_stores: 2,
      priority_mode: "balanced",
      return_to_origin: true,
      degraded: false,
    };

    await expect(requestRecommendation(request)).rejects.toMatchObject({
      name: "ApiError",
      message: "La lista está vacía.",
      status: 422,
    });
  });

  it("shows the detail of a 503 answer from the geocoder", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Geocodificador no disponible" }, 503));

    const error = await geocode("Calle Ancha").catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Geocodificador no disponible");
    expect((error as ApiError).status).toBe(503);
  });

  it("falls back to the status code when the body has no detail", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 500 }));

    await expect(searchProducts("pan")).rejects.toThrow("HTTP 500");
  });
});

function sampleAgentRunResponse(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    run_id: "01948a00-0000-7000-8000-000000000001",
    recommendation_id: "rec-1",
    status: "completed",
    policy_name: "gemini_decisions",
    model_name: "gemini-decision-1",
    steps_count: 1,
    total_latency_ms: 142,
    buyer_summary: "He elegido plátanos como sueles comprar.",
    pending_question: null,
    alternatives_shown: [],
    mode: "walk",
    excluded_chains: [],
    recommendation: null,
    steps: [
      {
        step_number: 1,
        observation: {
          kind: "vague_line",
          summary: "«fruta» es demasiado amplio.",
          line_index: 0,
        },
        candidates: [
          { key: "aplicar_habitual:0", kind: "aplicar_habitual", label: "Usar Plátanos" },
          { key: "preguntar:0", kind: "preguntar", label: "Preguntar al comprador" },
        ],
        chosen_action: "aplicar_habitual:0",
        action_args: { line_index: 0 },
        confidence: 0.91,
        probabilities: { "aplicar_habitual:0": 0.91, "preguntar:0": 0.09 },
        retries: 0,
        used_default: false,
        result: { summary: "Sustituido por Plátanos." },
        latency_ms: 142,
        error: null,
      },
    ],
    ...overrides,
  };
}

describe("agent API client", () => {
  it("starts an agent run via POST /api/agent/runs", async () => {
    const payload = sampleAgentRunResponse();
    fetchMock.mockResolvedValue(jsonResponse(payload));

    const requestBody: AgentRunRequest = {
      request: {
        items: [],
        origin: { lat: 42.5987, lon: -5.5671 },
        mode: "walk",
        max_stores: 2,
        priority_mode: "balanced",
        return_to_origin: true,
        degraded: false,
      },
      recommendation_id: "rec-1",
      habits: {
        fruta: {
          term: "fruta",
          canonical_id: 12,
          canonical_name: "Plátanos",
          count: 4,
          total: 5,
        },
      },
      policy: "default",
    };

    const result = await startAgentRun(requestBody);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify(requestBody));
    expect(result).toEqual(payload);
  });

  it("answers a paused agent run via POST /api/agent/runs/:id/answer", async () => {
    const payload = sampleAgentRunResponse({ status: "completed", pending_question: null });
    fetchMock.mockResolvedValue(jsonResponse(payload));

    const result = await answerAgentRun("run/1", {
      option_index: 0,
      choice_label: "Plátanos",
      canonical_id: 12,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run%2F1/answer");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({ option_index: 0, choice_label: "Plátanos", canonical_id: 12 }),
    );
    expect(result).toEqual(payload);
  });

  it("answers the pending question with the chosen option and its canonical id", async () => {
    const payload = sampleAgentRunResponse({ status: "completed", pending_question: null });
    fetchMock.mockResolvedValue(jsonResponse(payload));

    await answerAgentRun("run-1", {
      option_index: 1,
      choice_label: "Leche entera",
      canonical_id: null,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run-1/answer");
    expect(init.body).toBe(
      JSON.stringify({ option_index: 1, choice_label: "Leche entera", canonical_id: null }),
    );
  });

  it("answers a pending question that offers no options with free text", async () => {
    fetchMock.mockResolvedValue(jsonResponse(sampleAgentRunResponse()));

    await answerAgentRun("run-2", { message: "Prefiero plátanos" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run-2/answer");
    expect(init.body).toBe(JSON.stringify({ message: "Prefiero plátanos" }));
  });

  it("requests a change with a free-text shopper message", async () => {
    fetchMock.mockResolvedValue(jsonResponse(sampleAgentRunResponse()));

    const requestBody: AgentRunRequest = {
      request: {
        items: [],
        origin: { lat: 42.5987, lon: -5.5671 },
        mode: "walk",
        max_stores: 2,
        priority_mode: "balanced",
        return_to_origin: true,
        degraded: false,
      },
      recommendation_id: "rec-1",
      shopper_message: "¿y si voy en coche?",
    };

    await startAgentRun(requestBody);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify(requestBody));
    const sent = JSON.parse(init.body as string) as AgentRunRequest;
    expect(sent.shopper_message).toBe("¿y si voy en coche?");
  });

  it("fetches an existing agent run via GET /api/agent/runs/:id", async () => {
    const payload = sampleAgentRunResponse();
    fetchMock.mockResolvedValue(jsonResponse(payload));

    const result = await getAgentRun("run-42");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run-42");
    expect(init.method).toBeUndefined();
    expect(result).toEqual(payload);
  });

  it("propagates ApiError when an agent endpoint returns an error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Ejecución no encontrada" }, 404));

    await expect(getAgentRun("missing-run")).rejects.toMatchObject({
      name: "ApiError",
      message: "Ejecución no encontrada",
      status: 404,
    });
  });
});

describe("describeError", () => {
  it("translates network failures", () => {
    expect(describeError(new TypeError("Failed to fetch"))).toBe(
      "No hemos podido conectar con el servidor. Inténtalo en unos segundos.",
    );
  });

  it("translates bare HTTP statuses without exposing them", () => {
    for (const status of [400, 401, 403, 404, 429, 500, 502, 503, 504]) {
      const message = describeError(new ApiError(`HTTP ${status}`, status));
      expect(message).not.toContain("HTTP");
      expect(message.length).toBeGreaterThan(10);
    }
    expect(describeError(new ApiError("HTTP 502", 502))).toBe(
      "El servicio no responde en este momento. Inténtalo de nuevo.",
    );
  });

  it("prefers the backend detail over a generic HTTP status message", () => {
    expect(describeError(new ApiError("HTTP 422", 422, "Lista vacía"))).toBe("Lista vacía");
  });
});

describe("catalog filters and new endpoints", () => {
  it("serializes the filters in getProducts and getCanonicals", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ items: [], total: 0, page: 1, size: 24 })),
    );
    const filters = {
      chains: ["mercadona", "lidl"],
      brand: "Hacendado",
      private_label: true,
      dietary: ["sin_gluten"],
      on_promo: true,
      min_price: 1,
      max_price: 5.5,
      near_lat: 42.6,
      near_lon: -5.57,
      mode: "walk" as const,
      sort: "popular" as const,
    };
    await getProducts(filters);
    await getCanonicals(filters);
    for (const [url] of fetchMock.mock.calls as [string][]) {
      const params = new URL(url, "http://x").searchParams;
      expect(params.get("chains")).toBe("mercadona,lidl");
      expect(params.get("brand")).toBe("Hacendado");
      expect(params.get("private_label")).toBe("true");
      expect(params.get("dietary")).toBe("sin_gluten");
      expect(params.get("on_promo")).toBe("true");
      expect(params.get("min_price")).toBe("1");
      expect(params.get("max_price")).toBe("5.5");
      expect(params.get("near_lat")).toBe("42.6");
      expect(params.get("near_lon")).toBe("-5.57");
      expect(params.get("mode")).toBe("walk");
      expect(params.get("sort")).toBe("popular");
    }
  });

  it("calls GET /api/chains", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ chains: [] }));
    await getChains();
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/chains");
  });

  it("posts a shopper message to a run", async () => {
    fetchMock.mockResolvedValue(jsonResponse(sampleAgentRunResponse()));
    await sendAgentMessage("run/1", "en coche");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run%2F1/message");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ message: "en coche" }));
  });

  it("sends the origin with a follow-up message so the run can re-optimize", async () => {
    fetchMock.mockResolvedValue(jsonResponse(sampleAgentRunResponse()));
    await sendAgentMessage("run/1", "en coche", { lat: 42.5987, lon: -5.5671 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/runs/run%2F1/message");
    expect(init.body).toBe(
      JSON.stringify({ message: "en coche", origin: { lat: 42.5987, lon: -5.5671 } }),
    );
  });

  it("omits the origin entirely when there is none to send", async () => {
    fetchMock.mockResolvedValue(jsonResponse(sampleAgentRunResponse()));
    await sendAgentMessage("run/1", "en coche", null);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe(JSON.stringify({ message: "en coche" }));
  });
});
