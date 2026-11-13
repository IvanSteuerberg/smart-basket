import { type Page, expect, test } from "@playwright/test";
import type {
  CategoriesResponse,
  GeocodeResponse,
  Health,
  InterpretResponse,
  Recommendation,
  SearchResponse,
} from "../src/api";

const TRANSPARENT_1X1_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

const mockHealth: Health = {
  status: "ok",
  version: "0.1.0",
  engine_version: "0.1.0",
  database: "ok",
};

const mockCategories: CategoriesResponse = {
  sections: [
    {
      key: "lacteos",
      name: "Lácteos",
      children: [
        {
          key: "leche",
          name: "Leche",
          vague: false,
          products: 2,
          children: [
            {
              key: "leche-entera",
              name: "Leche entera",
              base_unit: "l",
              products: 1,
            },
          ],
        },
      ],
    },
  ],
};

const mockSearch: SearchResponse = {
  results: [
    {
      key: "leche-entera",
      name: "Leche entera",
      kind: "leaf",
      path: "Lácteos > Leche > Leche entera",
    },
  ],
};

const mockGeocode: GeocodeResponse = {
  results: [
    {
      label: "Plaza Mayor, 24003 León",
      lat: 42.5987,
      lon: -5.5671,
    },
  ],
};

const mockInterpret: InterpretResponse = {
  items: [
    {
      line: 1,
      text: "2 l de leche",
      item: "leche",
      quantity: "2",
      unit: "l",
      category_key: "leche-entera",
      category_name: "Leche entera",
      brand: null,
      alternatives: [],
      resolved: true,
      needs_llm: false,
    },
    {
      line: 2,
      text: "pan de molde",
      item: "pan de molde",
      quantity: "1",
      unit: "ud",
      category_key: "pan-molde",
      category_name: "Pan de molde",
      brand: null,
      alternatives: [],
      resolved: true,
      needs_llm: false,
    },
    {
      line: 3,
      text: "colacao",
      item: "colacao",
      quantity: "1",
      unit: "ud",
      category_key: "cacao-soluble",
      category_name: "Cacao soluble",
      brand: "ColaCao",
      alternatives: [],
      resolved: true,
      needs_llm: false,
    },
  ],
  llm_used: false,
  degraded: false,
};

const mockRecommendation: Recommendation = {
  id: "rec-1",
  data_as_of: "2026-11-13T12:00:00Z",
  engine_version: "0.1.0",
  stores: [
    {
      store_id: "store-1",
      name: "Mercadona Palomera",
      chain: "Mercadona",
      lat: 42.6001,
      lon: -5.565,
      position: 1,
      lines: [
        {
          text: "2 l de leche",
          product_name: "Leche entera Pascual 1L",
          packs: 2,
          quantity_bought: "2",
          cost: "1.90",
        },
        {
          text: "pan de molde",
          product_name: "Pan de molde con corteza Hacendado",
          packs: 1,
          quantity_bought: "1",
          cost: "1.25",
        },
        {
          text: "colacao",
          product_name: "Cacao soluble ColaCao Original 760g",
          packs: 1,
          quantity_bought: "1",
          cost: "2.30",
        },
      ],
      subtotal: "5.45",
    },
  ],
  total_cost: "5.45",
  minutes: 8,
  missing: [],
  route: [
    [42.5987, -5.5671],
    [42.6001, -5.565],
  ],
  explanation: "Tu cesta en Mercadona ahorra 2,30 € respecto a la segunda opción.",
  degraded: false,
};

const LIST = "2 l de leche\npan de molde\ncolacao";
const ROUTE_ERROR = "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos.";

async function mockJson(page: Page, url: string, body: unknown, status = 200): Promise<void> {
  await page.route(url, (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }),
  );
}

test.beforeEach(async ({ page }) => {
  // Routes registered later take precedence. First block everything that is not the
  // dev server, and any /api call without a fixture, so nothing reaches the network.
  await page.route(
    (url) => url.hostname !== "localhost",
    (route) => route.abort(),
  );
  await page.route("**/api/**", (route) => route.abort());
  // Map tiles: a transparent 1x1 PNG.
  await page.route(/tile\.openstreetmap\.org/, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TRANSPARENT_1X1_PNG }),
  );
  await mockJson(page, "**/api/health", mockHealth);
  await mockJson(page, "**/api/categories", mockCategories);
  await mockJson(page, "**/api/search*", mockSearch);
  await mockJson(page, "**/api/geocode*", mockGeocode);
  await mockJson(page, "**/api/interpret", mockInterpret);
});

/** Writes the list, interprets it, continues the review and picks the origin on the map. */
async function goToOriginStep(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Tu lista de la compra" }).fill(LIST);
  const interpreted = page.waitForRequest("**/api/interpret");
  await page.getByRole("button", { name: "Interpretar" }).click();
  expect((await interpreted).postDataJSON()).toEqual({ text: LIST });

  const continueButton = page.getByRole("button", { name: "Continuar" });
  await expect(continueButton).toBeEnabled();
  await continueButton.click();

  const calculate = page.getByRole("button", { name: "Calcular cesta" });
  await expect(calculate).toBeDisabled();
  // The map has no accessible role: click its container to pick the origin.
  await page.locator(".map").click();
  await expect(calculate).toBeEnabled();

  const car = page.getByRole("radio", { name: "En coche" });
  await car.check();
  await expect(car).toBeChecked();
}

test("full recommendation flow through list, review, origin and basket", async ({ page }) => {
  await mockJson(page, "**/api/recommendations", mockRecommendation);
  await goToOriginStep(page);

  const sent = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular cesta" }).click();
  const body = (await sent).postDataJSON();
  expect(body.mode).toBe("car");
  expect(body.items).toHaveLength(3);
  // The origin is the clicked point, around León.
  expect(body.origin.lat).toBeGreaterThan(42.5);
  expect(body.origin.lat).toBeLessThan(42.7);
  expect(body.origin.lon).toBeGreaterThan(-5.7);
  expect(body.origin.lon).toBeLessThan(-5.4);

  await expect(page.getByText(mockRecommendation.explanation)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "1. Mercadona – Mercadona Palomera" }),
  ).toBeVisible();
  await expect(page.getByText("Leche entera Pascual 1L")).toBeVisible();
  await expect(page.getByText("Pan de molde con corteza Hacendado")).toBeVisible();
  await expect(page.getByText("Cacao soluble ColaCao Original 760g")).toBeVisible();
  await expect(page.getByText(/Total:\s*5,45\s*€/)).toBeVisible();

  // Map: the origin marker plus one numbered marker per store, and the route line.
  await expect(page.locator(".map .leaflet-marker-icon")).toHaveCount(
    1 + mockRecommendation.stores.length,
  );
  await expect(page.locator(".map path.leaflet-interactive")).toHaveCount(1);
});

test("recommendations 503 displays the error inline", async ({ page }) => {
  await mockJson(page, "**/api/recommendations", { detail: ROUTE_ERROR }, 503);
  await goToOriginStep(page);
  await page.getByRole("button", { name: "Calcular cesta" }).click();

  await expect(page.getByRole("alert").filter({ hasText: ROUTE_ERROR })).toBeVisible();
  // The flow stays on the origin step.
  await expect(page.getByRole("button", { name: "Calcular cesta" })).toBeVisible();
});
