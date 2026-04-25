import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import UnknownStrandBanner from "../components/UnknownStrandBanner";

function wrap({ children }: { children: ReactNode }): JSX.Element {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => vi.unstubAllGlobals());

describe("UnknownStrandBanner", () => {
  it("hides when ratio is below threshold", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ unknown_user_ratio: 0.2 }),
      }),
    );
    render(<UnknownStrandBanner />, { wrapper: wrap });
    // Give react-query a tick to resolve.
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("unknown-banner")).toBeNull();
  });

  it("shows alert when ratio crosses threshold", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ unknown_user_ratio: 0.6 }),
      }),
    );
    render(<UnknownStrandBanner />, { wrapper: wrap });
    await waitFor(() =>
      expect(screen.getByTestId("unknown-banner")).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/identity coverage/i);
    expect(screen.getByRole("alert")).toHaveTextContent("60%");
  });
});
