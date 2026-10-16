import { defineConfig, devices } from "@playwright/test";

// E2E contra los servicios reales (backend FastAPI + frontend Next.js). Si ya están en marcha se reutilizan.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: "../output/e2e-results",
  use: {
    baseURL: "http://localhost:3000",
    acceptDownloads: true,
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: "cd ../backend && .venv/bin/python -m app",
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "npx next dev --hostname localhost --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
