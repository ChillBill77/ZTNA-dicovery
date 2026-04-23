import type { Page } from "@playwright/test";

/**
 * Mint a session cookie via the test-only POST /api/test/login-as route
 * (available when the api is started with `MOCK_SESSION=1`) and attach it to
 * the Playwright browser context. Bypasses the real OIDC redirect dance.
 */
export async function loginAs(
  page: Page,
  upn: string,
  roles: Array<"viewer" | "editor" | "admin">,
): Promise<void> {
  const r = await page.request.post("/api/test/login-as", {
    data: { upn, roles },
    failOnStatusCode: true,
  });
  const { session, csrf_token } = (await r.json()) as {
    session: string;
    csrf_token: string;
  };
  const base = process.env.APP_URL ?? "https://localhost";
  await page.context().addCookies([
    { name: "session", value: session, url: base },
    { name: "csrf_token", value: csrf_token, url: base },
  ]);
}
