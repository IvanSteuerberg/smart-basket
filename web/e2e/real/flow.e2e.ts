import { expect, test } from "@playwright/test";

// No mocks: the frontend talks to the live backend, LLM and routing included.
test("full flow against the real backend", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");

  await page
    .getByRole("textbox", { name: "Tu lista de la compra" })
    .fill("2 l de leche\npan de molde\ncolacao");
  await page.getByRole("button", { name: "Interpretar" }).click();

  // The interpreter may wait for the LLM.
  const continueButton = page.getByRole("button", { name: "Continuar" });
  await expect(continueButton).toBeEnabled({ timeout: 60_000 });
  await continueButton.click();

  const calculate = page.getByRole("button", { name: "Calcular cesta" });
  await expect(calculate).toBeDisabled();
  // The map has no accessible role: click its container to pick the origin.
  await page.locator(".map").click();
  await expect(calculate).toBeEnabled();

  const walk = page.getByRole("radio", { name: "A pie" });
  await expect(walk).toBeChecked();

  await calculate.click();

  // Routing and the optimizer may take a few seconds.
  await expect(page.locator(".store-card h3").first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/^Total: /)).toBeVisible();
  await expect(page.locator(".map path.leaflet-interactive").first()).toBeVisible();
});
