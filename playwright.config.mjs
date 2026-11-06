// End-to-end tests of the viewer (site/), on a small history built from
// tests/fixtures/site_history.json (a slice of mevzuat-tarihce).
import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const PYTHON = process.env.PYTHON || "python";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  fullyParallel: true,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}/`, locale: "tr-TR", timezoneId: "Europe/Istanbul" },
  projects: [
    { name: "masaüstü", use: { ...devices["Desktop Chrome"] } },
    { name: "mobil", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `${PYTHON} tests/site_fixture.py build/e2e && ${PYTHON} -m http.server ${PORT} --bind 127.0.0.1 -d build/e2e/www`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "ignore",
  },
});
