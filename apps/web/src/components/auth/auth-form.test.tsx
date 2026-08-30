import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthForm } from "./auth-form";

const mockApi = vi.hoisted(() => ({ login: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("AuthForm", () => {
  it("shows a neutral message when login is rejected", async () => {
    const user = userEvent.setup();
    mockApi.login.mockRejectedValue(new Error("rejected"));
    render(<AuthForm mode="login" />);

    await user.type(screen.getByLabelText("邮箱"), "learner@example.com");
    await user.type(screen.getByLabelText("密码"), "incorrect password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("登录未成功，请检查邮箱和密码后重试。");
  });
});
