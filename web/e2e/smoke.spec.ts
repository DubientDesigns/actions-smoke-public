import { expect, test, type Page } from "@playwright/test";

const PAGES = ["/", "/discoveries", "/tokens", "/presales", "/influencers", "/wallets", "/security", "/research", "/paper", "/performance", "/alerts", "/system", "/settings"];
const production = Boolean(process.env.BASE_URL);

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page scrolls horizontally").toBeLessThanOrEqual(1);
}

test("login page renders and fits the viewport", async ({ page }) => {
  const res = await page.goto("/login");
  expect(res?.status()).toBe(200);
  await expect(page.getByText("CRYPTO INTELLIGENCE TERMINAL")).toBeVisible();
  await expect(page.getByText(/no sign-up/i)).toBeVisible();
  await noHorizontalScroll(page);
});

test("every dashboard page requires sign-in", async ({ page }) => {
  for (const path of PAGES) {
    await page.goto(path);
    await expect(page, `${path} should redirect to /login`).toHaveURL(/\/login/);
  }
});

test("open redirects are refused", async ({ page }) => {
  await page.goto("/login?next=//evil.example");
  await expect(page).toHaveURL(/\/login/);
});

test("no server secrets or framework banner reach the browser", async ({ page, request }) => {
  const res = await request.get("/login");
  expect(res.headers()["x-powered-by"]).toBeUndefined();
  const scripts: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/_next/static/") && r.url().endsWith(".js")) scripts.push(await r.text());
  });
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  const all = scripts.join("\n");
  for (const marker of ["CIT_INTERNAL_API_TOKEN", "CIT_DATABASE_URL", "service_role", "CIT_ANTHROPIC_API_KEY", "CIT_TELEGRAM_BOT_TOKEN"]) {
    expect(all, `client bundle mentions ${marker}`).not.toContain(marker);
  }
});

test("production security headers", async ({ request }) => {
  test.skip(!production || !process.env.BASE_URL?.startsWith("https://"), "only against the deployed HTTPS site");
  const h = (await request.get("/login")).headers();
  expect(h["strict-transport-security"]).toContain("max-age=");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
});

test("signed-in walkthrough of every page", async ({ page }) => {
  const email = process.env.E2E_EMAIL;
  const password = process.env.E2E_PASSWORD;
  test.skip(!production || !email || !password, "needs BASE_URL + E2E_EMAIL/E2E_PASSWORD of an allowlisted user");
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill(email!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  for (const path of PAGES) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBeLessThan(400);
    await expect(page.locator("h1").first(), `${path} has a heading`).toBeVisible();
    await expect(page.getByText(/Application error|Internal Server Error/i)).toHaveCount(0);
    await expect(page.getByText("Account not allowlisted")).toHaveCount(0);
    await noHorizontalScroll(page);
  }
});
