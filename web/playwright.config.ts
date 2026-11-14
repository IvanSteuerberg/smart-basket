import { defineConfig, devices } from "@playwright/test";

// E2E_PORT lets two checkouts run their mocked suites at the same time.
const port = Number(process.env.E2E_PORT ?? 5174);

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  // The live-stack suite has its own config (playwright.real.config.ts).
  testIgnore: "**/real/**",
  forbidOnly: !!process.env.CI,
  retries: 0,
  use: {
    baseURL: `http://localhost:${port}`,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
  },
});
