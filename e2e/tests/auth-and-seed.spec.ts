import { expect, test } from "@playwright/test";

import { loginAs } from "../fixtures/oidc-mock";
import { seedFlows } from "../fixtures/seed-flows";

/**
 * Minimum-viable E2E: the mock-session + seed helpers plug in. Deeper UI
 * specs (golden-path, role-gating) activate against the live stack with
 * MOCK_SESSION=1; group-rollup, unknown-user-strand, and accessibility
 * blocks remain skipped pending UI features that aren't yet wired.
 */

test("mock-session login mints a session cookie", async ({ page }) => {
  await loginAs(page, "alice@example.com", ["viewer"]);
  const cookies = await page.context().cookies();
  const names = new Set(cookies.map((c) => c.name));
  expect(names.has("session")).toBe(true);
  expect(names.has("csrf_token")).toBe(true);
});

test("seed route publishes without errors", async ({ request }) => {
  await seedFlows(request, {
    ts: new Date().toISOString(),
    window_s: 5,
    nodes_left: [],
    nodes_right: [],
    links: [],
  });
});

// -------- Activated UI specs --------

const goldenDelta = () => ({
  ts: new Date().toISOString(),
  window_s: 5,
  nodes_left: [{ id: "g:eng", label: "Engineering", size: 10 }],
  nodes_right: [{ id: "app:m365", label: "Microsoft 365", kind: "saas" }],
  links: [
    {
      src: "g:eng",
      dst: "app:m365",
      bytes: 1_000_000,
      flows: 10,
      users: 5,
    },
  ],
  lossy: false,
  dropped_count: 0,
});

test.describe("golden path", () => {
  test("login → Sankey → click link → details pane → override visible", async ({
    page,
    request,
  }) => {
    // 1. Login as editor (also viewer).
    await loginAs(page, "alice@example.com", ["editor", "viewer"]);

    // 2. Load the SPA.
    await page.goto("/");

    // 3. Sankey container renders.
    await expect(page.getByTestId("sankey-canvas")).toBeVisible({
      timeout: 5_000,
    });

    // 4. Seed a deterministic delta. The WS fanout pushes it to the page.
    await seedFlows(request, goldenDelta());

    // 5. Wait for at least one rendered link, then click it.
    const link = page.getByTestId("sankey-link").first();
    await expect(link).toBeVisible({ timeout: 10_000 });
    await link.click();

    // 6. Details pane shows the bytes/flows headline.
    const details = page.getByTestId("details-pane");
    await expect(details).toContainText(/1,?000,?000/);
    await expect(details).toContainText(/10\s+flows/i);

    // 7. Editor sees the Override label button.
    await expect(
      page.getByRole("button", { name: /override label/i }),
    ).toBeVisible();
  });
});

test.describe("role gates", () => {
  test("viewer cannot see Override label button", async ({ page, request }) => {
    await loginAs(page, "viewer@example.com", ["viewer"]);
    await page.goto("/");
    await expect(page.getByTestId("sankey-canvas")).toBeVisible({
      timeout: 5_000,
    });

    await seedFlows(request, goldenDelta());

    const link = page.getByTestId("sankey-link").first();
    await expect(link).toBeVisible({ timeout: 10_000 });
    await link.click();

    const details = page.getByTestId("details-pane");
    await expect(details).toContainText(/1,?000,?000/);
    await expect(details).toContainText(/10\s+flows/i);

    await expect(
      page.getByRole("button", { name: /override label/i }),
    ).toHaveCount(0);
  });

  test("editor sees Override label button", async ({ page, request }) => {
    await loginAs(page, "editor@example.com", ["editor", "viewer"]);
    await page.goto("/");
    await expect(page.getByTestId("sankey-canvas")).toBeVisible({
      timeout: 5_000,
    });

    await seedFlows(request, goldenDelta());

    const link = page.getByTestId("sankey-link").first();
    await expect(link).toBeVisible({ timeout: 10_000 });
    await link.click();

    const details = page.getByTestId("details-pane");
    await expect(details).toContainText(/1,?000,?000/);
    await expect(details).toContainText(/10\s+flows/i);

    await expect(
      page.getByRole("button", { name: /override label/i }),
    ).toBeVisible();
  });
});

// -------- Still-deferred UI specs --------

test.describe.skip("group rollup", () => {
  test("toggle group / user / src_ip mode + member list modal", async () => {
    // See plan Task 5.4. Awaiting group-node click handler wiring.
  });
});

test.describe.skip("unknown-user strand", () => {
  test("amber strand + banner when unknown_ratio high", async () => {
    // See plan Task 5.5. Awaiting sustained-window banner timing logic.
  });
});

test.describe.skip("accessibility", () => {
  test("axe-core WCAG AA scan on every main page", async () => {
    // See plan Task 5.6. Uses @axe-core/playwright (already in devDependencies).
  });
});
