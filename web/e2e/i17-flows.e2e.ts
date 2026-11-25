// E2E flows of the Iteration 17 web rework: the conversational agent (questions, accumulated
// changes, «Sin asistente»), the plan view, the native dialogs (Cambiar, Ajustes, saved lists)
// and the mobile layout guarantees. Every test runs under the page guard of `mock.ts`: any
// console error, page error or unexpected /api failure fails the test.

import { type Page } from "@playwright/test";
import type {
  AgentRunResponse,
  CanonicalDetail,
  CategoriesResponse,
  ChainsResponse,
  Health,
  InterpretResponse,
  Product,
  Recommendation,
  SectionsResponse,
} from "../src/api";
import {
  blockUnmocked,
  countAgentRunResponses,
  expect,
  expectNoHorizontalOverflow,
  mockJson,
  test,
  TRANSPARENT_1X1_PNG,
} from "./mock";

const ORIGIN = { lat: 42.5987, lon: -5.5671, label: "Plaza Mayor, 24003 León" };

const mockHealth: Health = {
  status: "ok",
  version: "0.1.0",
  engine_version: "0.1.0",
  database: "ok",
};

const mockSections: SectionsResponse = {
  sections: [{ key: "lacteos", name: "Lácteos", products: 2, image_url: null }],
};

const mockChains: ChainsResponse = {
  chains: [
    {
      code: "mercadona",
      name: "Mercadona",
      store_count: 3,
      product_count: 120,
      last_price_at: null,
    },
  ],
};

const interpretResolved: InterpretResponse = {
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
      exact_only: false,
      image_url: null,
      options: [],
    },
  ],
  llm_used: false,
  degraded: false,
};

/** The plan on screen: one Mercadona store selling one line of milk, route of two points. */
const baseRecommendation: Recommendation = {
  id: "rec-1",
  data_as_of: "2026-11-20T12:00:00Z",
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
          exact_only: false,
          product_name: "Leche entera Pascual 1L",
          brand: "Pascual",
          image_url: null,
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

/** One generic milk line, as the draft keeps it in localStorage. */
function lecheDraftItem(): Record<string, unknown> {
  return {
    id: "line-1",
    text: "2 l de leche",
    categoryKey: "leche-entera",
    categoryName: "Leche entera",
    quantity: "2",
    unit: "l",
    brand: "",
    privateLabelOk: true,
  };
}

/** Fills localStorage with an origin, route options and the given draft. */
async function seedStore(
  page: Page,
  options: { draftItems?: Record<string, unknown>[]; draftText?: string } = {},
): Promise<void> {
  // The init script runs on every load; the flag makes it seed only the first one, so a
  // reload within the test keeps what the app has written since (M12).
  await page.addInitScript(
    (payload) => {
      if (localStorage.getItem("smart-basket.e2e-seeded")) return;
      localStorage.setItem("smart-basket.e2e-seeded", "1");
      localStorage.setItem("smart-basket.lists", JSON.stringify(payload.store));
    },
    {
      store: {
        schema_version: 4,
        lists: [],
        cart: [],
        draftText: options.draftText ?? "",
        draftItems: options.draftItems ?? [],
        origin: { lat: 42.5987, lon: -5.5671, label: "Plaza Mayor, 24003 León" },
        options: { mode: "walk", maxStores: 2, priority: "balanced", returnToOrigin: true },
      },
    },
  );
}

/** A completed agent run, with the fields the plan view reads. */
function agentRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    run_id: "run-1",
    recommendation_id: "rec-1",
    status: "completed",
    policy_name: "Agente ahorrador",
    model_name: "gpt-oss-120b",
    steps_count: 0,
    total_latency_ms: 12,
    buyer_summary: null,
    pending_question: null,
    alternatives_shown: [],
    mode: "walk",
    excluded_chains: [],
    recommendation: null,
    steps: [],
    ...overrides,
  };
}

/** The plan request bodies, in order, from a route that always answers the same plan. */
async function mockRecommendations(
  page: Page,
  recommendation: Recommendation,
): Promise<unknown[]> {
  const bodies: unknown[] = [];
  await page.route("**/api/recommendations", (route) => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(recommendation),
    });
  });
  return bodies;
}

/** Calculates the seeded list and waits for the plan view. */
async function calculatePlan(page: Page): Promise<void> {
  await page.goto("/#/lista");
  await page.getByRole("button", { name: "Calcular plan", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tu plan de compra" })).toBeVisible();
}

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

/** True when the only open dialog is a native <dialog> shown with showModal. */
async function isOpenNativeDialog(page: Page): Promise<boolean> {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog.evaluate((element) => element instanceof HTMLDialogElement && element.open);
}

test.beforeEach(async ({ page }) => {
  await blockUnmocked(page);
  await page.route(/tile\.openstreetmap\.org/, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TRANSPARENT_1X1_PNG }),
  );
  await mockJson(page, "**/api/health", mockHealth);
  await mockJson(page, "**/api/categories", { sections: [] } satisfies CategoriesResponse);
  await mockJson(page, "**/api/chains", mockChains);
  await mockJson(page, "**/api/sections", mockSections);
  await mockJson(page, "**/api/geocode*", { results: [] });
  // The catalog the overflow sweep and «Elegir en el catálogo» open.
  await mockJson(page, "**/api/canonicals?*", { items: [], total: 0, page: 1, size: 24 });
  // The app always asks the agent to review a fresh plan; it may answer nothing new.
  await mockJson(page, "**/api/agent/runs", agentRun());
});

test("a waiting agent question offers clickable options and applies the answer", async ({
  page,
}) => {
  await seedStore(page, { draftItems: [lecheDraftItem()] });

  const waiting = agentRun({
    status: "waiting_shopper",
    pending_question: {
      line_index: 0,
      prompt: "¿Qué leche compras normalmente?",
      options: [
        { label: "Leche entera", canonical_id: 201, price: "1.05" },
        { label: "Leche sin lactosa", canonical_id: 202, price: "1.15" },
      ],
    },
  });
  await mockJson(page, "**/api/recommendations", baseRecommendation);
  await mockJson(page, "**/api/agent/runs", waiting);

  const answeredRecommendation: Recommendation = {
    ...baseRecommendation,
    stores: [
      {
        ...baseRecommendation.stores[0],
        lines: [
          {
            ...baseRecommendation.stores[0].lines[0],
            product_id: 999,
            product_name: "Leche entera Hacendado 1L",
            brand: "Hacendado",
            cost: "1.05",
          },
        ],
        subtotal: "1.05",
      },
    ],
    total_cost: "1.05",
  };
  let answerBody: unknown = null;
  await page.route("**/api/agent/runs/*/answer", (route) => {
    answerBody = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        agentRun({
          buyer_summary: "He cambiado la leche por la que has elegido.",
          recommendation: answeredRecommendation,
        }),
      ),
    });
  });

  await calculatePlan(page);

  // The question box with its priced options.
  await expect(page.getByText("¿Qué leche compras normalmente?")).toBeVisible();
  const entera = page.getByRole("button", { name: /Leche entera.*1,05 €/ });
  await expect(entera).toBeVisible();
  await expect(page.getByRole("button", { name: /Leche sin lactosa.*1,15 €/ })).toBeVisible();

  await entera.click();

  // The click answers the run with the option it stands for.
  await expect.poll(() => answerBody).toEqual({
    option_index: 0,
    choice_label: "Leche entera",
    canonical_id: 201,
  });
  // The plan takes the product of the chosen option, and the question is gone.
  await expect(page.getByText("Leche entera Hacendado 1L")).toBeVisible();
  await expect(page.getByText("He cambiado la leche por la que has elegido.")).toBeVisible();
  await expect(page.getByText("¿Qué leche compras normalmente?")).toHaveCount(0);
});

test("follow-up chips keep the conversation on one run and one summary (C2, M5)", async ({
  page,
}) => {
  await seedStore(page, { draftItems: [lecheDraftItem()] });
  await mockJson(page, "**/api/recommendations", baseRecommendation);

  const firstSummary = "He revisado tu cesta: todo en Mercadona por 1,90 €.";
  const withoutLidl = "He quitado Lidl del plan.";
  const oneStore = "Ahora compras todo en una sola tienda.";
  await mockJson(
    page,
    "**/api/agent/runs",
    agentRun({ buyer_summary: firstSummary, recommendation: baseRecommendation }),
  );

  const messages: { url: string; body: unknown }[] = [];
  let followUps = 0;
  await page.route("**/api/agent/runs/*/message", (route) => {
    followUps += 1;
    messages.push({ url: route.request().url(), body: route.request().postDataJSON() });
    const run =
      followUps === 1
        ? agentRun({
            buyer_summary: withoutLidl,
            excluded_chains: ["lidl"],
            recommendation: {
              ...baseRecommendation,
              explanation: "Sin Lidl, el plan se queda como estaba.",
            },
          })
        : agentRun({
            buyer_summary: oneStore,
            recommendation: {
              ...baseRecommendation,
              explanation: "Con una sola tienda, el plan es este.",
            },
          });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(run),
    });
  });

  await calculatePlan(page);

  // One summary (M5): the agent's confirmation, never the engine explanation next to it.
  await expect(page.getByText(firstSummary)).toBeVisible();
  await expect(page.getByText(baseRecommendation.explanation)).toHaveCount(0);

  // «Sin Lidl» and then «Solo 1 tienda», as quick chips.
  await page.getByRole("button", { name: "Sin Lidl", exact: true }).click();
  await expect(page.getByText(withoutLidl)).toBeVisible();
  await expect(page.getByText("Sin Lidl, el plan se queda como estaba.")).toHaveCount(0);

  await page.getByRole("button", { name: "Solo 1 tienda", exact: true }).click();
  await expect(page.getByText(oneStore)).toBeVisible();
  await expect(page.getByText("Con una sola tienda, el plan es este.")).toHaveCount(0);

  // Both changes travelled as messages of the same run, with the origin.
  expect(messages).toHaveLength(2);
  expect(messages[0].url).toContain("/api/agent/runs/run-1/message");
  expect(messages[1].url).toContain("/api/agent/runs/run-1/message");
  expect(messages[0].body).toEqual({
    message: "Sin Lidl",
    origin: { lat: ORIGIN.lat, lon: ORIGIN.lon },
  });
  expect(messages[1].body).toEqual({
    message: "Solo 1 tienda",
    origin: { lat: ORIGIN.lat, lon: ORIGIN.lon },
  });
});

test("«Sin asistente» recalculates with the default policy and disables the changes", async ({
  page,
}) => {
  await seedStore(page, { draftItems: [lecheDraftItem()] });
  await mockJson(page, "**/api/recommendations", baseRecommendation);

  const runs: Record<string, unknown>[] = [];
  const agentRunsDone = countAgentRunResponses(page);
  await page.route("**/api/agent/runs", (route) => {
    runs.push(route.request().postDataJSON() as Record<string, unknown>);
    const run =
      runs.length === 1
        ? agentRun({ buyer_summary: "He revisado tu cesta con el asistente." })
        : agentRun({ policy_name: "default", buyer_summary: null });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(run),
    });
  });

  await calculatePlan(page);
  await expect(page.getByText("He revisado tu cesta con el asistente.")).toBeVisible();

  const toggle = page.getByRole("switch", { name: "Sin asistente" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();

  // The recalculation asks for the default policy, with no agent summary on top.
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => runs.length).toBe(2);
  expect(runs[0]).not.toHaveProperty("policy");
  expect(runs[1]).toMatchObject({ policy: "default" });
  await expect(page.getByText("He revisado tu cesta con el asistente.")).toHaveCount(0);
  await expect(page.getByText(baseRecommendation.explanation)).toBeVisible();

  // «Pide un cambio» and its chips are disabled, with a clear notice.
  await expect(page.getByLabel("Pide un cambio")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Sin Lidl", exact: true })).toBeDisabled();
  await expect(
    page.getByText(
      "El asistente de compra está desactivado. Desactiva «Sin asistente» para pedir cambios con texto libre.",
    ),
  ).toBeVisible();
  // Both agent reviews (plan and default-policy comparison) have answered.
  await expect.poll(agentRunsDone).toBe(2);
});

test("«Aplicar a toda la lista» recalculates every line for any brand", async ({ page }) => {
  await seedStore(page, {
    draftItems: [
      {
        id: "line-1",
        text: "Leche entera Pascual 1L",
        categoryKey: "leche-entera",
        categoryName: "Leche entera",
        productId: 101,
        quantity: "2",
        unit: "ud",
        brand: "Pascual",
        privateLabelOk: true,
        accept: "exact",
        locked: false,
        exactOnly: false,
      },
    ],
  });
  const withFlex: Recommendation = {
    ...baseRecommendation,
    flex_savings: { total: "0.85", lines: [{ line_id: 0, savings: "0.85" }] },
  };
  const bodies = await mockRecommendations(page, withFlex);
  const agentRunsDone = countAgentRunResponses(page);

  await calculatePlan(page);

  // The banner and the line note both show the possible saving.
  await expect(page.getByText(/Con cualquier marca ahorrarías 0,85\s*€\./)).toBeVisible();
  await expect(page.getByText(/0,85\s*€ menos con cualquier marca/)).toBeVisible();

  await page.getByRole("button", { name: "Aplicar a toda la lista" }).click();

  await expect.poll(() => bodies.length).toBe(2);
  const first = (bodies[0] as { items: Record<string, unknown>[] }).items[0];
  const second = (bodies[1] as { items: Record<string, unknown>[] }).items[0];
  expect(first).toMatchObject({ product_id: 101, accept: "exact" });
  expect(second).toMatchObject({ product_id: 101, accept: "equivalent" });
  // The agent review of the recalculated plan has answered too.
  await expect.poll(agentRunsDone).toBe(2);
});

test("«Cambiar» opens a native dialog, warns about other chains and applies the choice", async ({
  page,
}) => {
  await seedStore(page, { draftItems: [lecheDraftItem()] });
  const bodies = await mockRecommendations(page, baseRecommendation);
  const agentRunsDone = countAgentRunResponses(page);

  const detail: CanonicalDetail = {
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
    exact_only: false,
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
        canonical: {
          id: 201,
          name: "Leche entera",
          category_key: "leche-entera",
          category_name: "Leche entera",
          exact_only: false,
        },
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
        canonical: {
          id: 201,
          name: "Leche entera",
          category_key: "leche-entera",
          category_name: "Leche entera",
          exact_only: false,
        },
      },
    ],
  };
  await mockJson(page, "**/api/canonicals/201", detail);

  const diaMilk: Product = {
    id: 2,
    name: "Leche entera Dia 1L",
    brand: "Dia",
    private_label: true,
    packaging: "Botella 1 L",
    image_url: null,
    chain: "Dia",
    price: "1.09",
    unit_price: "1.09",
    base_unit: "l",
    base_quantity: "1",
    // Another canonical of the same category: «Otras opciones parecidas» excludes the
    // products of the canonical being changed, so this one only shows there.
    canonical: {
      id: 202,
      name: "Leche entera Dia",
      category_key: "leche-entera",
      category_name: "Leche entera",
      exact_only: false,
    },
  };
  await page.route("**/api/products**", (route) => {
    const url = new URL(route.request().url());
    const items = url.searchParams.get("category") === "leche-entera" ? [diaMilk] : [];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items, total: items.length, page: 1, size: 24 }),
    });
  });

  await calculatePlan(page);

  // The line's «Cambiar» opens a native <dialog>, never a window.prompt.
  await page.getByRole("button", { name: "Cambiar", exact: true }).click();
  expect(await isOpenNativeDialog(page)).toBe(true);
  await expect(page.getByRole("heading", { name: "Cambiar: Leche entera" })).toBeVisible();
  // The product already in the plan is marked as such.
  await expect(page.getByText("En tu plan actual")).toBeVisible();

  // The second tab widens the choice to the same category, warning about other chains.
  await page.getByRole("button", { name: "Otras opciones parecidas" }).click();
  const diaOption = page.getByRole("button", { name: /Leche entera Dia 1L/ });
  await expect(diaOption).toBeVisible();
  await expect(
    page.getByText("Otra cadena: puede añadir o cambiar tiendas en tu plan"),
  ).toBeVisible();

  await diaOption.click();

  // Choosing an option closes the dialog and recalculates the plan with it.
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect.poll(() => bodies.length).toBe(2);
  const second = (bodies[1] as { items: Record<string, unknown>[] }).items[0];
  expect(second).toMatchObject({ product_id: 2, accept: "exact" });
  // The agent review of the recalculated plan has answered too.
  await expect.poll(agentRunsDone).toBe(2);
});

test("Ajustes changes the theme, keeps the dietary toggles and exports and imports the profile", async ({
  page,
}) => {
  await seedStore(page);
  await page.goto("/#/lista");

  await page.getByRole("button", { name: "Ajustes" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await isOpenNativeDialog(page)).toBe(true);

  // The theme selector drives <meta name="color-scheme">.
  const metaContent = () =>
    page.evaluate(
      () =>
        (document.querySelector('meta[name="color-scheme"]') as HTMLMetaElement | null)
          ?.content ?? "",
    );
  await page.getByRole("button", { name: "Oscuro", exact: true }).click();
  await expect.poll(metaContent).toBe("dark");
  await page.getByRole("button", { name: "Claro", exact: true }).click();
  await expect.poll(metaContent).toBe("light");
  await page.getByRole("button", { name: "Sistema", exact: true }).click();
  await expect.poll(metaContent).toBe("light dark");

  // «Sistema» follows the OS: the dark preference renders the dark canvas.
  const canvasColor = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(canvasColor).toBe("rgb(13, 17, 23)");
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(canvasColor).toBe("rgb(247, 248, 250)");

  // FR-42: the dietary toggles reach the browser profile.
  const sinGluten = page.getByRole("checkbox", { name: "Sin gluten" });
  await sinGluten.check();
  await expect(sinGluten).toBeChecked();
  await expect.poll(() => profileHas(page, "sin_gluten")).toBe(true);

  // Export downloads the profile as JSON.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Exportar preferencias (JSON)" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("smart-basket-preferencias.json");

  // Import: a profile that carries the lactose rule turns its toggle on.
  const sinLactosa = page.getByRole("checkbox", { name: "Sin lactosa" });
  await expect(sinLactosa).not.toBeChecked();
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "preferencias.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        schema_version: 1,
        preferences: [
          {
            id: "pref-1",
            scope_kind: "global",
            scope_key: "sin_lactosa",
            kind: "dietary_rule",
            value: "sin_lactosa",
            origin: "imported",
            consent_ref: null,
            created_at: "2026-11-01T10:00:00.000Z",
            updated_at: "2026-11-01T10:00:00.000Z",
            deleted_at: null,
          },
        ],
        events: [],
      }),
    ),
  });
  await expect(page.getByText("Preferencias importadas.")).toBeVisible();
  await expect(sinLactosa).toBeChecked();

  // Escape closes the native dialog.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("saved lists live in a native dialog and the list survives a reload (M12)", async ({
  page,
}) => {
  await seedStore(page);
  await mockJson(page, "**/api/interpret", interpretResolved);
  await page.goto("/#/lista");

  // One line from the interpreted text, plus a line still being written.
  await page.getByRole("textbox", { name: "Escribe tu lista" }).fill("2 l de leche");
  await page.getByRole("button", { name: "Añadir a la lista", exact: true }).click();
  await expect(page.getByText("Leche entera", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Escribe tu lista" }).fill("pan");

  // A reload keeps both the unified list and the text (M12).
  await page.reload();
  await expect(page.getByText("Leche entera", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Escribe tu lista" })).toHaveValue("pan");

  // Saving goes through the native dialog, with no window.prompt anywhere.
  await page.getByRole("button", { name: "Listas guardadas" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await isOpenNativeDialog(page)).toBe(true);

  await dialog.getByLabel("Nombre de la lista").fill("Compra semanal");
  await dialog.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(page.getByText("Lista guardada.")).toBeVisible();
  // The closed drawer also renders its own copy of the dialog, so scope to the open one.
  await expect(dialog.getByText("Compra semanal")).toBeVisible();
  await expect(dialog.getByText("1 producto")).toBeVisible();

  // Renaming, inline in the same dialog.
  await dialog.getByRole("button", { name: "Renombrar" }).click();
  const renameInput = dialog.getByLabel("Nuevo nombre de Compra semanal");
  await renameInput.fill("Compra del lunes");
  await renameInput.locator("xpath=ancestor::form").getByRole("button", { name: "Guardar" }).click();
  await expect(dialog.getByText("Compra del lunes")).toBeVisible();

  // Deleting asks for confirmation inline.
  await dialog.getByRole("button", { name: "Borrar" }).click();
  await dialog.getByRole("button", { name: "Sí, borrar" }).click();
  await expect(dialog.getByText("Todavía no has guardado ninguna lista.")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("product back restores the filtered catalog URL and overlays close with Esc and Back", async ({
  page,
}) => {
  const catalogUrl = /#\/catalogo\/lacteos\?vista=super&orden=price$/;
  const milk: Product = {
    id: 2,
    name: "Leche entera 1 L",
    brand: "Dia",
    private_label: true,
    packaging: "Botella 1 L",
    image_url: null,
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
      exact_only: false,
    },
  };
  await page.route("**/api/products**", (route) => {
    const url = new URL(route.request().url());
    // The product page asks for the detail shape, the catalog for the page shape.
    if (/\/api\/products\/\d+$/.test(url.pathname)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...milk, alternatives: [] }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [milk], total: 1, page: 1, size: 24 }),
    });
  });

  // A4: «Volver al catálogo» returns to the exact URL, filters included.
  await page.goto("/#/catalogo/lacteos?vista=super&orden=price");
  // The card links the photo and the name to the same product page.
  await page.getByRole("link", { name: milk.name }).first().click();
  await expect(page).toHaveURL(/#\/producto\/2$/);
  await page.getByRole("link", { name: "← Volver al catálogo" }).click();
  await expect(page).toHaveURL(catalogUrl);

  // B3: Escape closes the native Ajustes dialog and returns the focus.
  await page.getByRole("button", { name: "Ajustes" }).click();
  const preferences = page.getByRole("dialog");
  await expect(preferences).toBeVisible();
  await expect(page.getByRole("button", { name: "Cerrar", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(preferences).toBeHidden();
  await expect(page.getByRole("button", { name: "Ajustes" })).toBeFocused();

  // B3: the Back button closes an open overlay instead of leaving the app.
  const listButton = page.getByRole("button", { name: /^Tu lista \d+$/ });
  await listButton.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await page.goBack();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(catalogUrl);

  // Escape closes the overlay too, and the focus comes back to its button.
  await listButton.click();
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(listButton).toBeFocused();
});

test("the plan map draws the route as a Leaflet polyline", async ({ page }) => {
  await seedStore(page, { draftItems: [lecheDraftItem()] });
  await mockRecommendations(page, baseRecommendation);
  const agentRunsDone = countAgentRunResponses(page);

  await calculatePlan(page);

  // The mocked route has two points, so the plan draws one interactive path.
  await expect(page.locator(".map path.leaflet-interactive")).toHaveCount(1);
  await expect.poll(agentRunsDone).toBe(1);
});

const MOBILE_SCREENS: { width: number; height: number }[] = [
  { width: 375, height: 812 },
  { width: 390, height: 844 },
];

for (const viewport of MOBILE_SCREENS) {
  test(`no horizontal overflow on any screen at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await seedStore(page, { draftItems: [lecheDraftItem()] });
    // The last plan lives in the tab session, so #/cesta renders without a new request.
    await page.addInitScript(
      (plan) => {
        sessionStorage.setItem(
          "smart-basket.last-plan",
          JSON.stringify({
            recommendation: plan.recommendation,
            agentRun: plan.agentRun,
            savedAt: new Date().toISOString(),
          }),
        );
      },
      { recommendation: baseRecommendation, agentRun: agentRun() },
    );

    const screens: [string, string][] = [
      ["/", "Tu compra más barata en León"],
      ["/#/catalogo", "Catálogo"],
      ["/#/lista", "Tu lista"],
      ["/#/cesta", "Tu plan de compra"],
    ];
    for (const [hash, heading] of screens) {
      await page.goto(hash);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expectNoHorizontalOverflow(page);
    }
  });
}
