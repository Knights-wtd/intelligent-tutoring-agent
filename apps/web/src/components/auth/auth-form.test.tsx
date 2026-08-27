import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthForm } from "./auth-form";

const mockApi = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("AuthForm", () => {
  it("shows a neutral message when login is rejected", async () => {
    const user = userEvent.setup();
    mockApi.login.mockRejectedValue(new Error("rejected"));
    render(<AuthForm mode="login" />);

    await user.type(screen.getByLabelText("邮箱或用户名"), "learner@example.com");
    await user.type(screen.getByLabelText("密码"), "incorrect password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "登录未成功，请检查邮箱/用户名和密码后重试。",
    );
  });

  it("submits the identifier so login accepts a username too", async () => {
    const user = userEvent.setup();
    mockApi.login.mockResolvedValue(undefined);
    render(<AuthForm mode="login" />);

    await user.type(screen.getByLabelText("邮箱或用户名"), "learner");
    await user.type(screen.getByLabelText("密码"), "correct horse battery staple 9");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await vi.waitFor(() =>
      expect(mockApi.login).toHaveBeenCalledWith({
        identifier: "learner",
        password: "correct horse battery staple 9",
      }),
    );
  });

  it("explains the password requirement before submitting registration", async () => {
    const user = userEvent.setup();
    render(<AuthForm mode="register" />);

    await user.type(screen.getByLabelText("用户名"), "wtd");
    await user.type(screen.getByLabelText("邮箱"), "wtd00005@163.com");
    await user.type(screen.getByLabelText("密码"), "short-pass");
    await user.click(screen.getByRole("button", { name: "注册" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("密码至少需要 12 位。");
    expect(mockApi.register).not.toHaveBeenCalled();
  });
});
