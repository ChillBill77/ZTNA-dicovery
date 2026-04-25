import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DetailsPane from "../components/DetailsPane";
import { useDetailsStore } from "../store/detailsStore";

function withQC(children: React.ReactNode) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function wrap({ children }: { children: ReactNode }): JSX.Element {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Mock fetch so /api/auth/me returns the given roles and /api/flows/raw
 *  resolves to an empty list. Other URLs fall through to a 404. */
function mockFetchWithRoles(roles: Array<"viewer" | "editor" | "admin">) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/auth/me")) {
      return new Response(
        JSON.stringify({ user_upn: "alice@example.com", roles }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/api/flows/raw")) {
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

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

  it("hides Override label button for viewer role", async () => {
    mockFetchWithRoles(["viewer"]);
    useDetailsStore.setState({
      selectedLink: { src: "ip:10.0.0.1", dst: "app:M365", bytes: 1000, flows: 3, users: 0 },
      overrideOpen: false,
    });
    render(<DetailsPane />, { wrapper: wrap });

    // Wait for the link tab to render the headline before asserting absence.
    await waitFor(() =>
      expect(screen.getByText(/bytes/i)).toBeInTheDocument(),
    );
    // Give react-query a tick so /api/auth/me resolves.
    await new Promise((r) => setTimeout(r, 20));
    expect(
      screen.queryByRole("button", { name: /override label/i }),
    ).toBeNull();
  });

  it("shows Override label button for editor role and clicking calls openOverride", async () => {
    mockFetchWithRoles(["editor"]);
    const openOverrideSpy = vi.fn();
    useDetailsStore.setState({
      selectedLink: { src: "ip:10.0.0.1", dst: "app:M365", bytes: 1000, flows: 3, users: 0 },
      overrideOpen: false,
      openOverride: openOverrideSpy,
    });
    render(<DetailsPane />, { wrapper: wrap });

    const btn = await screen.findByRole("button", { name: /override label/i });
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(openOverrideSpy).toHaveBeenCalledTimes(1);
  });
});
