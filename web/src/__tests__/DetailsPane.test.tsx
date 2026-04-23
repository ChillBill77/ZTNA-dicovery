import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DetailsPane from "../components/DetailsPane";
import { useDetailsStore } from "../store/detailsStore";

function withQC(children: React.ReactNode) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("DetailsPane", () => {
  it("shows prompt when no link selected", () => {
    useDetailsStore.setState({ selectedLink: null, overrideOpen: false });
    render(withQC(<DetailsPane />));
    expect(screen.getByText(/Click a link/i)).toBeInTheDocument();
  });

  it("renders bytes and flows when link selected", () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    useDetailsStore.setState({
      selectedLink: { src: "ip:10.0.0.1", dst: "app:M365", bytes: 1000, flows: 3, users: 0 },
      overrideOpen: false,
    });
    render(withQC(<DetailsPane />));
    expect(screen.getByText(/bytes/i)).toBeInTheDocument();
  });
});
