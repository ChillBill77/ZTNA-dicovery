import { act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SankeyDelta } from "../api/types";
import { useLiveStore } from "../store/liveStore";

const delta = (overrides: Partial<SankeyDelta> = {}): SankeyDelta => ({
  ts: new Date().toISOString(), window_s: 5,
  nodes_left: [], nodes_right: [], links: [],
  lossy: false, dropped_count: 0, ...overrides,
});

describe("liveStore", () => {
  it("stores latest delta", () => {
    act(() => useLiveStore.getState().setDelta(delta({ window_s: 5 })));
    expect(useLiveStore.getState().latest?.window_s).toBe(5);
  });

  it("freshness seconds computed from ts", () => {
    const past = new Date(Date.now() - 3000).toISOString();
    act(() => useLiveStore.getState().setDelta(delta({ ts: past })));
    const secs = useLiveStore.getState().secondsBehind();
    expect(secs).toBeGreaterThanOrEqual(2);
  });

  it("lossy flag surfaces", () => {
    act(() => useLiveStore.getState().setDelta(delta({ lossy: true, dropped_count: 10 })));
    expect(useLiveStore.getState().latest?.lossy).toBe(true);
  });
});
