import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LeftColumnModeToggle from "../components/LeftColumnModeToggle";

describe("LeftColumnModeToggle", () => {
  it("highlights the active mode", () => {
    render(<LeftColumnModeToggle value="user" onChange={() => {}} />);
    const userBtn = screen.getByTestId("mode-user");
    const groupBtn = screen.getByTestId("mode-group");
    expect(userBtn).toHaveAttribute("aria-checked", "true");
    expect(groupBtn).toHaveAttribute("aria-checked", "false");
  });

  it("invokes onChange with the clicked mode", () => {
    const onChange = vi.fn();
    render(<LeftColumnModeToggle value="group" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("mode-user"));
    expect(onChange).toHaveBeenCalledWith("user");
    fireEvent.click(screen.getByTestId("mode-src_ip"));
    expect(onChange).toHaveBeenCalledWith("src_ip");
  });

  it("renders three options", () => {
    render(<LeftColumnModeToggle value="group" onChange={() => {}} />);
    expect(screen.getByTestId("mode-group")).toBeInTheDocument();
    expect(screen.getByTestId("mode-user")).toBeInTheDocument();
    expect(screen.getByTestId("mode-src_ip")).toBeInTheDocument();
  });
});
