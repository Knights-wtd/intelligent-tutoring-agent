import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeBase } from "@/lib/knowledge-api";

import { WorkspaceShell } from "./workspace-shell";

const mockKnowledgeApi = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  remove: vi.fn(),
  upload: vi.fn(),
  search: vi.fn(),
  pagePreview: vi.fn(),
  documentStatus: vi.fn(),
  graph: vi.fn(),
  workspace: vi.fn(),
  note: vi.fn(),
}));
const mockQuestionBankApi = vi.hoisted(() => ({
  listQuestions: vi.fn(),
  submitAttempt: vi.fn(),
  listReviewItems: vi.fn(),
  listAttemptHistory: vi.fn(),
}));
const mockClassroomApi = vi.hoisted(() => ({
  create: vi.fn(),
  join: vi.fn(),
}));
const mockBreakpoint = vi.hoisted(() => ({
  value: "desktop" as "desktop" | "tablet" | "compact" | "mobile",
}));
const mockAgentPanel = vi.hoisted(() => ({
  citation: {
    spaceId: "class-space",
    knowledgeBaseId: "kb-functions",
    vaultFileId: "file-function",
    path: "概念/函数.md",
    heading: "定义",
  },
  runtimeUnavailable: false,
}));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});
vi.mock("@/lib/question-bank-api", () => ({ questionBankApi: mockQuestionBankApi }));
vi.mock("@/lib/classrooms-api", () => ({ classroomApi: mockClassroomApi }));
vi.mock("./use-workspace-breakpoint", () => ({
  useWorkspaceBreakpoint: () => mockBreakpoint.value,
}));
vi.mock("./agent-panel", () => ({
  AgentPanel: ({
    contextLabel,
    knowledgeBase,
    onOpenCitation,
  }: {
    contextLabel: string;
    knowledgeBase: KnowledgeBase;
    onOpenCitation: (citation: typeof mockAgentPanel.citation) => void;
  }) => (
    <section aria-label="Workspace Agent" role="region">
      <p>Agent 上下文：{contextLabel}</p>
      <p>Agent 知识库：{knowledgeBase.name}</p>
      {mockAgentPanel.runtimeUnavailable ? <p role="alert">Runtime unavailable</p> : null}
      <button onClick={() => onOpenCitation(mockAgentPanel.citation)} type="button">
        打开 Agent Vault 引用
      </button>
    </section>
  ),
}));

const personalSpace = { id: "personal", kind: "personal" as const, name: "我的空间" };
const wireless: KnowledgeBase = {
  id: "kb-wireless",
  space_id: "personal",
  name: "无线通信",
  state: "ready",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};
const digital: KnowledgeBase = {
  ...wireless,
  id: "kb-digital",
  name: "数字通信",
};
const classroomSpace = { id: "class-space", kind: "classroom" as const, name: "函数班" };
const functionsKnowledgeBase: KnowledgeBase = {
  ...wireless,
  id: "kb-functions",
  space_id: "class-space",
  name: "函数知识库",
};

beforeEach(() => {
  localStorage.clear();
  mockBreakpoint.value = "desktop";
  mockAgentPanel.runtimeUnavailable = false;
  mockAgentPanel.citation = {
    spaceId: "class-space",
    knowledgeBaseId: "kb-functions",
    vaultFileId: "file-function",
    path: "概念/函数.md",
    heading: "定义",
  };
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  for (const mock of Object.values(mockQuestionBankApi)) mock.mockReset();
  for (const mock of Object.values(mockClassroomApi)) mock.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([wireless, digital]);
  mockKnowledgeApi.remove.mockResolvedValue(undefined);
  mockKnowledgeApi.graph.mockResolvedValue({ nodes: [], edges: [] });
  mockKnowledgeApi.workspace.mockImplementation((knowledgeBaseId: string) =>
    Promise.resolve({
      knowledge_base_id: knowledgeBaseId,
      documents: [],
      candidate_batch: null,
      notes: [],
    }),
  );
  mockKnowledgeApi.note.mockResolvedValue({
    id: "note-digital",
    title: "数字调制",
    parent: null,
    markdown: "# 数字调制\n\n这是图节点对应的正式知识笔记。",
    source_document_id: null,
    source_name: "数字通信.md",
    source_markers: ["数字通信.md#数字调制"],
    updated_at: "2026-08-28T00:00:00Z",
  });
  mockQuestionBankApi.listQuestions.mockResolvedValue([]);
  mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [], next_cursor: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WorkspaceShell", () => {
  it("mounts Workspace Agent as the only AI workspace experience", async () => {
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("data-layout", "library-center-agent");
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
    expect(screen.queryByLabelText("AI 家教")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "AI 家教" })).not.toBeInTheDocument();
  });

  it("opens and reuses the requested graph tab without changing library selection", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "打开数字通信关联图" }));

    expect(screen.getByRole("tab", { name: "关联图 · 数字通信" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "选择无线通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toHaveTextContent("关联图：数字通信");

    await user.click(screen.getByRole("button", { name: "打开数字通信关联图" }));
    expect(screen.getAllByRole("tab", { name: "关联图 · 数字通信" })).toHaveLength(1);
  });

  it("clears deleted knowledge-base tabs, previews, preferences, and Agent context", async () => {
    mockAgentPanel.citation = {
      spaceId: "personal",
      knowledgeBaseId: digital.id,
      vaultFileId: "file-digital",
      path: "数字通信.md",
      heading: "调制",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            vault_file_id: "file-digital",
            relative_path: "数字通信.md",
            markdown: "# 数字通信",
          }),
      }),
    );
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "选择数字通信" }));
    await user.click(screen.getByRole("button", { name: "打开数字通信关联图" }));
    expect(screen.getByRole("tab", { name: "关联图 · 数字通信" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开 Agent Vault 引用" }));
    expect(await screen.findByRole("region", { name: "Vault 文件" })).toHaveTextContent("数字通信.md");

    await user.click(screen.getByRole("button", { name: "删除数字通信" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "输入知识库名称数字通信以确认" }),
      { target: { value: "数字通信" } },
    );
    expect(screen.getByRole("textbox", { name: "输入知识库名称数字通信以确认" })).toHaveValue("数字通信");
    expect(screen.getByRole("button", { name: "永久删除数字通信" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "永久删除数字通信" }));

    await waitFor(() =>
      expect(mockKnowledgeApi.remove).toHaveBeenCalledWith(digital.id, expect.any(AbortSignal)),
    );
    expect(screen.queryByRole("button", { name: "选择数字通信" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "关联图 · 数字通信" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Vault 文件" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择无线通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toHaveTextContent(
      "Agent 知识库：无线通信",
    );
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem("workspace:personal") ?? "null")).toMatchObject({
        selectedKnowledgeBaseId: wireless.id,
      }),
    );
    expect(localStorage.getItem("workspace:personal")).not.toContain(digital.id);
  });

  it("opens a graph from the knowledge page without embedding it below the file explorer", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(screen.getByRole("tab", { name: "知识库" }));
    await user.click(await screen.findByRole("button", { name: "打开链路图" }));

    expect(screen.getByRole("tab", { name: "关联图 · 无线通信" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByLabelText("知识关联图")).toBeInTheDocument();
    expect(screen.queryByLabelText("知识库内容层级")).not.toBeInTheDocument();
  });

  it("routes a published graph node to its formal note in the explorer", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.graph.mockResolvedValue({
      knowledge_base_id: digital.id,
      nodes: [
        {
          id: "candidate-digital",
          note_id: "note-digital",
          title: "数字调制",
          kind: "concept",
          source_pointers: ["数字通信.md#数字调制"],
        },
      ],
      edges: [],
    });
    mockKnowledgeApi.workspace.mockImplementation((knowledgeBaseId: string) =>
      Promise.resolve({
        knowledge_base_id: knowledgeBaseId,
        documents: [],
        candidate_batch: null,
        notes:
          knowledgeBaseId === digital.id
            ? [
                {
                  id: "note-digital",
                  title: "数字调制",
                  parent_id: null,
                  source_document_id: null,
                  source_name: "数字通信.md",
                  updated_at: "2026-08-28T00:00:00Z",
                },
              ]
            : [],
      }),
    );

    render(<WorkspaceShell spaces={[personalSpace]} />);
    await user.click(await screen.findByRole("button", { name: "打开数字通信关联图" }));
    await user.click(await screen.findByRole("button", { name: "数字调制" }));

    expect(screen.getByRole("tab", { name: "知识库" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "选择数字通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("heading", { name: "数字调制" })).toBeInTheDocument();
    expect(mockKnowledgeApi.note).toHaveBeenCalledWith(
      digital.id,
      "note-digital",
      expect.any(AbortSignal),
    );
  });
  it("returns an empty graph to candidate review for the graph knowledge base", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "打开数字通信关联图" }));
    await user.click(await screen.findByRole("button", { name: "审核候选内容" }));

    expect(screen.getByRole("tab", { name: "知识库" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByLabelText("知识库面板")).toHaveTextContent("数字通信");
    expect(screen.getByRole("button", { name: "选择数字通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("switches central tabs while keeping the selected knowledge base controlled by the shell", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await screen.findByRole("button", { name: "选择无线通信" });
    await user.click(screen.getByRole("tab", { name: "知识库" }));
    expect(await screen.findByLabelText("知识库面板")).toHaveTextContent("无线通信");

    await user.click(screen.getByRole("button", { name: "选择数字通信" }));
    expect(screen.getByLabelText("知识库面板")).toHaveTextContent("数字通信");

    await user.click(screen.getByRole("tab", { name: "题库练习" }));
    expect(await screen.findByLabelText("题库练习面板")).toBeInTheDocument();
  });

  it("renders three keyboard-resizable desktop panes", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(400);
    render(<WorkspaceShell spaces={[personalSpace]} />);
    await screen.findByRole("navigation", { name: "知识库" });

    const separators = screen.getAllByRole("separator");
    expect(separators).toHaveLength(2);
    const firstSeparator = separators[0];
    expect(firstSeparator).toHaveAttribute("tabindex", "0");
    const initialValue = Number(firstSeparator.getAttribute("aria-valuenow"));
    firstSeparator.focus();
    await user.keyboard("{ArrowRight}");
    expect(Number(firstSeparator.getAttribute("aria-valuenow"))).toBeGreaterThan(initialValue);
  });

  it("restores the selected knowledge base and active tab for each space", async () => {
    localStorage.setItem(
      "workspace:personal",
      JSON.stringify({ selectedKnowledgeBaseId: "kb-digital", activeTabId: "knowledge" }),
    );
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await screen.findByRole("button", { name: "选择数字通信" });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "选择数字通信" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(screen.getByRole("tab", { name: "知识库" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
    expect(await screen.findByLabelText("知识库面板")).toHaveTextContent("数字通信");
  });


  it("uses accessible library drawers in compact layouts without losing selection", async () => {
    mockBreakpoint.value = "compact";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(screen.getByRole("main")).toHaveAttribute("data-layout", "center-drawers");
    expect(screen.queryByRole("navigation", { name: "知识库" })).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: "打开知识库" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "知识库抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭知识库抽屉" })).toHaveFocus();

    await user.click(await screen.findByRole("button", { name: "选择数字通信" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "知识库抽屉" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    expect(screen.getByRole("button", { name: "选择数字通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await user.click(screen.getByRole("button", { name: "关闭知识库抽屉背景" }));
    expect(screen.queryByRole("dialog", { name: "知识库抽屉" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("uses an accessible Workspace Agent drawer in compact layouts", async () => {
    mockBreakpoint.value = "compact";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    const trigger = screen.getByRole("button", { name: "打开 Workspace Agent" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Workspace Agent 抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭 Workspace Agent 抽屉" })).toHaveFocus();
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "关闭 Workspace Agent 抽屉" }));
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "关闭 Workspace Agent 抽屉背景" }));
    expect(trigger).toHaveFocus();
  });

  it("keeps the library inline and moves only Workspace Agent into a tablet drawer", async () => {
    mockBreakpoint.value = "tablet";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开知识库" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "打开 Workspace Agent" }));
    expect(screen.getByRole("dialog", { name: "Workspace Agent 抽屉" })).toBeInTheDocument();
  });

  it("keeps the real classroom entry in the knowledge sidebar footer", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "创建或加入班级" }));
    expect(screen.getByRole("dialog", { name: "创建或加入班级" })).toBeInTheDocument();
    expect(screen.getByLabelText("班级名称")).toBeInTheDocument();
    expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
  });
  it.each(["tablet", "compact"] as const)(
    "opens Workspace Agent as the only assistant inside the %s drawer",
    async (breakpoint) => {
      mockBreakpoint.value = breakpoint;
      const user = userEvent.setup();
      render(<WorkspaceShell spaces={[personalSpace]} />);

      const trigger = await screen.findByRole("button", { name: "打开 Workspace Agent" });
      await user.click(trigger);
      expect(screen.getByRole("dialog", { name: "Workspace Agent 抽屉" })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
      expect(screen.queryByText("AI 家教")).not.toBeInTheDocument();
    },
  );

  it("opens an Agent Vault citation after switching space and loading its knowledge base", async () => {
    mockKnowledgeApi.list.mockImplementation((spaceId: string) =>
      Promise.resolve(spaceId === "class-space" ? [functionsKnowledgeBase] : [wireless, digital]),
    );
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        vault_file_id: "file-function",
        relative_path: "概念/函数.md",
        markdown: "# 函数\n\n函数是集合之间的映射。",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    await user.click(await screen.findByRole("button", { name: "打开 Agent Vault 引用" }));

    await waitFor(() => expect(mockKnowledgeApi.list).toHaveBeenCalledWith(
      "class-space",
      expect.any(AbortSignal),
    ));
    expect(await screen.findByRole("button", { name: "选择函数知识库" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/knowledge-bases/kb-functions/vault/files/file-function"),
      expect.objectContaining({ credentials: "include" }),
    ));
    expect(await screen.findByRole("region", { name: "Vault 文件" })).toHaveTextContent(
      "函数是集合之间的映射。",
    );
    expect(screen.getByRole("region", { name: "Vault 文件" })).toHaveTextContent("概念/函数.md");
  });

  it("shows only a generic unavailable message when a Vault citation fails ACL", async () => {
    mockKnowledgeApi.list.mockImplementation((spaceId: string) =>
      Promise.resolve(spaceId === "class-space" ? [functionsKnowledgeBase] : [wireless, digital]),
    );
    mockAgentPanel.citation = {
      ...mockAgentPanel.citation,
      path: "机密/不可见方案.md",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace, classroomSpace]} />);

    await user.click(await screen.findByRole("button", { name: "打开 Agent Vault 引用" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("资源不可用");
    expect(screen.queryByText(/机密\/不可见方案/)).not.toBeInTheDocument();
  });

  it("keeps knowledge workspace controls usable when Agent Runtime returns 503", async () => {
    mockAgentPanel.runtimeUnavailable = true;
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Runtime unavailable");
    await user.click(screen.getByRole("tab", { name: "知识库" }));
    expect(await screen.findByLabelText("知识库面板")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Workspace Agent" })).toBeInTheDocument();
    expect(screen.queryByText("AI 家教")).not.toBeInTheDocument();
  });

});
