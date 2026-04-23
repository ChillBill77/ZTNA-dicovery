import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import OverrideModal from "../components/OverrideModal";
import { useDetailsStore } from "../store/detailsStore";

describe("OverrideModal", () => {
  it("posts to /api/applications and closes", async () => {
    useDetailsStore.setState({
      selectedLink: {
        src: "ip:10.0.0.1", dst: "app:M365", bytes: 1, flows: 1, users: 0,
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 201 })
    );
    vi.stubGlobal("fetch", fetchMock);
    const onClose = vi.fn();
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <OverrideModal onClose={onClose} />
      </QueryClientProvider>
    );
    await userEvent.clear(screen.getByLabelText(/Destination CIDR/i));
    await userEvent.type(screen.getByLabelText(/Destination CIDR/i), "10.100.0.0/16");
    await userEvent.click(screen.getByRole("button", { name: /Save/i }));
    expect(fetchMock).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
