import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FreshnessBanner from "../components/FreshnessBanner";
import { useLiveStore } from "../store/liveStore";

describe("FreshnessBanner", () => {
  it("renders live + seconds behind when fresh", () => {
    useLiveStore.setState({
      latest: {
        ts: new Date(Date.now() - 2_000).toISOString(),
        window_s: 5, nodes_left: [], nodes_right: [],
        links: [], lossy: false, dropped_count: 0,
      },
      status: "open",
    });
    render(<FreshnessBanner />);
    expect(screen.getByTestId("freshness")).toHaveTextContent(/Live/);
    expect(screen.getByTestId("freshness")).toHaveTextContent(/2s/);
    expect(screen.getByTestId("freshness").className).toMatch(/green/);
  });

  it("amber when lossy", () => {
    useLiveStore.setState({
      latest: {
        ts: new Date().toISOString(), window_s: 5,
        nodes_left: [], nodes_right: [],
        links: [], lossy: true, dropped_count: 3,
      },
      status: "open",
    });
    render(<FreshnessBanner />);
    expect(screen.getByTestId("freshness").className).toMatch(/amber/);
  });
});
