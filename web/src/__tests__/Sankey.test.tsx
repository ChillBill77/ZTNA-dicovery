import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Sankey from "../components/Sankey";
import { useLiveStore } from "../store/liveStore";

describe("Sankey", () => {
  it("renders empty-state message when no delta", () => {
    useLiveStore.setState({ latest: null, status: "open" });
    render(<Sankey />);
    expect(screen.getByText(/awaiting flows/i)).toBeInTheDocument();
  });

  it("renders SVG with link paths when small delta present", () => {
    useLiveStore.setState({
      latest: {
        ts: new Date().toISOString(), window_s: 5,
        nodes_left: [{ id: "ip:10.0.0.1", label: "10.0.0.1", size: 1 }],
        nodes_right: [{ id: "app:M365", label: "M365", kind: "saas" }],
        links: [{ src: "ip:10.0.0.1", dst: "app:M365", bytes: 1000, flows: 10, users: 0 }],
        lossy: false, dropped_count: 0,
      },
      status: "open",
    });
    const { container } = render(<Sankey />);
    expect(container.querySelectorAll("path.sankey-link").length).toBe(1);
  });

  it("switches to canvas fallback above 500 links", () => {
    const many = Array.from({ length: 501 }, (_, i) => ({
      src: `ip:10.0.0.${i % 250}`, dst: `app:app${i % 10}`,
      bytes: 100, flows: 1, users: 0,
    }));
    useLiveStore.setState({
      latest: {
        ts: new Date().toISOString(), window_s: 5,
        nodes_left: [], nodes_right: [], links: many,
        lossy: false, dropped_count: 0, truncated: false, total_links: many.length,
      },
      status: "open",
    });
    const { container } = render(<Sankey />);
    expect(container.querySelector("canvas")).not.toBeNull();
  });
});
