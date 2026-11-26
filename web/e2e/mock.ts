import { test as base, expect, type Page } from "@playwright/test";

export { expect };

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

/** Fail the test when the page scrolls sideways at the current viewport. */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const sizes = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(sizes.scrollWidth, "horizontal overflow on the page").toBeLessThanOrEqual(
    sizes.innerWidth,
  );
}

/**
 * Counts completed agent-run responses, so a test can end only after the fire-and-forget
 * agent review of its last recalculation has answered (no teardown races).
 */
export function countAgentRunResponses(page: Page): () => number {
  let completed = 0;
  page.on("response", (response) => {
    if (response.url().includes("/api/agent/runs")) completed += 1;
  });
  return () => completed;
}

export interface PageGuard {
  /** Problems seen so far: console errors, page errors and unexpected /api failures. */
  readonly problems: string[];
  /** Lets responses matching `pattern` answer 4xx/5xx without failing the test. */
  allowHttpError(pattern: RegExp): void;
}

/**
 * The mocked suites must stay 100 % green: any `console.error`, uncaught page error or
 * unexpected HTTP >= 400 on `/api` fails the test that caused it. Every suite imports this
 * `test` instead of the plain one; the check runs automatically at the end of each test.
 */
export const test = base.extend<{ guard: PageGuard }>({
  guard: [
    async ({ page }, use) => {
      const problems: string[] = [];
      const allowedErrors: RegExp[] = [];
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        // Chromium artifacts: layout observers, and network failures reported again below.
        if (message.text().startsWith("ResizeObserver")) return;
        if (message.text().startsWith("Failed to load resource:")) return;
        problems.push(`console.error: ${message.text()}`);
      });
      page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
      // An aborted /api request is a call without a fixture; name it, unlike the console
      // line. Anything else (e.g. the blocked web font) is not the app's contract.
      page.on("requestfailed", (request) => {
        if (request.failure()?.errorText !== "net::ERR_FAILED") return;
        if (!request.url().includes("/api/")) return;
        problems.push(`requestfailed: ${request.method()} ${request.url()}`);
      });
      page.on("response", (response) => {
        const status = response.status();
        const url = response.url();
        if (status < 400 || !url.includes("/api/")) return;
        if (allowedErrors.some((pattern) => pattern.test(url))) return;
        problems.push(`HTTP ${status}: ${response.request().method()} ${url}`);
      });
      await use({
        problems,
        allowHttpError: (pattern) => {
          allowedErrors.push(pattern);
        },
      });
      expect(problems, "unexpected page problems").toEqual([]);
    },
    { auto: true },
  ],
});
