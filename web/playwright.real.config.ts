import { defineConfig, devices } from "@playwright/test";

// End-to-end suite against the real stack; the orchestrator starts it and sets E2E_BASE_URL.
export default defineConfig({
  testDir: "e2e/real",
  testMatch: "**/*.e2e.ts",
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8080",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
