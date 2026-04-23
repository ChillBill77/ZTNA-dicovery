import type { APIRequestContext } from "@playwright/test";

/**
 * Publish a synthetic SankeyDelta to Redis `sankey.live` via the test-only
 * route, bypassing the ingest → correlator pipeline. The api must be started
 * with `MOCK_SESSION=1` to expose this endpoint.
 */
export async function seedFlows(
  req: APIRequestContext,
  delta: unknown,
): Promise<void> {
  await req.post("/api/test/seed", { data: delta, failOnStatusCode: true });
}
