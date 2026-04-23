import { expect, test } from "@playwright/test";

import { loginAs } from "../fixtures/oidc-mock";
import { seedFlows } from "../fixtures/seed-flows";

/**
 * Minimum-viable E2E: the mock-session + seed helpers plug in. Deeper UI
 * specs (golden-path, group-rollup, unknown-user strand, role-gating,
 * accessibility scans) are scaffolded below as `test.describe.skip` blocks;
 * the bodies activate once the P4-followup web login / role-gated components
 * land.
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

// -------- Scaffolded UI specs (bodies deferred to P4-followup) --------

test.describe.skip("golden path", () => {
  test("login → Sankey → click link → override → relabel", async () => {
    // See plan Task 5.2. Requires data-testid hooks on Sankey canvas, links,
    // details pane, and override modal. Wires up after Task 1.9 (web login
    // UI + role-gated OverrideAppButton) lands.
  });
});

test.describe.skip("group rollup", () => {
  test("toggle group / user / src_ip mode + member list modal", async () => {
    // See plan Task 5.4.
  });
});

test.describe.skip("unknown-user strand", () => {
  test("amber strand + banner when unknown_ratio high", async () => {
    // See plan Task 5.5.
  });
});

test.describe.skip("role gates", () => {
  test("viewer hidden override; editor visible; admin reloads adapters", async () => {
    // See plan Task 5.7.
  });
});

test.describe.skip("accessibility", () => {
  test("axe-core WCAG AA scan on every main page", async () => {
    // See plan Task 5.6. Uses @axe-core/playwright (already in devDependencies).
  });
});
