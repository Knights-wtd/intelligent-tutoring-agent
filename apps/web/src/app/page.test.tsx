import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "./page";

const mockApi = vi.hoisted(() => ({
  me: vi.fn(),
  spaces: vi.fn(),
  models: vi.fn(),
  billingMe: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("HomePage", () => {
  it("shows the login form to an anonymous visitor", async () => {
    mockApi.me.mockResolvedValue(null);

    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });

  it("loads authenticated space summaries into the workspace", async () => {
    mockApi.me.mockResolvedValue({
      user: { id: "user-1", email: "learner@example.com", username: "learner" },
      personal_space: { id: "personal", kind: "personal", name: "我的空间" },
    });
    mockApi.spaces.mockResolvedValue([
      { id: "personal", kind: "personal", name: "我的空间" },
      { id: "math", kind: "classroom", name: "七年级数学" },
    ]);
    mockApi.models.mockResolvedValue([]);
    mockApi.billingMe.mockResolvedValue({ balance: "0", currency: "CNY", entries: [] });

    render(<HomePage />);

    expect(await screen.findByLabelText("个人空间")).toBeInTheDocument();
    expect(screen.getByLabelText("七年级数学")).toBeInTheDocument();
  });
});
