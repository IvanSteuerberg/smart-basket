import { type Page, type Request, expect, test } from "@playwright/test";
import type {
  CanonicalDetail,
  CategoriesResponse,
  GeocodeResponse,
  Health,
  InterpretResponse,
  Recommendation,
  SearchResponse,
} from "../src/api";
import { blockUnmocked, mockJson, TRANSPARENT_1X1_PNG } from "./mock";

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

const mockInterpretResolved: InterpretResponse = {
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
      image_url: null,
      options: [],
    },
  ],
  llm_used: false,
  degraded: false,
};

const mockInterpretWithVague: InterpretResponse = {
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
      image_url: null,
      options: [],
    },
    {
      line: 2,
      text: "pollo",
      item: "pollo",
      quantity: "1",
      unit: "kg",
      category_key: null,
      category_name: "Pollo",
      brand: null,
      alternatives: [],
      resolved: false,
      needs_llm: false,
      image_url: null,
      options: [
        {
          category_key: "pollo_pechuga",
          name: "Pechuga de pollo",
          image_url: null,
          from_unit_price: "2.50",
          base_unit: "kg",
        },
        {
          category_key: "pollo_muslos",
          name: "Muslos de pollo",
          image_url: null,
          from_unit_price: "1.99",
          base_unit: "kg",
        },
      ],
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
      address: "Av. de Portugal, 12",
      lat: 42.6001,
      lon: -5.565,
      position: 1,
      lines: [
        {
          line_id: 0,
          text: "2 l de leche",
          product_id: 101,
          canonical_id: 201,
          brand: "Pascual",
          image_url: null,
          product_name: "Leche entera Pascual 1L",
          packs: 2,
          quantity_bought: "2",
          cost: "1.90",
        },
      ],
      subtotal: "1.90",
    },
  ],
  total_cost: "1.90",
  minutes: "14.28",
  missing: [],
  route: [
    [42.5987, -5.5671],
    [42.6001, -5.565],
  ],
  explanation: "Tu cesta en Mercadona ahorra 2,30 € respecto a la segunda opción.",
  degraded: false,
  flex_savings: null,
};

const mockCanonicalDetail: CanonicalDetail = {
  id: 201,
  name: "Leche entera",
  category_key: "leche-entera",
  category_name: "Leche entera",
  image_url: null,
  from_price: "1.05",
  from_unit_price: "1.05",
  base_unit: "l",
  product_count: 2,
  chains: ["mercadona"],
  products: [
    {
      id: 101,
      name: "Leche entera Pascual 1L",
      brand: "Pascual",
      private_label: false,
      packaging: "Botella 1 L",
      image_url: null,
      chain: "Mercadona",
      price: "1.90",
      unit_price: "1.90",
      base_unit: "l",
      base_quantity: "1",
      canonical: { id: 201, name: "Leche entera", category_key: "leche-entera", category_name: "Leche entera" },
    },
    {
      id: 999,
      name: "Leche entera Hacendado 1L",
      brand: "Hacendado",
      private_label: true,
      packaging: "Brik 1 L",
      image_url: null,
      chain: "Mercadona",
      price: "1.05",
      unit_price: "1.05",
      base_unit: "l",
      base_quantity: "1",
      canonical: { id: 201, name: "Leche entera", category_key: "leche-entera", category_name: "Leche entera" },
    },
  ],
};

const ROUTE_ERROR = "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos.";

test.beforeEach(async ({ page }) => {
  await blockUnmocked(page);
  await page.route(/tile\.openstreetmap\.org/, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TRANSPARENT_1X1_PNG }),
  );
  await mockJson(page, "**/api/health", mockHealth);
  await mockJson(page, "**/api/categories", mockCategories);
  await mockJson(page, "**/api/sections", { sections: [] });
  await mockJson(page, "**/api/search*", mockSearch);
  await mockJson(page, "**/api/geocode*", mockGeocode);
  await mockJson(page, "**/api/canonicals/201", mockCanonicalDetail);
});

async function setPrestoredOrigin(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "smart-basket.lists",
      JSON.stringify({
        schema_version: 3,
        lists: [],
        cart: [],
        origin: { lat: 42.5987, lon: -5.5671, label: "Plaza Mayor, 24003 León" },
        options: { mode: "walk", maxStores: 2, priority: "balanced", returnToOrigin: true },
      }),
    );
  });
}

test("vague line presents choices inline and resolves before calculation", async ({ page }) => {
  await setPrestoredOrigin(page);
  await mockJson(page, "**/api/interpret", mockInterpretWithVague);
  await mockJson(page, "**/api/recommendations", mockRecommendation);

  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  await page.goto("/#/lista");
  const textarea = page.getByRole("textbox", { name: "Tu lista" });
  await textarea.fill("2 l de leche\npollo");

  // Click Calcular
  await page.getByRole("button", { name: "Calcular", exact: true }).click();

  // Vague line header appears inline
  await expect(page.getByRole("heading", { name: "¿Qué pollo?" })).toBeVisible();
  // Two chips with options
  const pechugaChip = page.getByRole("button", { name: /Pechuga de pollo/ });
  const muslosChip = page.getByRole("button", { name: /Muslos de pollo/ });
  await expect(pechugaChip).toBeVisible();
  await expect(muslosChip).toBeVisible();
  await expect(page.getByText(/desde 2,50\s*€\/kg/)).toBeVisible();

  // No recommendation request yet
  expect(recRequests).toHaveLength(0);

  // Pick "Pechuga de pollo"
  await pechugaChip.click();

  // Now resolved, pick Calcular again
  const recPromise = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular", exact: true }).click();

  const sent = await recPromise;
  const body = sent.postDataJSON();
  expect(body.items).toHaveLength(2);
  expect(body.items[0].category_key).toBe("leche-entera");
  expect(body.items[1].category_key).toBe("pollo_pechuga");
  expect(body.items[1].text).toBe("pollo");
  expect(body.origin).toEqual({ lat: 42.5987, lon: -5.5671 });

  // Basket is shown
  await expect(page.getByRole("heading", { name: "Tu cesta" })).toBeVisible();
  await expect(page.getByText("Leche entera Pascual 1L")).toBeVisible();
  expect(recRequests).toHaveLength(1);
});

test("basket with flex_savings offers applying any brand", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "smart-basket.lists",
      JSON.stringify({
        schema_version: 3,
        lists: [],
        cart: [
          {
            id: "cart-1",
            product_id: 101,
            name: "Leche entera Pascual 1L",
            brand: "Pascual",
            packaging: "Botella 1 L",
            image_url: null,
            category_key: "leche-entera",
            category_name: "Leche entera",
            quantity: 2,
            accept: "exact",
            locked: false,
          },
        ],
        origin: { lat: 42.5987, lon: -5.5671, label: "Plaza Mayor, 24003 León" },
        options: { mode: "walk", maxStores: 2, priority: "balanced", returnToOrigin: true },
      }),
    );
  });

  const flexRecommendation: Recommendation = {
    ...mockRecommendation,
    flex_savings: {
      total: "0.85",
      lines: [{ line_id: 0, savings: "0.85" }],
    },
  };
  await mockJson(page, "**/api/recommendations", flexRecommendation);

  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  await page.goto("/#/lista");
  // Open cart drawer and calculate basket from concrete item
  await page.getByRole("button", { name: "Cesta" }).click();
  const firstRecPromise = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular cesta" }).click();

  const firstReq = await firstRecPromise;
  const firstBody = firstReq.postDataJSON();
  expect(firstBody.items[0].product_id).toBe(101);
  expect(firstBody.items[0].accept).toBe("exact");

  // Savings notice is visible
  await expect(page.getByText(/Con cualquier marca ahorrarías 0,85\s*€\./)).toBeVisible();
  await expect(page.getByText(/0,85\s*€ menos con cualquier marca/)).toBeVisible();

  // Click "Aplicar a toda la lista"
  const secondRecPromise = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Aplicar a toda la lista" }).click();

  const secondReq = await secondRecPromise;
  const secondBody = secondReq.postDataJSON();
  expect(secondBody.items[0].product_id).toBe(101);
  expect(secondBody.items[0].accept).toBe("equivalent");

  await expect.poll(() => recRequests.length).toBe(2);
});

test("basket line with canonical_id can be swapped for an alternative product", async ({ page }) => {
  await setPrestoredOrigin(page);
  await mockJson(page, "**/api/interpret", mockInterpretResolved);
  await mockJson(page, "**/api/recommendations", mockRecommendation);

  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  await page.goto("/#/lista");
  await page.getByRole("textbox", { name: "Tu lista" }).fill("2 l de leche");
  const firstRecPromise = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular", exact: true }).click();
  await firstRecPromise;

  await expect(page.getByText("Leche entera Pascual 1L")).toBeVisible();
  expect(recRequests).toHaveLength(1);

  // Click "Cambiar" on the basket line
  await page.getByRole("button", { name: "Cambiar" }).click();

  // Modal appears with alternatives
  const hacendadoOption = page.getByRole("button", { name: /Leche entera Hacendado 1L/ });
  await expect(hacendadoOption).toBeVisible();

  const secondRecPromise = page.waitForRequest("**/api/recommendations");
  await hacendadoOption.click();

  const sent = await secondRecPromise;
  const body = sent.postDataJSON();
  expect(body.items[0].product_id).toBe(999);
  expect(body.items[0].accept).toBe("exact");

  await expect.poll(() => recRequests.length).toBe(2);
});

test("remembered origin appears folded on reload and is reused without prompting", async ({ page }) => {
  // Do not seed localStorage: pick an origin using the simulated search
  await mockJson(page, "**/api/interpret", mockInterpretResolved);
  await mockJson(page, "**/api/recommendations", mockRecommendation);

  await page.goto("/#/lista");
  await expect(page.getByRole("heading", { name: "¿Desde dónde sales?" })).toBeVisible();

  const address = page.getByRole("searchbox", { name: "Escribe una dirección de León" });
  await address.fill("Plaza Mayor");
  await page.getByRole("button", { name: "Buscar" }).click();
  await page.getByRole("button", { name: /Plaza Mayor, 24003 León/ }).click();

  // Folded origin row shows label
  await expect(
    page.getByText(/Desde:\s*Plaza Mayor, 24003 León\s*·\s*A pie\s*·\s*Hasta 2 tiendas/),
  ).toBeVisible();

  // Reload page
  await page.reload();

  // Folded origin row still visible
  await expect(
    page.getByText(/Desde:\s*Plaza Mayor, 24003 León\s*·\s*A pie\s*·\s*Hasta 2 tiendas/),
  ).toBeVisible();

  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  // Write list and calculate: goes directly to basket without asking for origin
  await page.getByRole("textbox", { name: "Tu lista" }).fill("2 l de leche");
  const recPromise = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular", exact: true }).click();
  await recPromise;

  await expect(page.getByRole("heading", { name: "Tu cesta" })).toBeVisible();
  expect(recRequests).toHaveLength(1);
  expect(recRequests[0].postDataJSON().origin).toEqual({ lat: 42.5987, lon: -5.5671 });
});

test("address search waits for Enter and three characters", async ({ page }) => {
  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  const searches: string[] = [];
  await page.route("**/api/geocode*", (route) => {
    searches.push(route.request().url());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockGeocode),
    });
  });

  await page.goto("/#/lista");
  // Origin is not set yet, so unfolded origin section is open
  await expect(page.getByRole("heading", { name: "¿Desde dónde sales?" })).toBeVisible();

  const address = page.getByRole("searchbox", { name: "Escribe una dirección de León" });
  const buscar = page.getByRole("button", { name: "Buscar" });
  await expect(buscar).toBeDisabled();

  await address.fill("Ca");
  await expect(buscar).toBeDisabled();
  await page.waitForTimeout(500);
  expect(searches).toHaveLength(0);

  await address.fill("Calle Ancha");
  await expect(buscar).toBeEnabled();
  await address.press("Enter");

  await expect.poll(() => searches.length).toBe(1);
  expect(searches[0]).toContain("q=Calle%20Ancha");
  await expect(page.getByText(mockGeocode.results[0].label)).toBeVisible();
  expect(recRequests).toHaveLength(0);
});

test("recommendations 503 displays the error inline", async ({ page }) => {
  const recRequests: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/recommendations")) recRequests.push(req);
  });

  await setPrestoredOrigin(page);
  await mockJson(page, "**/api/interpret", mockInterpretResolved);
  await mockJson(page, "**/api/recommendations", { detail: ROUTE_ERROR }, 503);

  await page.goto("/#/lista");
  await page.getByRole("textbox", { name: "Tu lista" }).fill("2 l de leche");
  await page.getByRole("button", { name: "Calcular", exact: true }).click();

  await expect(page.getByRole("alert").filter({ hasText: ROUTE_ERROR })).toBeVisible();
  // Flow remains on the list screen
  await expect(page.getByRole("button", { name: "Calcular", exact: true })).toBeVisible();
  await expect.poll(() => recRequests.length).toBe(1);
});
