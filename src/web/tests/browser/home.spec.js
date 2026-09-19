import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("redirects unauthenticated visitors to login with a local return target", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login\/\?next=\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
});

test("keeps the anonymous redirect destination accessible and free of overflow", async ({
  page,
}) => {
  await page.goto("/");

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  const results = await new AxeBuilder({ page }).analyze();

  expect(hasHorizontalOverflow).toBe(false);
  expect(results.violations).toEqual([]);
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("keeps authentication available after requesting the dashboard", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/login\/\?next=\/$/);
    await expect(page.getByRole("textbox", { name: "Email" })).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
