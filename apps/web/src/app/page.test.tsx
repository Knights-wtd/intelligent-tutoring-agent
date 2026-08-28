import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "./page";

const mockApi = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  register: vi.fn(),
  spaces: vi.fn(),
  models: vi.fn(),
  billingMe: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("HomePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the login form to an anonymous visitor", async () => {
    mockApi.me.mockResolvedValue(null);

    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });

  it("loads authenticated space summaries into the workspace", async () => {
    const user = userEvent.setup();
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

    await user.click(await screen.findByRole("button", { name: "切换空间" }));
    expect(screen.getByRole("dialog", { name: "切换空间" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "个人空间" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "七年级数学" })).toBeInTheDocument();
  });

  it("opens the workspace after logging in from the anonymous home page", async () => {
    const user = userEvent.setup();
    mockApi.me
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        user: { id: "user-1", email: "learner@example.com", username: "learner" },
        personal_space: { id: "personal", kind: "personal", name: "我的空间" },
      });
    mockApi.login.mockResolvedValue(undefined);
    mockApi.spaces.mockResolvedValue([
      { id: "personal", kind: "personal", name: "我的空间" },
    ]);
    mockApi.models.mockResolvedValue([]);
    mockApi.billingMe.mockResolvedValue({ balance: "0", currency: "CNY", entries: [] });

    render(<HomePage />);

    await user.type(await screen.findByLabelText("邮箱或用户名"), "learner@example.com");
    await user.type(screen.getByLabelText("密码"), "correct horse battery staple 9");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByLabelText("学习工作区")).toBeInTheDocument();
    expect(mockApi.me).toHaveBeenCalledTimes(2);
  });
});
