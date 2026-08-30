import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentEventEnvelope } from "@/lib/agent-api";
import type { KnowledgeBase } from "@/lib/knowledge-api";

import { WorkspaceShell } from "./workspace-shell";

const directory = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(directory, "../../..");

const mockKnowledgeApi = vi.hoisted(() => ({
  create: vi.fn(),
  documentStatus: vi.fn(),
  graph: vi.fn(),
  list: vi.fn(),
  note: vi.fn(),
  pagePreview: vi.fn(),
  search: vi.fn(),
  upload: vi.fn(),
  workspace: vi.fn(),
}));
const mockQuestionBankApi = vi.hoisted(() => ({
  listAttemptHistory: vi.fn(),
  listQuestions: vi.fn(),
  listReviewItems: vi.fn(),
  submitAttempt: vi.fn(),
}));
const mockClassroomApi = vi.hoisted(() => ({
  create: vi.fn(),
  join: vi.fn(),
}));
const mockBreakpoint = vi.hoisted(() => ({
  value: "desktop" as "desktop" | "tablet" | "compact" | "mobile",
}));
const mockAgentNetwork = vi.hoisted(() => ({
  citations: [] as Record<string, unknown>[],
  connectAgentEvents: vi.fn(),
  fetch: vi.fn(),
  turnFailuresRemaining: 0,
  turnRequests: [] as Array<{ body: string; idempotencyKey: string | null }>,
  vaultRequests: 0,
}));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});
vi.mock("@/lib/question-bank-api", () => ({ questionBankApi: mockQuestionBankApi }));
vi.mock("@/lib/classrooms-api", () => ({ classroomApi: mockClassroomApi }));
vi.mock("@/lib/agent-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/agent-api")>();
  return { ...actual, connectAgentEvents: mockAgentNetwork.connectAgentEvents };
});
vi.mock("./use-workspace-breakpoint", () => ({
  useWorkspaceBreakpoint: () => mockBreakpoint.value,
}));

const personalSpace = { id: "personal", kind: "personal" as const, name: "我的空间" };
const classroomSpace = { id: "class-space", kind: "classroom" as const, name: "函数班" };
const wireless: KnowledgeBase = {
  created_at: "2026-08-01T00:00:00Z",
  id: "kb-wireless",
  name: "无线通信",
  space_id: "personal",
  state: "ready",
  updated_at: "2026-08-01T00:00:00Z",
};
const digital: KnowledgeBase = { ...wireless, id: "kb-digital", name: "数字通信" };
const functionsKnowledgeBase: KnowledgeBase = {
  ...wireless,
  id: "kb-functions",
  name: "函数知识库",
  space_id: "class-space",
};

const agentSession = {
  id: "session-acceptance",
  title: "Workspace 验收",
  knowledge_base_id: wireless.id,
  space_id: personalSpace.id,
  provider: "faro",
  model: "gemini-3.7-flash-tiered",
  state: "waiting_input",
  last_event_sequence: 1,
  is_legacy: false,
};
const classroomAgentSession = {
  ...agentSession,
  id: "session-functions",
  title: "函数知识库验收",
  knowledge_base_id: functionsKnowledgeBase.id,
  space_id: classroomSpace.id,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function agentEvent(
  citations: Record<string, unknown>[],
  sessionId = agentSession.id,
): AgentEventEnvelope {
  return {
    event_id: `event-${sessionId}-1`,
    session_id: sessionId,
    turn_id: "turn-acceptance-1",
    sequence: 1,
    event_type: "model_text_delta",
    timestamp: "2026-08-29T08:00:00Z",
    payload: { text: "请查看引用。", citations },
    idempotency_key: "acceptance-event-1",
  };
}

function productionFiles(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name);
    if (entry.isDirectory()) return productionFiles(path);
    if (/\.(?:test|spec)\.[cm]?[jt]sx?$/.test(entry.name)) return [];
    return [".css", ".js", ".jsx", ".ts", ".tsx"].includes(extname(entry.name)) ? [path] : [];
  });
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, "", "/workspace");
  mockBreakpoint.value = "desktop";
  mockAgentNetwork.citations = [];
  mockAgentNetwork.turnFailuresRemaining = 0;
  mockAgentNetwork.turnRequests = [];
  mockAgentNetwork.vaultRequests = 0;
  mockAgentNetwork.fetch.mockReset();
  mockAgentNetwork.connectAgentEvents.mockReset();
  mockAgentNetwork.connectAgentEvents.mockImplementation(
    (_sessionId: string, after: number, _onEvent: (event: AgentEventEnvelope) => void, onState: (state: unknown) => void) => {
      onState({ status: "open", attempt: 0, after });
      return { after, close: vi.fn() };
    },
  );

  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  for (const mock of Object.values(mockQuestionBankApi)) mock.mockReset();
  for (const mock of Object.values(mockClassroomApi)) mock.mockReset();

  mockKnowledgeApi.list.mockImplementation((spaceId: string) =>
    Promise.resolve(spaceId === classroomSpace.id ? [functionsKnowledgeBase] : [wireless, digital]),
  );
  mockKnowledgeApi.graph.mockResolvedValue({ edges: [], nodes: [] });
  mockKnowledgeApi.workspace.mockImplementation((knowledgeBaseId: string) =>
    Promise.resolve({ candidate_batch: null, documents: [], knowledge_base_id: knowledgeBaseId, notes: [] }),
  );
  mockQuestionBankApi.listQuestions.mockResolvedValue([]);
  mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [], next_cursor: null });

  mockAgentNetwork.fetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/v1/agent/diagnostics")) {
      return jsonResponse({ runtime: { status: "healthy" }, providers: [], mcp: [] });
    }
    if (url.includes("/api/v1/agent/settings")) {
      return jsonResponse({
        provider: "faro",
        model: "gemini-3.7-flash-tiered",
        context_window: 32_000,
        provider_secret_configured: true,
      });
    }
    const eventSession = [agentSession, classroomAgentSession].find(
      (session) => url.includes(`/api/v1/agent/sessions/${session.id}/events`),
    );
    if (eventSession) {
      const events = mockAgentNetwork.citations.length > 0
        ? [agentEvent(mockAgentNetwork.citations, eventSession.id)]
        : [];
      return jsonResponse(events);
    }
    if (url.includes(`/api/v1/agent/sessions/${agentSession.id}/turns`)) {
      mockAgentNetwork.turnRequests.push({
        body: String(init?.body ?? ""),
        idempotencyKey: new Headers(init?.headers).get("Idempotency-Key"),
      });
      if (mockAgentNetwork.turnFailuresRemaining > 0) {
        mockAgentNetwork.turnFailuresRemaining -= 1;
        return jsonResponse({ detail: "runtime turn offline" }, 503);
      }
      return jsonResponse({ turn_id: "turn-retried", native_session_id: "native-session" }, 202);
    }
    if (url.endsWith("/api/v1/agent/sessions")) {
      return jsonResponse([agentSession, classroomAgentSession]);
    }
    if (url.includes("/api/v1/knowledge-bases/") && url.includes("/vault/files/")) {
      mockAgentNetwork.vaultRequests += 1;
      return jsonResponse({
        markdown: "# 函数\n\n函数是集合之间的映射。",
        relative_path: "概念/函数.md",
        vault_file_id: "file-function",
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", mockAgentNetwork.fetch);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Workspace Agent aggregate acceptance", () => {
  it("mounts the real AgentPanel as the only active AI workspace entry", async () => {
    const shellSource = readFileSync(resolve(directory, "workspace-shell.tsx"), "utf8");
    expect(shellSource.match(/<AgentPanel\b/g)).toHaveLength(1);
    expect(shellSource).not.toContain("TutorPanel");
    expect(shellSource).not.toContain("assistantMode");
    expect(existsSync(resolve(directory, "tutor-panel.tsx"))).toBe(false);

    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    const agent = screen.getByRole("region", { name: "Workspace Agent" });
    expect(within(agent).queryByRole("navigation", { name: "Agent sessions" })).not.toBeInTheDocument();
    expect(within(agent).getByRole("region", { name: "Agent composer" })).toBeInTheDocument();
    await user.click(within(agent).getByRole("button", { name: "打开助教设置" }));
    expect(screen.getByRole("dialog", { name: "Workspace Agent 设置" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Agent sessions" })).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Workspace Agent" })).toHaveLength(1);
    expect(screen.queryByLabelText("AI 家教")).not.toBeInTheDocument();
  });

  it("keeps the desktop library, center workspace, and inline Agent operable", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);
    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(document.querySelector("main[data-layout]")).toHaveAttribute("data-layout", "library-center-agent");
    expect(screen.getAllByRole("separator")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "选择数字通信" }));
    await user.click(screen.getByRole("tab", { name: "知识库" }));
    expect(await screen.findByLabelText("知识库面板")).toHaveTextContent("数字通信");
  });

  it("keeps tablet navigation inline while moving only Agent into an accessible drawer", async () => {
    mockBreakpoint.value = "tablet";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);
    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开知识库" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    const trigger = screen.getByRole("button", { name: "打开 Workspace Agent" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Workspace Agent 抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭 Workspace Agent 抽屉" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Workspace Agent 抽屉" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps mobile library and Agent drawers independently navigable without losing selection", async () => {
    mockBreakpoint.value = "mobile";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);
    expect(screen.getByRole("main")).toHaveAttribute("data-layout", "center-drawers");
    expect(screen.queryByRole("navigation", { name: "知识库" })).not.toBeInTheDocument();
    const libraryTrigger = screen.getByRole("button", { name: "打开知识库" });
    await user.click(libraryTrigger);
    expect(screen.getByRole("dialog", { name: "知识库抽屉" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "选择数字通信" }));
    await user.keyboard("{Escape}");
    expect(libraryTrigger).toHaveFocus();
    const agentTrigger = screen.getByRole("button", { name: "打开 Workspace Agent" });
    await user.click(agentTrigger);
    expect(screen.getByRole("dialog", { name: "Workspace Agent 抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭 Workspace Agent 抽屉背景" }));
    expect(agentTrigger).toHaveFocus();
  });

  it("retries the real failed Runtime turn while knowledge and question-bank controls stay usable", async () => {
    mockAgentNetwork.turnFailuresRemaining = 1;
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    const composer = await screen.findByRole("region", { name: "Agent composer" });
    const textbox = within(composer).getByRole("textbox", { name: "向 Agent 发送消息" });
    const sendButton = within(composer).getByRole("button", { name: "发送" });
    await waitFor(() => expect(textbox).toBeEnabled());
    fireEvent.change(textbox, { target: { value: "请解释信道容量" } });
    await waitFor(() => expect(sendButton).toBeEnabled());
    await user.click(sendButton);
    await waitFor(() => expect(mockAgentNetwork.turnRequests).toHaveLength(1));

    const alert = await screen.findByText("Runtime unavailable");
    expect(alert).toHaveAttribute("role", "alert");
    expect(screen.getByText(/HTTP 503/)).toHaveTextContent("runtime turn offline");
    expect(mockAgentNetwork.turnRequests).toHaveLength(1);
    await user.click(screen.getByRole("tab", { name: "知识库" }));
    expect(await screen.findByLabelText("知识库面板")).toHaveTextContent("无线通信");
    await user.click(screen.getByRole("tab", { name: "题库练习" }));
    expect(await screen.findByLabelText("题库练习面板")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试失败的 Agent 消息" }));
    await waitFor(() => expect(mockAgentNetwork.turnRequests).toHaveLength(2));
    expect(mockAgentNetwork.turnRequests[1]).toEqual(mockAgentNetwork.turnRequests[0]);
    expect(screen.queryByRole("alert", { name: "Runtime unavailable" })).not.toBeInTheDocument();
  });

  it("opens a readable joined-space citation through the real AgentPanel and ACL-backed Vault endpoint", async () => {
    mockAgentNetwork.citations = [{
      id: "citation-readable",
      kind: "vault",
      label: "函数定义",
      heading: "定义",
      knowledge_base_id: "kb-functions",
      path: "概念/函数.md",
      space_id: "class-space",
      vault_file_id: "file-function",
    }];
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    await user.click(await screen.findByRole("button", { name: "切换空间" }));
    await user.click(screen.getByRole("button", { name: classroomSpace.name }));
    await waitFor(() => expect(mockKnowledgeApi.list).toHaveBeenCalledWith(classroomSpace.id, expect.any(AbortSignal)));
    await user.click(await screen.findByRole("button", { name: /Vault 引用|函数定义/ }));
    expect(await screen.findByRole("button", { name: "选择函数知识库" })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(mockAgentNetwork.vaultRequests).toBe(1));
    expect(await screen.findByRole("region", { name: "Vault 文件" })).toHaveTextContent("函数是集合之间的映射。");
  });

  it("hides unjoined citation metadata before any click or Vault request", async () => {
    const secretPath = "机密/未加入空间.md";
    mockAgentNetwork.citations = [{
      id: "citation-foreign",
      kind: "vault",
      heading: "机密",
      knowledge_base_id: "kb-foreign",
      path: secretPath,
      space_id: "space-foreign",
      vault_file_id: "file-foreign",
    }];
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    await screen.findByText("请查看引用。");
    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Vault 引用|机密/ })).not.toBeInTheDocument();
    expect(mockAgentNetwork.vaultRequests).toBe(0);
  });

  it("redacts an unreadable joined-space citation before click and rejects it before the Vault endpoint", async () => {
    const secretPath = "机密/不可读知识库.md";
    mockAgentNetwork.citations = [{
      id: "citation-unreadable",
      kind: "vault",
      heading: "机密",
      knowledge_base_id: "kb-unreadable",
      path: secretPath,
      space_id: "class-space",
      vault_file_id: "file-unreadable",
    }];
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    const citation = await screen.findByText("受保护的 Vault 引用");
    expect(citation.tagName).not.toBe("BUTTON");
    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
    await user.click(citation);
    expect(mockAgentNetwork.vaultRequests).toBe(0);
    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
  });

  it("redacts a joined-space citation that reuses a knowledge-base id readable only in another space", async () => {
    const secretLabel = "跨空间机密标题";
    const secretExcerpt = "跨空间机密摘要";
    const secretPath = "机密/错配知识库.md";
    mockAgentNetwork.citations = [{
      id: "citation-pair-mismatch",
      kind: "vault",
      label: secretLabel,
      excerpt: secretExcerpt,
      knowledge_base_id: wireless.id,
      path: secretPath,
      space_id: classroomSpace.id,
      vault_file_id: "file-pair-mismatch",
    }];
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    expect((await screen.findByText("受保护的 Vault 引用")).tagName).not.toBe("BUTTON");
    expect(screen.queryByText(secretLabel)).not.toBeInTheDocument();
    expect(screen.queryByText(secretExcerpt)).not.toBeInTheDocument();
    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
    expect(mockAgentNetwork.vaultRequests).toBe(0);
  });

  it(["keeps ", ["Clau", "dian"].join(""), " provenance and license text out of client-visible source and real UI"].join(""), async () => {
    const vendorName = ["Clau", "dian"].join("");
    const forbidden = [
      vendorName,
      ["d190786d11cc0b067475", "dcffbf8c334ee565d208"].join(""),
      ["Permission is hereby granted", ", free of charge"].join(""),
      ["Copyright (c)", " 2025"].join(""),
      [vendorName, " commit"].join(""),
      [vendorName.toLowerCase(), "_commit"].join(""),
      [vendorName.toLowerCase(), "-commit"].join(""),
    ];
    const inputs = productionFiles(resolve(webRoot, "src"));
    expect(inputs.length).toBeGreaterThan(0);
    for (const path of inputs) {
      const content = readFileSync(path, "utf8");
      for (const marker of forbidden) expect(content).not.toContain(marker);
    }

    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);
    await user.click(await screen.findByRole("button", { name: "打开助教设置" }));
    await screen.findByRole("navigation", { name: "Agent sessions" });
    const visibleUi = document.body.textContent ?? "";
    for (const marker of forbidden) expect(visibleUi).not.toContain(marker);
  });
});
