import { expect, test } from "@playwright/test";

// No mocks: the frontend talks to the live backend, LLM and routing included.
test("full flow against the real backend", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/#/lista");

  // "pollo" is vague: the list asks which one, inline, with photos.
  await page.getByRole("textbox", { name: "Tu lista" }).fill("2 l de leche\npan de molde\npollo");
  const calculate = page.getByRole("button", { name: "Calcular", exact: true });
  await calculate.click();

  // The interpreter may wait for the LLM.
  await expect(page.getByRole("heading", { name: "¿Qué pollo?" })).toBeVisible({
    timeout: 60_000,
  });
  await page.getByRole("button", { name: /Pechuga de pollo/ }).click();

  // Without a remembered origin the origin row opens; the map has no accessible role.
  await calculate.click();
  await page.locator(".map").click();
  await calculate.click();

  // Routing and the optimizer may take a few seconds.
  await expect(page.getByRole("heading", { name: "Tu cesta" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/^Total: /)).toBeVisible();
  await expect(page.getByText(/pechuga/i).first()).toBeVisible();
  await expect(page.locator(".map path.leaflet-interactive").first()).toBeVisible();
});
