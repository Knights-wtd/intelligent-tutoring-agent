import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentDiagnostics } from "./agent-diagnostics";

describe("AgentDiagnostics", () => {
  it("shows runtime, provider, and MCP degradation without rendering arbitrary secret details", () => {
    const secret = "runtime-secret-body";
    render(
      <AgentDiagnostics
        value={{
          runtime: { status: "unavailable", detail: secret, commit: "hidden-commit" },
          providers: [
            { id: "claude", status: "degraded", detail: secret },
            { id: "faro", status: "healthy" },
          ],
          mcp: [{ name: "filesystem", state: "degraded", error: secret }],
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Diagnostics" })).toBeVisible();
    expect(within(screen.getByTestId("diagnostic-runtime")).getByText("unavailable")).toBeVisible();
    expect(within(screen.getByTestId("diagnostic-provider-claude")).getByText("degraded")).toBeVisible();
    expect(within(screen.getByTestId("diagnostic-provider-faro")).getByText("healthy")).toBeVisible();
    expect(within(screen.getByTestId("diagnostic-mcp-filesystem")).getByText("degraded")).toBeVisible();
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(screen.queryByText("hidden-commit")).not.toBeInTheDocument();
  });

  it("normalizes unrecognized status text instead of echoing it", () => {
    const secret = "sk-status-secret";
    render(<AgentDiagnostics value={{ runtime: { status: secret } }} />);
    expect(within(screen.getByTestId("diagnostic-runtime")).getByText("unknown")).toBeVisible();
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
  });

  it("uses an explicit unknown state when diagnostics are missing", () => {
    render(<AgentDiagnostics value={{}} />);
    expect(within(screen.getByTestId("diagnostic-runtime")).getByText("unknown")).toBeVisible();
    expect(screen.getByText("No provider diagnostics")).toBeVisible();
    expect(screen.getByText("No MCP diagnostics")).toBeVisible();
  });
});
