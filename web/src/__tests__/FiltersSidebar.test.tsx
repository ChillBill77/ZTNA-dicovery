import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import FiltersSidebar from "../components/FiltersSidebar";
import { useFilterStore } from "../store/filterStore";

describe("FiltersSidebar", () => {
  it("updates src_cidr in store", async () => {
    render(<FiltersSidebar />);
    await userEvent.type(screen.getByLabelText("source-cidr"), "10.0.0.0/8");
    expect(useFilterStore.getState().src_cidr).toBe("10.0.0.0/8");
  });
});
