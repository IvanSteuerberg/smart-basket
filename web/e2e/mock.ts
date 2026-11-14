import type { Page } from "@playwright/test";

export const TRANSPARENT_1X1_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

export async function mockJson(
  page: Page,
  url: string,
  body: unknown,
  status = 200,
): Promise<void> {
  await page.route(url, (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }),
  );
}

/**
 * First block everything that is not the dev server, and any /api call without a
 * fixture, so nothing reaches the network. Routes registered later take precedence.
 */
export async function blockUnmocked(page: Page): Promise<void> {
  await page.route(
    (url) => url.hostname !== "localhost",
    (route) => route.abort(),
  );
  await page.route("**/api/**", (route) => route.abort());
}
