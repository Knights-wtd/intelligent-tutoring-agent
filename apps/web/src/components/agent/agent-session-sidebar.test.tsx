import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentSessionSummary } from "@/lib/agent-api";

import {
  AgentSessionSidebar,
  encodeAgentSessionPreference,
  resolveAgentSessionPreference,
} from "./agent-session-sidebar";

function session(
  id: string,
  overrides: Partial<AgentSessionSummary> = {},
): AgentSessionSummary {
  return {
    id,
    title: id,
    provider: "claude",
    model: "claude-sonnet-4-5",
    state: "waiting_input",
    last_event_sequence: 17,
    is_legacy: false,
    ...overrides,
  };
}

function callbacks() {
  return {
    onCreate: vi.fn(),
    onSelect: vi.fn(),
    onArchive: vi.fn(),
    onStop: vi.fn(),
    onResume: vi.fn(),
    onRewind: vi.fn(),
    onFork: vi.fn(),
  };
}

describe("AgentSessionSidebar", () => {
  it("groups active, warm, archived, and legacy sessions", () => {
    render(
      <AgentSessionSidebar
        {...callbacks()}
        selectedSessionId="active"
        sessions={[
          session("active", { title: "正在执行", state: "running" }),
          session("warm", { title: "保持就绪", state: "waiting_input" }),
          session("archived", { title: "已归档", state: "archived" }),
          session("legacy", { title: "旧 Tutor 对话", is_legacy: true }),
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Active" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Warm" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Archived" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Legacy" })).toBeVisible();
    expect(screen.getByRole("button", { name: "切换到正在执行" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("offers exact resume, rewind, and fork controls with the minimal native props", () => {
    render(
      <AgentSessionSidebar
        onFork={vi.fn()}
        onResume={vi.fn()}
        onRewind={vi.fn()}
        sessions={[session("native", { title: "原生会话", state: "stopped" })]}
      />,
    );

    expect(screen.getByRole("button", { name: "继续" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "回退" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "分叉" })).toBeEnabled();
  });

  it("supports create, switch, archive, stop, resume, rewind, and fork", async () => {
    const handlers = callbacks();
    const user = userEvent.setup();
    render(
      <AgentSessionSidebar
        {...handlers}
        sessions={[
          session("running", { title: "运行任务", state: "running", last_event_sequence: 8 }),
          session("stopped", { title: "暂停任务", state: "stopped", last_event_sequence: 13 }),
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "新建会话" }));
    await user.click(screen.getByRole("button", { name: "切换到运行任务" }));
    await user.click(within(screen.getByTestId("agent-session-running")).getByRole("button", { name: "停止" }));
    await user.click(within(screen.getByTestId("agent-session-running")).getByRole("button", { name: "归档" }));
    await user.click(within(screen.getByTestId("agent-session-stopped")).getByRole("button", { name: "继续" }));
    await user.click(within(screen.getByTestId("agent-session-stopped")).getByRole("button", { name: "回退" }));
    await user.click(within(screen.getByTestId("agent-session-stopped")).getByRole("button", { name: "分叉" }));

    expect(handlers.onCreate).toHaveBeenCalledOnce();
    expect(handlers.onSelect).toHaveBeenCalledWith("running");
    expect(handlers.onStop).toHaveBeenCalledWith("running");
    expect(handlers.onArchive).toHaveBeenCalledWith("running");
    expect(handlers.onResume).toHaveBeenCalledWith("stopped");
    expect(handlers.onRewind).toHaveBeenCalledWith("stopped", 13);
    expect(handlers.onFork).toHaveBeenCalledWith("stopped", 13);
  });

  it("keeps legacy Tutor sessions viewable and archivable without native controls", () => {
    render(
      <AgentSessionSidebar
        {...callbacks()}
        sessions={[session("legacy", { title: "历史答疑", is_legacy: true })]}
      />,
    );

    const row = screen.getByTestId("agent-session-legacy");
    expect(within(row).getByRole("button", { name: "切换到历史答疑" })).toBeEnabled();
    expect(within(row).getByRole("button", { name: "归档" })).toBeEnabled();
    expect(within(row).queryByRole("button", { name: /停止|继续|回退|分叉/ })).not.toBeInTheDocument();
  });
});

describe("agent session restore preference", () => {
  it("prefers a valid URL session and its replay cursor", () => {
    expect(
      resolveAgentSessionPreference({
        search: "?agentSession=url-session&agentAfter=42",
        storedPreference: JSON.stringify({
          sessionId: "stored-session",
          lastPersistedSequence: 9,
        }),
        sessions: [session("url-session"), session("stored-session")],
      }),
    ).toEqual({ sessionId: "url-session", lastPersistedSequence: 42 });
  });

  it("reuses the local persisted cursor when the URL selects the same session without a cursor", () => {
    expect(
      resolveAgentSessionPreference({
        search: "?agentSession=warm",
        storedPreference: JSON.stringify({
          sessionId: "warm",
          lastPersistedSequence: 31,
        }),
        sessions: [session("warm")],
      }),
    ).toEqual({ sessionId: "warm", lastPersistedSequence: 31 });
  });

  it("falls back to local preference and rejects missing or invalid cursors", () => {
    expect(
      resolveAgentSessionPreference({
        search: "?agentSession=missing&agentAfter=-2",
        storedPreference: JSON.stringify({
          sessionId: "warm",
          lastPersistedSequence: 23,
        }),
        sessions: [session("warm")],
      }),
    ).toEqual({ sessionId: "warm", lastPersistedSequence: 23 });

    expect(
      encodeAgentSessionPreference({
        sessionId: "warm",
        lastPersistedSequence: 23,
      }),
    ).toBe('{"sessionId":"warm","lastPersistedSequence":23}');
  });
});
