import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("anonymous transaction access", () => {
  for (const path of [
    "/transactions/",
    "/transactions/new/",
    "/transactions/1/",
    "/transactions/import/",
  ]) {
    test(`${path} requires sign in and preserves a local return target`, async ({ page }) => {
      await page.goto(path);

      await expect(page).toHaveURL((url) => {
        return url.pathname === "/login/" && url.searchParams.get("next") === path;
      });
      await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();

      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations).toEqual([]);
    });
  }
});

test.describe("transaction access without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("keeps authentication available after an anonymous transaction request", async ({
    page,
  }) => {
    await page.goto("/transactions/");

    await expect(page.getByRole("textbox", { name: "Email" })).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
