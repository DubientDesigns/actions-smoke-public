import { defineConfig, devices } from "@playwright/test";

// Smoke tests. Two modes:
//  * local / CI (no BASE_URL): starts the standalone server from the existing build
//    without Supabase configuration, which must fail closed (everything -> /login).
//  * production: BASE_URL=https://your-domain npx playwright test
//    Optional E2E_EMAIL / E2E_PASSWORD (an allowlisted user) also walks every page.
const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:3100";
const local = !process.env.BASE_URL;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "off",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: local
    ? {
        // Same standalone server as the Docker image (needs a prior `npm run build`).
        command:
          "cp -r .next/static .next/standalone/.next/ && cp -r public .next/standalone/ && node .next/standalone/server.js",
        url: "http://127.0.0.1:3100/login",
        reuseExistingServer: false,
        timeout: 60_000,
        env: { PORT: "3100", HOSTNAME: "127.0.0.1", NEXT_PUBLIC_SUPABASE_URL: "", NEXT_PUBLIC_SUPABASE_ANON_KEY: "" },
      }
    : undefined,
});
