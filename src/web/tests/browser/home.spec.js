import { expect, test } from "@playwright/test";

test("redirects unauthenticated visitors to login with a local return target", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login\/\?next=\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
});
