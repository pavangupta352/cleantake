import { defineConfig, devices } from "@playwright/test";
const packaged = process.env.CLEANTAKE_PACKAGED === "1";
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL: packaged ? "http://127.0.0.1:8765" : "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: [
    {
      command: "uv run python e2e/server.py",
      url: "http://127.0.0.1:8765/api/health",
      timeout: 60_000,
      reuseExistingServer: false,
    },
    ...(!packaged ? [{
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    }] : []),
  ],
});
