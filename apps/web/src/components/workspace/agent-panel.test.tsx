import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentConnectionState,
  AgentDiagnostics,
  AgentEventEnvelope,
  AgentSession,
  AgentSessionSummary,
  AgentSettings,
} from "@/lib/agent-api";

import { AgentPanel } from "./agent-panel";

const mocks = vi.hoisted(() => ({
  archive: vi.fn(),
  connectAgentEvents: vi.fn(),
  create: vi.fn(),
  diagnostics: vi.fn(),
  events: vi.fn(),
  fork: vi.fn(),
  get: vi.fn(),
  list: vi.fn(),
  mcp: vi.fn(),
  resume: vi.fn(),
  rewind: vi.fn(),
  send: vi.fn(),
  settings: vi.fn(),
  sidecar: vi.fn(),
  skills: vi.fn(),
  stop: vi.fn(),
  updateSettings: vi.fn(),
}));

vi.mock("@/lib/agent-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/agent-api")>();
  return {
    ...actual,
    agentApi: {
      archive: mocks.archive,
      create: mocks.create,
      diagnostics: mocks.diagnostics,
      events: mocks.events,
      fork: mocks.fork,
      get: mocks.get,
      list: mocks.list,
      mcp: mocks.mcp,
      resume: mocks.resume,
      rewind: mocks.rewind,
      send: mocks.send,
      settings: mocks.settings,
      sidecar: mocks.sidecar,
      skills: mocks.skills,
      stop: mocks.stop,
      updateSettings: mocks.updateSettings,
    },
    connectAgentEvents: mocks.connectAgentEvents,
  };
});

const settings: AgentSettings = {
  provider: "faro",
  model: "gemini-3.7-flash-tiered",
  context_window: 32_000,
  provider_secret_configured: true,
  permission_mode: "bypassPermissions",
  workspace_roots: ["E:/vaults/personal"],
  mcp_enabled: true,
  skills_enabled: true,
  subagents_enabled: true,
  web_enabled: true,
};

const diagnostics: AgentDiagnostics = {
  runtime: { status: "healthy", version: "1.0.0" },
  providers: [{ name: "faro", status: "ready" }],
  mcp: [{ name: "filesystem", status: "connected" }],
};

const runningSession: AgentSessionSummary = {
  id: "session-running",
  title: "函数研究",
  provider: "faro",
  model: "gemini-3.7-flash-tiered",
  state: "running",
  last_event_sequence: 4,
  is_legacy: false,
};

function session(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    ...runningSession,
    knowledge_base_id: "kb-current",
    ...overrides,
  };
}

function event(
  sequence: number,
  eventType: AgentEventEnvelope["event_type"],
  payload: Record<string, unknown>,
): AgentEventEnvelope {
  return {
    event_id: `event-${sequence}`,
    session_id: "session-running",
    turn_id: "turn-1",
    sequence,
    event_type: eventType,
    timestamp: `2026-08-28T00:00:0${sequence}.000Z`,
    payload,
    idempotency_key: `idem-${sequence}`,
  };
}

function renderPanel(onOpenCitation = vi.fn()) {
  return render(
    <AgentPanel
      contextLabel="第一章 / 函数"
      joinedSpaceIds={["space-current", "space-class"]}
      knowledgeBase={{ id: "kb-current", name: "当前知识库" }}
      onOpenCitation={onOpenCitation}
      readableVaultScopes={[
        { spaceId: "space-current", knowledgeBaseId: "kb-current" },
        { spaceId: "space-class", knowledgeBaseId: "kb-class" },
      ]}
      space={{ id: "space-current", name: "个人空间" }}
    />,
  );
}

describe("AgentPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, "", "/workspace");
    vi.clearAllMocks();

    mocks.list.mockResolvedValue([runningSession]);
    mocks.settings.mockResolvedValue(settings);
    mocks.diagnostics.mockResolvedValue(diagnostics);
    mocks.events.mockResolvedValue({ events: [], last_sequence: 0 });
    mocks.create.mockResolvedValue(session({ id: "session-created", title: "新会话", state: "waiting_input", last_event_sequence: 0 }));
    mocks.get.mockImplementation(async (sessionId: string) => session({ id: sessionId }));
    mocks.archive.mockResolvedValue(undefined);
    mocks.stop.mockResolvedValue(session({ state: "stopped" }));
    mocks.resume.mockResolvedValue(session({ state: "running" }));
    mocks.rewind.mockResolvedValue(session({ id: "session-rewound", state: "waiting_input" }));
    mocks.fork.mockResolvedValue(session({ id: "session-forked", state: "waiting_input" }));
    mocks.send.mockResolvedValue({ accepted: true });
    mocks.updateSettings.mockImplementation(async (value: AgentSettings) => value);
    mocks.sidecar.mockResolvedValue(new Response("full", {
      status: 206,
      headers: { "Content-Range": "bytes 0-3/4", "Content-Type": "text/plain" },
    }));
    mocks.connectAgentEvents.mockImplementation(
      (_sessionId: string, after: number, _onEvent: (value: AgentEventEnvelope) => void, onState: (value: AgentConnectionState) => void) => {
        onState({ status: "open", attempt: 0, after });
        return { after, close: vi.fn() };
      },
    );
  });

  it("loads control-plane data, restores the persisted session, replays all events, and composes every Agent surface", async () => {
    localStorage.setItem("agent-session-preference-v1", JSON.stringify({
      sessionId: "session-running",
      lastPersistedSequence: 2,
    }));
    const replay = [
      event(1, "user_message", { text: "解释函数" }),
      event(2, "model_text_delta", { text: "函数描述输入与输出的对应关系。" }),
      event(3, "tool_started", {
        tool_call_id: "tool-web",
        name: "WebSearch",
        tool_kind: "web_search",
        input: { query: "函数定义" },
      }),
      event(4, "tool_completed", {
        tool_call_id: "tool-web",
        name: "WebSearch",
        tool_kind: "web_search",
        output: { results: ["A", "B", "C"] },
        sidecar_id: "sidecar-1",
        sha256: "abc",
        size: 4,
        media_type: "text/plain",
      }),
    ];
    mocks.events.mockResolvedValue({ events: replay, last_sequence: 4 });

    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("函数描述输入与输出的对应关系。")).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Agent sessions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "服务设置" })).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-tool-web_search")).toBeVisible();
    expect(await screen.findByTestId("agent-sidecar-sidecar-1")).toHaveTextContent("full");

    await user.click(screen.getByRole("button", { name: "打开助教设置" }));
    const dialog = screen.getByRole("dialog", { name: "Workspace Agent 设置" });
    expect(within(dialog).getByRole("navigation", { name: "Agent sessions" })).toBeVisible();
    await user.click(within(dialog).getByRole("tab", { name: "服务设置" }));
    expect(within(dialog).getByRole("heading", { name: "服务设置" })).toBeVisible();
    expect(screen.getByTestId("diagnostic-runtime")).toHaveTextContent("healthy");
    expect(mocks.list).toHaveBeenCalledTimes(1);
    expect(mocks.settings).toHaveBeenCalledTimes(1);
    expect(mocks.diagnostics).toHaveBeenCalledTimes(1);
    expect(mocks.events).toHaveBeenCalledWith("session-running", 0, expect.any(AbortSignal));
    expect(mocks.connectAgentEvents).toHaveBeenCalledWith(
      "session-running",
      4,
      expect.any(Function),
      expect.any(Function),
    );
    expect(JSON.parse(localStorage.getItem("agent-session-preference-v1") ?? "null")).toEqual({
      sessionId: "session-running",
      lastPersistedSequence: 4,
    });
  });

  it("creates a session from the current knowledge base when none can be restored", async () => {
    mocks.list.mockResolvedValue([]);
    mocks.create.mockResolvedValue(session({
      id: "session-created",
      title: "当前知识库",
      state: "waiting_input",
      last_event_sequence: 0,
    }));

    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith({
      knowledge_base_id: "kb-current",
      provider: "faro",
      model: "gemini-3.7-flash-tiered",
      context_window: 32_000,
      title: "当前知识库",
      linked_contexts: [{ knowledge_base_id: "kb-current", label: "知识库：当前知识库" }],
    }, expect.any(AbortSignal)));
    await user.click(screen.getByRole("button", { name: "打开助教设置" }));
    expect(screen.getByText("当前知识库")).toBeVisible();
    expect(mocks.connectAgentEvents).toHaveBeenCalledWith(
      "session-created",
      0,
      expect.any(Function),
      expect.any(Function),
    );
  });

  it("labels the default whole-knowledge-base context without exposing its id", async () => {
    renderPanel();

    const composer = await screen.findByRole("region", { name: "Agent composer" });
    expect(within(composer).getByText("知识库：当前知识库")).toBeVisible();
    expect(within(composer).queryByText("kb-current")).not.toBeInTheDocument();
  });
  it.each([
    ["URL", () => window.history.replaceState({}, "", "/workspace?agentSession=session-failed&agentAfter=9")],
    ["localStorage", () => localStorage.setItem("agent-session-preference-v1", JSON.stringify({
      sessionId: "session-failed",
      lastPersistedSequence: 9,
    }))],
    ["最近会话", () => undefined],
  ])("does not restore a failed Faro session from %s when a healthy Faro session exists", async (_source, arrangePreference) => {
    const failedSession: AgentSessionSummary = {
      ...runningSession,
      id: "session-failed",
      title: "失败会话",
      state: "failed",
      last_event_sequence: 9,
    };
    const healthySession: AgentSessionSummary = {
      ...runningSession,
      id: "session-healthy",
      title: "健康会话",
      state: "waiting_input",
      last_event_sequence: 3,
    };
    mocks.list.mockResolvedValue([failedSession, healthySession]);
    arrangePreference();

    renderPanel();

    await waitFor(() => expect(mocks.events).toHaveBeenCalledWith(
      "session-healthy",
      0,
      expect.any(AbortSignal),
    ));
    expect(mocks.events).not.toHaveBeenCalledWith(
      "session-failed",
      expect.any(Number),
      expect.any(AbortSignal),
    );
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.connectAgentEvents).toHaveBeenCalledWith(
      "session-healthy",
      0,
      expect.any(Function),
      expect.any(Function),
    );
  });

  it.each([
    ["failed Faro", session({ id: "session-failed", state: "failed" })],
    ["archived Faro", session({ id: "session-archived", state: "archived" })],
    ["旧 provider", session({
      id: "session-legacy-provider",
      provider: "claude",
      model: "fable",
      state: "waiting_input",
    })],
  ])("creates a healthy Faro session when only %s history exists", async (_kind, unavailableSession) => {
    mocks.list.mockResolvedValue([unavailableSession]);

    renderPanel();

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith({
      knowledge_base_id: "kb-current",
      provider: "faro",
      model: "gemini-3.7-flash-tiered",
      context_window: 32_000,
      title: "当前知识库",
      linked_contexts: [{ knowledge_base_id: "kb-current", label: "知识库：当前知识库" }],
    }, expect.any(AbortSignal)));
    expect(mocks.events).toHaveBeenCalledWith(
      "session-created",
      0,
      expect.any(AbortSignal),
    );
  });

  it("replays a cursor gap, reconnects from the recovered cursor, and streams every event without a fixed accumulation limit", async () => {
    let onEvent: ((value: AgentEventEnvelope) => void) | undefined;
    let onState: ((value: AgentConnectionState) => void) | undefined;
    const closes: ReturnType<typeof vi.fn>[] = [];
    mocks.events
      .mockResolvedValueOnce({ events: [], last_sequence: 0 })
      .mockResolvedValueOnce({
        events: [
          event(2, "model_text_delta", { text: "二" }),
          event(3, "model_text_delta", { text: "三" }),
        ],
        last_sequence: 3,
      });
    mocks.connectAgentEvents.mockImplementation(
      (_sessionId: string, after: number, nextEvent: (value: AgentEventEnvelope) => void, nextState: (value: AgentConnectionState) => void) => {
        onEvent = nextEvent;
        onState = nextState;
        const close = vi.fn();
        closes.push(close);
        nextState({ status: "open", attempt: 0, after });
        return { after, close };
      },
    );

    renderPanel();
    await waitFor(() => expect(mocks.connectAgentEvents).toHaveBeenCalledTimes(1));

    act(() => onEvent?.(event(1, "model_text_delta", { text: "一" })));
    expect(await screen.findByText("一")).toBeVisible();
    act(() => onState?.({ status: "reconnecting", attempt: 1, after: 1 }));
    expect(screen.getByText(/正在重连/)).toBeVisible();

    act(() => onEvent?.(event(3, "model_text_delta", { text: "三" })));

    await waitFor(() => expect(mocks.events).toHaveBeenLastCalledWith(
      "session-running",
      1,
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(mocks.connectAgentEvents).toHaveBeenLastCalledWith(
      "session-running",
      3,
      expect.any(Function),
      expect.any(Function),
    ));
    expect(closes[0]).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("一二三")).toBeVisible();
  });

  it("orchestrates composer send, stop, resume, sidebar branching, and settings persistence", async () => {
    mocks.events.mockResolvedValue({
      events: [event(1, "session_state", { state: "waiting_input" })],
      last_sequence: 1,
    });
    const user = userEvent.setup();
    renderPanel();

    const composer = await screen.findByRole("region", { name: "Agent composer" });
    await user.type(within(composer).getByRole("textbox", { name: "向 Agent 发送消息" }), "完整长任务");
    await user.click(within(composer).getByRole("button", { name: "发送" }));
    expect(mocks.send).toHaveBeenCalledWith(
      "session-running",
      { text: "完整长任务", linked_contexts: [{ knowledge_base_id: "kb-current", label: "知识库：当前知识库" }] },
      expect.any(String),
    );

    await user.click(within(composer).getByRole("button", { name: "停止" }));
    expect(mocks.stop).toHaveBeenCalledWith("session-running");
    await user.click(within(composer).getByRole("button", { name: "继续" }));
    expect(mocks.resume).toHaveBeenCalledWith("session-running");

    await user.click(screen.getByRole("button", { name: "打开助教设置" }));
    const dialog = screen.getByRole("dialog", { name: "Workspace Agent 设置" });
    const row = within(dialog).getByTestId("agent-session-session-running");
    await user.click(within(row).getByRole("button", { name: "分叉" }));
    expect(mocks.fork).toHaveBeenCalledWith("session-running", { after_sequence: 4 });

    await user.click(within(dialog).getByRole("tab", { name: "服务设置" }));
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Permission mode" }), {
      target: { value: "plan" },
    });
    await waitFor(() => expect(mocks.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "faro",
        model: "gemini-3.7-flash-tiered",
        context_window: 32_000,
        permission_mode: "plan",
      }),
      expect.any(AbortSignal),
    ));
  });

  it("shows a retryable Runtime unavailable state without crashing other panel content", async () => {
    mocks.diagnostics.mockRejectedValueOnce(new Error("runtime offline"));
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("Runtime unavailable")).toHaveAttribute("role", "alert");
    expect(screen.getByText("当前上下文：第一章 / 函数")).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Agent sessions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开助教设置" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "重试 Agent Runtime" }));
    await waitFor(() => expect(mocks.diagnostics).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "打开助教设置" }));
    await user.click(screen.getByRole("tab", { name: "服务设置" }));
    expect(await screen.findByTestId("diagnostic-runtime")).toHaveTextContent("healthy");
  });

  it("closes the settings dialog with Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    renderPanel();
    const trigger = await screen.findByRole("button", { name: "打开助教设置" });

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Workspace Agent 设置" })).toBeVisible();
    expect(screen.getByRole("button", { name: "关闭助教设置" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Workspace Agent 设置" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps stale Claude or Fable sessions as read-only history and creates a writable Faro session", async () => {
    const legacySession: AgentSessionSummary = {
      id: "session-legacy",
      title: "旧助教记录",
      provider: "claude",
      model: "fable",
      state: "waiting_input",
      last_event_sequence: 2,
      is_legacy: false,
    };
    mocks.list.mockResolvedValue([legacySession]);
    mocks.create.mockResolvedValue(session({
      id: "session-faro-new",
      title: "当前知识库",
      provider: "faro",
      model: "gemini-3.7-flash-tiered",
      state: "waiting_input",
      last_event_sequence: 0,
      is_legacy: false,
    }));
    mocks.get.mockResolvedValue({
      ...legacySession,
      knowledge_base_id: "kb-current",
    });
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith({
      knowledge_base_id: "kb-current",
      provider: "faro",
      model: "gemini-3.7-flash-tiered",
      context_window: 32_000,
      title: "当前知识库",
      linked_contexts: [{ knowledge_base_id: "kb-current", label: "知识库：当前知识库" }],
    }, expect.any(AbortSignal)));
    expect(mocks.connectAgentEvents).toHaveBeenCalledTimes(1);
    expect(mocks.connectAgentEvents).toHaveBeenLastCalledWith(
      "session-faro-new",
      0,
      expect.any(Function),
      expect.any(Function),
    );

    await user.click(screen.getByRole("button", { name: "打开助教设置" }));
    const legacyRow = screen.getByTestId("agent-session-session-legacy");
    expect(within(legacyRow).getByText("claude · fable")).toBeVisible();
    expect(within(legacyRow).queryByRole("button", { name: "继续" })).not.toBeInTheDocument();
    expect(within(legacyRow).queryByRole("button", { name: "停止" })).not.toBeInTheDocument();
    expect(within(legacyRow).queryByRole("button", { name: "分叉" })).not.toBeInTheDocument();

    await user.click(within(legacyRow).getByRole("button", { name: "切换到旧助教记录" }));
    expect(await screen.findByText(/此旧会话仅供查看/)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "向 Agent 发送消息" })).toBeDisabled();
    expect(mocks.connectAgentEvents).toHaveBeenCalledTimes(1);
  });

  it("does not invent the current space or forward metadata for a citation without space_id", async () => {
    const onOpenCitation = vi.fn();
    const secrets = ["面板机密标题", "面板机密章节", "面板机密摘要", "机密/面板.md", "file-panel-secret"];
    mocks.events.mockResolvedValue({
      events: [event(1, "model_text_delta", {
        citations: [{
          id: "citation-missing-space",
          kind: "vault",
          label: secrets[0],
          heading: secrets[1],
          excerpt: secrets[2],
          path: secrets[3],
          vault_file_id: secrets[4],
          knowledge_base_id: "kb-current",
        }],
      })],
      last_sequence: 1,
    });
    const user = userEvent.setup();
    renderPanel(onOpenCitation);

    const protectedCitation = await screen.findByText("受保护的 Vault 引用");
    expect(protectedCitation.tagName).not.toBe("BUTTON");
    for (const secret of secrets) expect(document.body).not.toHaveTextContent(secret);
    await user.click(protectedCitation);
    expect(onOpenCitation).not.toHaveBeenCalled();
  });

  it("preserves space, knowledge base, path, and heading in the Vault citation callback", async () => {
    const onOpenCitation = vi.fn();
    mocks.events.mockResolvedValue({
      events: [event(1, "model_text_delta", {
        text: "参见函数定义。",
        citations: [{
          id: "citation-1",
          kind: "vault",
          label: "函数定义",
          space_id: "space-class",
          knowledge_base_id: "kb-class",
          vault_file_id: "file-function",
          path: "概念/函数.md",
          heading: "定义",
        }],
      })],
      last_sequence: 1,
    });
    const user = userEvent.setup();
    renderPanel(onOpenCitation);

    await user.click(await screen.findByRole("button", { name: "函数定义" }));

    expect(onOpenCitation).toHaveBeenCalledWith({
      spaceId: "space-class",
      knowledgeBaseId: "kb-class",
      vaultFileId: "file-function",
      path: "概念/函数.md",
      heading: "定义",
    });
  });
});
