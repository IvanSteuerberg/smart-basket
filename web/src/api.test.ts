import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  geocode,
  interpretText,
  requestRecommendation,
  searchProducts,
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
