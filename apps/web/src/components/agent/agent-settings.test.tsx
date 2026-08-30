import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AgentSettings,
  FARO_CONTEXT_WINDOW,
  FARO_MODEL,
  FARO_PROVIDER,
} from "./agent-settings";

function settings(overrides: Record<string, unknown> = {}) {
  return {
    provider: "claude",
    model: "fable",
    context_window: 1_000_000,
    permission_mode: "bypassPermissions" as const,
    workspace_roots: ["E:\\项目\\知识库课本", "D:\\资料"],
    mcp_enabled: true,
    skills_enabled: true,
    subagents_enabled: true,
    web_enabled: true,
    ...overrides,
  };
}

describe("AgentSettings", () => {
  it("renders Faro and Gemini as a fixed service instead of editable provider fields", () => {
    render(<AgentSettings value={settings()} />);

    expect(screen.getByText("Faro")).toBeVisible();
    expect(screen.getByText(FARO_MODEL)).toBeVisible();
    expect(screen.getByText(`${FARO_CONTEXT_WINDOW.toLocaleString("en-US")} tokens`)).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Provider" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Model" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "Context window" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("claude");
    expect(document.body).not.toHaveTextContent("fable");
  });

  it("warns about bypassPermissions and shows a smaller actual provider capability", () => {
    render(
      <AgentSettings
        providerCapability={{ contextWindow: 16_000, secretConfigured: true }}
        value={settings()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("bypassPermissions");
    expect(screen.getByText(/Provider 实际 context window：16,000/)).toBeVisible();
    expect(screen.getByText(/请求值 32,000/)).toBeVisible();
  });

  it("accepts safe provider capability metadata from the settings payload", () => {
    render(
      <AgentSettings
        value={settings({
          provider_context_window: 16_000,
          provider_secret_configured: true,
        })}
      />,
    );

    expect(screen.getByText(/Provider 实际 context window：16,000/)).toBeVisible();
    expect(screen.getByText("configured")).toBeVisible();
  });

  it("reports only configured/not-configured for secrets and never renders a key value", () => {
    const secret = "sk-provider-should-never-render";
    const { rerender } = render(
      <AgentSettings
        providerCapability={{ contextWindow: FARO_CONTEXT_WINDOW, secretConfigured: true }}
        value={settings({ api_key: secret, license: "MIT", commit: "d190786d" })}
      />,
    );

    expect(screen.getByText("configured")).toBeVisible();
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(screen.queryByText(/MIT|d190786d/)).not.toBeInTheDocument();

    rerender(
      <AgentSettings
        providerCapability={{ contextWindow: FARO_CONTEXT_WINDOW, secretConfigured: false }}
        value={settings({ api_key: secret })}
      />,
    );
    expect(screen.getByText("not-configured")).toBeVisible();
  });

  it("keeps Faro service values fixed when editable workspace settings change", () => {
    const onChange = vi.fn();
    render(
      <AgentSettings
        onChange={onChange}
        value={settings({ api_key: "sk-private", secret_reference: "vault://private" })}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Permission mode" }), {
      target: { value: "plan" },
    });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      provider: FARO_PROVIDER,
      model: FARO_MODEL,
      context_window: FARO_CONTEXT_WINDOW,
      permission_mode: "plan",
    }));
    expect(onChange.mock.calls[0][0]).not.toHaveProperty("api_key");
    expect(onChange.mock.calls[0][0]).not.toHaveProperty("secret_reference");
  });

  it("keeps workspace roots and capabilities configurable without changing the service", () => {
    const onChange = vi.fn();
    render(<AgentSettings onChange={onChange} value={settings()} />);

    expect(screen.getByText("E:\\项目\\知识库课本")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "MCP" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Skills" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Subagents" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Web" })).toBeChecked();

    screen.getByRole("checkbox", { name: "Web" }).click();
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      provider: FARO_PROVIDER,
      model: FARO_MODEL,
      context_window: FARO_CONTEXT_WINDOW,
      web_enabled: false,
    }));
  });
});