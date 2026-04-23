import { expect, test } from "@playwright/test";

test("sankey renders with at least one link and details pane populates on click", async ({ page }) => {
  await page.goto("/");

  // Sankey container must render within 15 s of page load
  const sankey = page.locator('[data-testid="sankey-canvas"]');
  await expect(sankey).toBeVisible({ timeout: 15_000 });

  // Wait for at least one link to appear
  const link = page.locator('[data-testid="sankey-link"]').first();
  await expect(link).toBeVisible({ timeout: 15_000 });

  // Click the link and verify the details pane populates
  await link.click();
  const details = page.locator('[data-testid="details-pane"]');
  await expect(details).toContainText(/bytes|flows|users/i, { timeout: 5_000 });
});
