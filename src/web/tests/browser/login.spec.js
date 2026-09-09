import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const stylesheetResponse = page.waitForResponse((response) =>
    response.url().endsWith("/static/css/app.css"),
  );
  await page.goto("/login/");
  const response = await stylesheetResponse;
  expect(response.ok()).toBe(true);
  expect(response.status()).toBe(200);
});

test("renders an accessible email and password form", async ({ page }) => {
  await expect(page).toHaveTitle("Sign in | Penni More");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();

  const email = page.getByRole("textbox", { name: "Email" });
  const password = page.getByLabel("Password");
  const submit = page.getByRole("button", { name: "Sign in" });

  await expect(email).toHaveAttribute("type", "email");
  await expect(email).toHaveAttribute("autocomplete", "email");
  await expect(password).toHaveAttribute("type", "password");
  await expect(password).toHaveAttribute("autocomplete", "current-password");
  await expect(submit).toBeVisible();
  await expect(page.locator('form[action="/login/"]')).toHaveAttribute("method", "post");
  await expect(page.locator('input[name="csrfmiddlewaretoken"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /register|recover|reset/i })).toHaveCount(0);
});

test("uses a sensible keyboard focus order and visible focus treatment", async ({ page }) => {
  await page.keyboard.press("Tab");

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await skipLink.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "Email" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();

  const outlineStyle = await page
    .getByRole("button", { name: "Sign in" })
    .evaluate((button) => getComputedStyle(button).outlineStyle);
  expect(outlineStyle).not.toBe("none");
});

test("has no horizontal overflow at the configured viewport", async ({ page }) => {
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );

  expect(hasHorizontalOverflow).toBe(false);
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  const results = await new AxeBuilder({ page }).analyze();

  expect(results.violations).toEqual([]);
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("keeps the core sign-in form available", async ({ page }) => {
    await expect(page.getByRole("textbox", { name: "Email" })).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
