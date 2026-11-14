import { expect, test } from "@playwright/test";
import type { Product, SectionsResponse } from "../src/api";
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

const CATALOG: { section: string; product: Product }[] = [
  { section: "lacteos", product: leche },
  { section: "lacteos", product: diaLeche },
  { section: "aceites", product: aceite },
];

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
});

test("home, section, sort, product page and cart reach the origin step", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Tu compra más barata en León" })).toBeVisible();
  await expect(page.getByPlaceholder(HOME_SEARCH_PLACEHOLDER)).toBeVisible();

  // A section card opens its catalog.
  await page.getByRole("link", { name: /Lácteos/ }).click();
  await expect(page).toHaveURL(/#\/catalogo\/lacteos$/);
  await expect(page.getByRole("heading", { name: "Lácteos" })).toBeVisible();
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
  await expect(drawer.getByText("Cualquier Leche entera")).toBeVisible();

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
      candidate.url().includes("/api/products?") && candidate.url().includes("q=Leche"),
  );
  await page.getByRole("button", { name: "Leche" }).click();
  await request;

  await expect(page).toHaveURL(/#\/catalogo$/);
  await expect(page.getByRole("heading", { name: "Resultados para «Leche»" })).toBeVisible();
  // Both milks, and none of the oil.
  await expect(page.locator("article")).toHaveCount(2);
  await expect(page.getByText("2 productos")).toBeVisible();
  await expect(page.getByText(aceite.name)).toHaveCount(0);
});

test("the header searches from any page", async ({ page }) => {
  await page.goto("/#/catalogo");
  await expect(page.locator("article")).toHaveCount(3);

  const search = page.getByRole("searchbox", { name: "Buscar en el catálogo" });
  await search.fill("aceite");
  await search.press("Enter");

  await expect(page.getByRole("heading", { name: "Resultados para «aceite»" })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(1);
  await expect(page.getByPlaceholder(PRODUCT_SEARCH_PLACEHOLDER)).toHaveValue("aceite");
});
