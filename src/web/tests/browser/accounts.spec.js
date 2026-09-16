import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("anonymous account access", () => {
  for (const path of ["/accounts/", "/accounts/new/", "/accounts/1/"]) {
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
