import { expect, test } from "@playwright/test";
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

test.beforeEach(async ({ page }) => {
  // Prevent any request to the outside internet; answer tiles with 1x1 transparent PNG.
  await page.route(/tile\.openstreetmap\.org/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: TRANSPARENT_1X1_PNG,
    });
  });

  // Mock every /api/* route with synthetic fixtures.
  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockHealth),
    });
  });

  await page.route("**/api/categories", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockCategories),
    });
  });

  await page.route("**/api/search*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockSearch),
    });
  });

  await page.route("**/api/geocode*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockGeocode),
    });
  });

  await page.route("**/api/interpret", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockInterpret),
    });
  });
});

test("full recommendation flow through list, review, origin and basket", async ({ page }) => {
  await page.route("**/api/recommendations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockRecommendation),
    });
  });

  await page.goto("/");

  // 1. List step: write items and click "Interpretar".
  const listInput = page.getByRole("textbox", { name: "Tu lista de la compra" });
  await expect(listInput).toBeVisible();
  await listInput.fill("2 l de leche\npan de molde\ncolacao");

  const interpretButton = page.getByRole("button", { name: "Interpretar" });
  await expect(interpretButton).toBeEnabled();
  await interpretButton.click();

  // 2. Review step: continue with the interpreted items.
  const continueButton = page.getByRole("button", { name: "Continuar" });
  await expect(continueButton).toBeEnabled();
  await continueButton.click();

  // 3. Origin step: click map to set origin, choose "En coche" and calculate basket.
  const calculateButton = page.getByRole("button", { name: "Calcular cesta" });
  await expect(calculateButton).toBeDisabled();

  // The map has no accessible role; click container to pick an origin coordinate.
  await page.locator(".map").click();
  await expect(calculateButton).toBeEnabled();

  const carRadio = page.getByRole("radio", { name: "En coche" });
  await carRadio.check();
  await expect(carRadio).toBeChecked();

  await calculateButton.click();

  // 4. Basket step: assert explanation, store card with lines, total, and map route line.
  await expect(
    page.getByText("Tu cesta en Mercadona ahorra 2,30 € respecto a la segunda opción."),
  ).toBeVisible();

  await expect(
    page.getByRole("heading", { name: "1. Mercadona – Mercadona Palomera" }),
  ).toBeVisible();
  await expect(page.getByText("Leche entera Pascual 1L")).toBeVisible();
  await expect(page.getByText("Pan de molde con corteza Hacendado")).toBeVisible();
  await expect(page.getByText("Cacao soluble ColaCao Original 760g")).toBeVisible();

  await expect(page.getByText(/Total:\s*5,45\s*€/)).toBeVisible();

  // The polyline renders an SVG path inside the leaflet map pane.
  await expect(page.locator(".map path.leaflet-interactive")).toBeVisible();
});

test("recommendations 503 displays the error inline", async ({ page }) => {
  await page.route("**/api/recommendations", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos.",
      }),
    });
  });

  await page.goto("/");

  const listInput = page.getByRole("textbox", { name: "Tu lista de la compra" });
  await listInput.fill("2 l de leche\npan de molde\ncolacao");

  await page.getByRole("button", { name: "Interpretar" }).click();
  await page.getByRole("button", { name: "Continuar" }).click();

  await page.locator(".map").click();
  await page.getByRole("button", { name: "Calcular cesta" }).click();

  await expect(
    page.getByRole("alert"),
  ).toHaveText("No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos.");
});
