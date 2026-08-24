import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const stylesheetResponse = page.waitForResponse((response) =>
    response.url().endsWith("/static/css/app.css"),
  );
  await page.goto("/");
  const response = await stylesheetResponse;
  expect(response.ok()).toBe(true);
  expect(response.status()).toBe(200);
});

test("renders the responsive application shell", async ({ page }, testInfo) => {
  await expect(page).toHaveTitle("Home | Penni More");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Penni More" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Web GUI is running");

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);

  const mainPadding = await page
    .locator("main")
    .evaluate((main) => getComputedStyle(main).paddingLeft);
  expect(mainPadding).toBe(testInfo.project.name === "desktop-chromium" ? "24px" : "16px");
});

test("keeps the footer at the viewport bottom on a short desktop page", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Desktop short-page assertion");

  const layout = await page.evaluate(() => {
    const bodyStyle = getComputedStyle(document.body);
    const footer = document.querySelector("footer");

    return {
      bodyDisplay: bodyStyle.display,
      bodyFlexDirection: bodyStyle.flexDirection,
      footerBottom: footer?.getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight,
    };
  });

  expect(layout.bodyDisplay).toBe("flex");
  expect(layout.bodyFlexDirection).toBe("column");
  expect(layout.footerBottom).toBe(layout.viewportHeight);
});

test("exposes the skip link to keyboard users", async ({ page }) => {
  await page.keyboard.press("Tab");

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await skipLink.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  const results = await new AxeBuilder({ page }).analyze();

  expect(results.violations).toEqual([]);
});
