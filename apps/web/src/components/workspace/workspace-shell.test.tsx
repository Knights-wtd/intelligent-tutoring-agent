import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkspaceShell", () => {
  it("keeps spaces in the far-left rail and content in the second pane", () => {
    render(<WorkspaceShell />);

    const rail = screen.getByLabelText("空间切换");
    const tree = screen.getByLabelText("当前空间内容");
    expect(rail).toHaveTextContent("个人空间");
    expect(rail).toHaveTextContent("七年级数学");
    expect(tree).toHaveTextContent("教材与练习");
    expect(tree).toHaveTextContent("知识图谱");
    expect(tree).not.toHaveTextContent("个人空间");
  });

  it("uses ordinary pressed buttons for placeholder content views", () => {
    render(<WorkspaceShell />);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "知识图谱" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "教材原页" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("renders three keyboard-resizable content panes", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(400);
    render(<WorkspaceShell />);
    expect(screen.getByLabelText("当前空间内容")).toBeInTheDocument();
    expect(screen.getByLabelText("知识工作区")).toBeInTheDocument();
    expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();

    const separators = screen.getAllByRole("separator");
    expect(separators).toHaveLength(2);

    const firstSeparator = separators[0];
    expect(firstSeparator).toHaveAttribute("tabindex", "0");
    expect(firstSeparator).toHaveAttribute("aria-valuemin");
    expect(firstSeparator).toHaveAttribute("aria-valuemax");
    expect(firstSeparator).toHaveAttribute("aria-valuenow");

    const initialValue = Number(firstSeparator.getAttribute("aria-valuenow"));
    firstSeparator.focus();
    await user.keyboard("{ArrowRight}");

    expect(Number(firstSeparator.getAttribute("aria-valuenow"))).toBeGreaterThan(initialValue);
  });
});
