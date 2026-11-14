import { type Page, expect, test } from "@playwright/test";
import type {
  CanonicalCard,
  Product,
  Recommendation,
  SectionsResponse,
} from "../src/api";
import { parseDecimal } from "../src/format";
import { HOME_SEARCH_PLACEHOLDER, PRODUCT_SEARCH_PLACEHOLDER } from "../src/texts";
import { blockUnmocked, mockJson, TRANSPARENT_1X1_PNG } from "./mock";

const PHOTO = "https://photos.test/product.png";

const mockSections: SectionsResponse = {
  sections: [
    { key: "lacteos", name: "Lácteos", products: 2, image_url: PHOTO },
    { key: "aceites", name: "Aceites", products: 1, image_url: PHOTO },
  ],
};

const leche: Product = {
  id: 1,
  name: "Leche entera 6 x 1 L",
  brand: "Pascual",
  private_label: false,
  packaging: "Pack 6 uds",
  image_url: PHOTO,
  chain: "mercadona",
  price: "6.30",
  unit_price: "1.05",
  base_unit: "l",
  base_quantity: "6",
  canonical: {
    id: 10,
    name: "Leche entera",
    category_key: "leche-entera",
    category_name: "Leche entera",
  },
};

const diaLeche: Product = {
  id: 2,
  name: "Leche entera 1 L",
  brand: "Dia",
  private_label: true,
  packaging: "Botella 1 L",
  image_url: PHOTO,
  chain: "dia",
  price: "1.09",
  unit_price: "1.09",
  base_unit: "l",
  base_quantity: "1",
  canonical: {
    id: 10,
    name: "Leche entera",
    category_key: "leche-entera",
    category_name: "Leche entera",
  },
};

const aceite: Product = {
  id: 3,
  name: "Aceite de oliva virgen extra 1 L",
  brand: "Hacendado",
  private_label: true,
  packaging: "Botella 1 L",
  image_url: PHOTO,
  chain: "mercadona",
  price: "7.50",
  unit_price: "7.50",
  base_unit: "l",
  base_quantity: "1",
  canonical: {
    id: 11,
    name: "Aceite de oliva virgen extra",
    category_key: "aceite-oliva",
    category_name: "Aceite de oliva virgen extra",
  },
};

const lecheCard: CanonicalCard = {
  id: 10,
  name: "Leche entera",
  category_key: "leche-entera",
  category_name: "Leche entera",
  image_url: PHOTO,
  from_price: "1.05",
  from_unit_price: "1.05",
  base_unit: "l",
  product_count: 2,
  chains: ["mercadona", "dia"],
};

const aceiteCard: CanonicalCard = {
  id: 11,
  name: "Aceite de oliva virgen extra",
  category_key: "aceite-oliva",
  category_name: "Aceite de oliva virgen extra",
  image_url: PHOTO,
  from_price: "7.50",
  from_unit_price: "7.50",
  base_unit: "l",
  product_count: 1,
  chains: ["mercadona"],
};

const CANONICALS: { section: string; card: CanonicalCard }[] = [
  { section: "lacteos", card: lecheCard },
  { section: "aceites", card: aceiteCard },
];

const CATALOG: { section: string; product: Product }[] = [
  { section: "lacteos", product: leche },
  { section: "lacteos", product: diaLeche },
  { section: "aceites", product: aceite },
];

const emptyRecommendation: Recommendation = {
  id: "rec-1",
  data_as_of: null,
  engine_version: "0.1.0",
  stores: [],
  total_cost: "0",
  minutes: "0",
  missing: [],
  route: [],
  explanation: "No hay tiendas con esos productos.",
  degraded: false,
  flex_savings: null,
};

/** Reads the stored profile from IndexedDB, so the test waits for the real write. */
async function profileHas(page: Page, needle: string): Promise<boolean> {
  return page.evaluate(async (text) => {
    try {
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open("smart-basket");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const stored = await new Promise<unknown>((resolve, reject) => {
        const transaction = database.transaction("profile", "readonly");
        const request = transaction.objectStore("profile").get("profile");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      database.close();
      return JSON.stringify(stored ?? null).includes(text);
    } catch {
      return false;
    }
  }, needle);
}

test.beforeEach(async ({ page }) => {
  await blockUnmocked(page);
  // Product and section photos: a transparent 1x1 PNG.
  await page.route("https://photos.test/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TRANSPARENT_1X1_PNG }),
  );
  await mockJson(page, "**/api/sections", mockSections);
  await page.route("**/api/products**", (route) => {
    const url = new URL(route.request().url());
    const detail = /\/api\/products\/(\d+)$/.exec(url.pathname);
    if (detail) {
      const product = CATALOG.find((entry) => entry.product.id === Number(detail[1]))?.product;
      if (!product) return route.fulfill({ status: 404, body: JSON.stringify({ detail: "No existe" }) });
      const alternatives = CATALOG.map((entry) => entry.product).filter(
        (candidate) =>
          candidate.id !== product.id &&
          candidate.canonical?.category_key === product.canonical?.category_key,
      );
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...product, alternatives }),
      });
    }

    const section = url.searchParams.get("section");
    const query = (url.searchParams.get("q") ?? "").toLowerCase();
    const sort = url.searchParams.get("sort") ?? "unit_price";
    const items = CATALOG.filter((entry) => section === null || entry.section === section)
      .map((entry) => entry.product)
      .filter(
        (product) =>
          query === "" ||
          product.name.toLowerCase().includes(query) ||
          (product.brand ?? "").toLowerCase().includes(query),
      )
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name, "es");
        const field = sort === "price" ? "price" : "unit_price";
        return parseDecimal(a[field]) - parseDecimal(b[field]);
      });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items, total: items.length, page: 1, size: 24 }),
    });
  });

  await page.route("**/api/canonicals**", (route) => {
    const url = new URL(route.request().url());
    const detail = /\/api\/canonicals\/(\d+)$/.exec(url.pathname);
    if (detail) {
      const entry = CANONICALS.find((candidate) => candidate.card.id === Number(detail[1]));
      if (!entry) {
        return route.fulfill({ status: 404, body: JSON.stringify({ detail: "No existe" }) });
      }
      const products = CATALOG.filter(
        (candidate) => candidate.product.canonical?.id === entry.card.id,
      ).map((candidate) => candidate.product);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...entry.card, products }),
      });
    }

    const section = url.searchParams.get("section");
    const query = (url.searchParams.get("q") ?? "").toLowerCase();
    const items = CANONICALS.filter((entry) => section === null || entry.section === section)
      .map((entry) => entry.card)
      .filter((card) => query === "" || card.name.toLowerCase().includes(query));
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items, total: items.length, page: 1, size: 24 }),
    });
  });
});

test("home, section, sort, product page and cart reach the origin step", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Tu compra más barata en León" })).toBeVisible();
  await expect(page.getByPlaceholder(HOME_SEARCH_PLACEHOLDER)).toBeVisible();

  // A section card opens its catalog, by generic product.
  await page.getByRole("link", { name: /Lácteos/ }).click();
  await expect(page).toHaveURL(/#\/catalogo\/lacteos$/);
  await expect(page.getByRole("heading", { name: "Lácteos" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Por producto" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  // The supermarket tab shows the concrete products, as before.
  await page.getByRole("tab", { name: "Por supermercado" }).click();
  await expect(page).toHaveURL(/#\/catalogo\/lacteos\?vista=super$/);
  await expect(page.getByText("2 productos")).toBeVisible();

  const cards = page.locator("article");
  await expect(cards).toHaveCount(2);
  // Default order: price per unit, so the six-pack comes first.
  await expect(cards.first()).toContainText(leche.name);
  await expect(cards.first()).toContainText("1,05 €/l");

  const sorted = page.waitForRequest(
    (request) => request.url().includes("/api/products?") && request.url().includes("sort=price"),
  );
  await page.getByRole("combobox", { name: "Ordenar por" }).selectOption("price");
  await sorted;
  await expect(cards.first()).toContainText(diaLeche.name);

  // Product page: one specific line and one generic line.
  await page.getByRole("link", { name: diaLeche.name }).first().click();
  await expect(page).toHaveURL(/#\/producto\/2$/);
  await expect(page.getByRole("heading", { name: diaLeche.name })).toBeVisible();
  await expect(page.getByText("1,09 €/l")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Otras opciones" })).toBeVisible();
  await expect(page.getByText(leche.name, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Añadir este producto" }).click();
  await page.getByRole("button", { name: 'Añadir cualquier "Leche entera"' }).click();

  await expect(page.getByRole("button", { name: "Cesta", exact: true })).toContainText("2");
  await page.getByRole("button", { name: "Cesta", exact: true }).click();

  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText(diaLeche.name, { exact: true })).toBeVisible();
  await expect(
    drawer.locator("p").filter({ hasText: "Cualquier leche entera" }),
  ).toBeVisible();

  // Quantity stepper: the specific line goes from one to two.
  const firstLine = drawer.locator("li").first();
  await firstLine.getByRole("button", { name: "Sumar cantidad" }).click();
  await expect(firstLine.getByText("2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cesta", exact: true })).toContainText("3");
  // Changing a quantity does not move the focus out of the line.
  await expect(firstLine.getByRole("button", { name: "Sumar cantidad" })).toBeFocused();

  // Escape closes the dialog and gives the focus back to the button that opened it.
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("button", { name: "Cesta", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Cesta", exact: true }).click();
  await expect(drawer.getByRole("button", { name: "Cerrar" })).toBeFocused();

  await drawer.getByRole("button", { name: "Calcular cesta" }).click();
  await expect(page).toHaveURL(/#\/lista$/);
  await expect(page.getByRole("heading", { name: "¿Desde dónde sales?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Calcular cesta" })).toBeDisabled();

  // The cart survives a reload.
  await page.reload();
  await expect(page.getByRole("button", { name: "Cesta", exact: true })).toContainText("3");
});

test("the home suggestion searches across sections", async ({ page }) => {
  await page.goto("/");
  const request = page.waitForRequest(
    (candidate) =>
      candidate.url().includes("/api/canonicals?") && candidate.url().includes("q=Leche"),
  );
  await page.getByRole("button", { name: "Leche" }).click();
  await request;

  await expect(page).toHaveURL(/#\/catalogo$/);
  await expect(page.getByRole("heading", { name: "Resultados para «Leche»" })).toBeVisible();
  // One generic milk, and none of the oil.
  const cards = page.locator("article");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Leche entera");
  await expect(cards.first()).toContainText("2 productos");
  await expect(page.getByText(aceite.name)).toHaveCount(0);
});

test("the header searches from any page", async ({ page }) => {
  await page.goto("/#/catalogo");
  await expect(page.locator("article")).toHaveCount(2);

  const search = page.getByRole("searchbox", { name: "Buscar en el catálogo" });
  await search.fill("aceite");
  await search.press("Enter");

  await expect(page.getByRole("heading", { name: "Resultados para «aceite»" })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(1);
  await expect(page.getByPlaceholder(PRODUCT_SEARCH_PLACEHOLDER)).toHaveValue("aceite");
});

test("the catalog opens by generic product and adds a generic line", async ({ page }) => {
  await page.goto("/#/catalogo");
  await expect(page.getByRole("tab", { name: "Por producto" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  const cards = page.locator("article");
  await expect(cards).toHaveCount(2);
  const milk = cards.filter({ hasText: "Leche entera" });
  await expect(milk).toContainText("desde 1,05 €/l");
  await expect(milk).toContainText("2 productos");

  await milk.getByRole("button", { name: "Añadir" }).click();
  await page.getByRole("button", { name: "Cesta", exact: true }).click();

  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  await expect(
    drawer.locator("p").filter({ hasText: "Cualquier leche entera" }),
  ).toBeVisible();
});

test("a canonical page adds any product or one concrete one", async ({ page }) => {
  await page.goto("/#/generico/10");
  await expect(page.getByRole("heading", { name: "Leche entera", level: 1 })).toBeVisible();
  await expect(page.getByText("desde 1,05 €/l")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Elige uno concreto" })).toBeVisible();

  await page.getByRole("button", { name: "Añadir cualquier leche entera" }).click();
  const concrete = page.locator("article").filter({ hasText: diaLeche.name });
  await concrete.getByRole("button", { name: "Añadir" }).click();

  await page.getByRole("button", { name: "Cesta", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  await expect(
    drawer.locator("p").filter({ hasText: "Cualquier leche entera" }),
  ).toBeVisible();

  const concreteLine = drawer.locator("li").filter({ hasText: diaLeche.name });
  await expect(
    concreteLine.getByRole("combobox", { name: "Qué acepta esta línea" }),
  ).toHaveValue("exact");
});

test("Me da igual la marca leaves the pinned line exact", async ({ page }) => {
  await page.goto("/#/catalogo?vista=super");
  const cards = page.locator("article");
  await cards.filter({ hasText: leche.name }).getByRole("button", { name: "Añadir" }).click();
  await cards.filter({ hasText: aceite.name }).getByRole("button", { name: "Añadir" }).click();

  await page.getByRole("button", { name: "Cesta", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  const first = drawer.locator("li").first();
  const second = drawer.locator("li").nth(1);
  const accept = (line: typeof first) =>
    line.getByRole("combobox", { name: "Qué acepta esta línea" });

  await expect(accept(first)).toHaveValue("exact");
  await first.getByRole("button", { name: "Fijar este producto" }).click();
  await expect(first.getByRole("button", { name: "Quitar fijación" })).toBeVisible();

  const toggle = drawer.getByRole("switch", { name: "Me da igual la marca" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();

  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(accept(first)).toHaveValue("exact");
  await expect(accept(second)).toHaveValue("equivalent");

  // Turning it off does not change the lines again.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(accept(second)).toHaveValue("equivalent");
});

test("the selected chains travel in the recommendation request", async ({ page }) => {
  await mockJson(page, "**/api/recommendations", emptyRecommendation);
  await page.goto("/#/producto/1");
  await page.getByRole("button", { name: "Añadir este producto" }).click();
  await page.getByRole("button", { name: "Cesta", exact: true }).click();

  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  const mercadona = drawer.getByRole("button", { name: "Mercadona" });
  await mercadona.click();
  await expect(mercadona).toHaveAttribute("aria-pressed", "true");
  await expect(drawer.getByRole("button", { name: "Todas" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  await drawer.getByRole("button", { name: "Calcular cesta" }).click();
  await expect(page.locator(".map")).toBeVisible();
  await page.locator(".map").click();

  const sent = page.waitForRequest("**/api/recommendations");
  await page.getByRole("button", { name: "Calcular cesta" }).click();
  const body = (await sent).postDataJSON();
  expect(body.chains).toEqual(["mercadona"]);
});

test("the padlock, the switch and the chains survive a reload", async ({ page }) => {
  await page.goto("/#/producto/1");
  await page.getByRole("button", { name: "Añadir este producto" }).click();
  await page.getByRole("button", { name: "Cesta", exact: true }).click();

  const drawer = page.getByRole("dialog", { name: "Tu cesta" });
  const line = drawer.locator("li").first();
  await line.getByRole("button", { name: "Fijar este producto" }).click();
  await drawer.getByRole("switch", { name: "Me da igual la marca" }).click();
  await drawer.getByRole("button", { name: "Mercadona" }).click();

  await expect.poll(() => profileHas(page, "brand_pin")).toBe(true);
  await expect.poll(() => profileHas(page, "any_brand")).toBe(true);
  await expect.poll(() => profileHas(page, "chain_include")).toBe(true);

  await page.reload();
  await expect(page.getByRole("button", { name: "Cesta", exact: true })).toContainText("1");
  await page.getByRole("button", { name: "Cesta", exact: true }).click();

  const reopened = page.getByRole("dialog", { name: "Tu cesta" });
  await expect(reopened.getByRole("button", { name: "Quitar fijación" })).toBeVisible();
  await expect(reopened.getByRole("switch", { name: "Me da igual la marca" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(reopened.getByRole("button", { name: "Mercadona" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    reopened.getByRole("combobox", { name: "Qué acepta esta línea" }),
  ).toHaveValue("exact");
});

test("a product without brand shows its chain logo on the card", async ({ page }) => {
  // A product with no brand in the supermarket catalog.
  await page.route("**/api/products**", (route) => {
    const url = new URL(route.request().url());
    if (/\/api\/products\/\d+$/.test(url.pathname)) return route.fallback();
    const unbranded = { ...diaLeche, brand: null };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [unbranded], total: 1, page: 1, size: 24 }),
    });
  });

  await page.goto("/#/catalogo?vista=super");
  const card = page.locator("article").first();
  await expect(card.getByRole("img", { name: "dia" })).toBeVisible();
});
