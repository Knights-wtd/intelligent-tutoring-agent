import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeBase } from "@/lib/knowledge-api";

import { WorkspaceShell } from "./workspace-shell";

const mockKnowledgeApi = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
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
const mockTutorApi = vi.hoisted(() => ({
  status: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  sendMessage: vi.fn(),
}));
const mockBreakpoint = vi.hoisted(() => ({
  value: "desktop" as "desktop" | "tablet" | "compact" | "mobile",
}));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});
vi.mock("@/lib/question-bank-api", () => ({ questionBankApi: mockQuestionBankApi }));
vi.mock("@/lib/classrooms-api", () => ({ classroomApi: mockClassroomApi }));
vi.mock("@/lib/tutor-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/tutor-api")>();
  return { ...actual, tutorApi: mockTutorApi };
});
vi.mock("./use-workspace-breakpoint", () => ({
  useWorkspaceBreakpoint: () => mockBreakpoint.value,
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

beforeEach(() => {
  localStorage.clear();
  mockBreakpoint.value = "desktop";
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  for (const mock of Object.values(mockQuestionBankApi)) mock.mockReset();
  for (const mock of Object.values(mockClassroomApi)) mock.mockReset();
  for (const mock of Object.values(mockTutorApi)) mock.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([wireless, digital]);
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
  mockTutorApi.status.mockResolvedValue({ configured: false, model: "" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkspaceShell", () => {
  it("renders knowledge bases at far left and the tutor at right", async () => {
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("data-layout", "library-center-tutor");
    expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();
    expect(screen.queryByText("服务正常")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("MVP 功能说明")).not.toBeInTheDocument();
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
    expect(screen.getByLabelText("AI 家教")).toHaveTextContent("关联图：数字通信");

    await user.click(screen.getByRole("button", { name: "打开数字通信关联图" }));
    expect(screen.getAllByRole("tab", { name: "关联图 · 数字通信" })).toHaveLength(1);
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

  it("keeps tutor draft state mounted while its compact drawer is closed", async () => {
    mockBreakpoint.value = "compact";
    mockTutorApi.status.mockResolvedValue({ configured: true, model: "faro" });
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    const trigger = screen.getByRole("button", { name: "打开 AI 家教" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "AI 家教抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭 AI 家教抽屉" })).toHaveFocus();

    const prompt = await screen.findByLabelText("向 AI 导师提问");
    await waitFor(() => expect(prompt).toBeEnabled());
    await user.type(prompt, "请解释香农定理");
    await user.click(screen.getByRole("button", { name: "关闭 AI 家教抽屉" }));
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    expect(screen.getByLabelText("向 AI 导师提问")).toHaveValue("请解释香农定理");
    await user.click(screen.getByRole("button", { name: "关闭 AI 家教抽屉背景" }));
    expect(trigger).toHaveFocus();
  });

  it("keeps the library inline and moves only the tutor into a tablet drawer", async () => {
    mockBreakpoint.value = "tablet";
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开知识库" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "打开 AI 家教" }));
    expect(screen.getByRole("dialog", { name: "AI 家教抽屉" })).toBeInTheDocument();
  });

  it("keeps the real classroom entry in the knowledge sidebar footer", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "创建或加入班级" }));
    expect(screen.getByRole("dialog", { name: "创建或加入班级" })).toBeInTheDocument();
    expect(screen.getByLabelText("班级名称")).toBeInTheDocument();
    expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
  });
  it("opens a Tutor citation in the matching knowledge preview", async () => {
    mockBreakpoint.value = "compact";
    mockTutorApi.status.mockResolvedValue({ configured: true, model: "faro" });
    mockTutorApi.createConversation.mockResolvedValue({
      id: "conversation-1",
      knowledge_base_id: "kb-wireless",
      title: "路径损耗",
      messages: [
        {
          id: "message-user",
          role: "user",
          content: "解释路径损耗",
          citations: [],
          created_at: "2026-08-26T00:00:00Z",
        },
        {
          id: "message-assistant",
          role: "assistant",
          content: "路径损耗随距离增加而增大。",
          citations: [
            {
              id: "citation-wireless",
              source_name: "无线通信.txt",
              page_number: 1,
            },
          ],
          created_at: "2026-08-26T00:00:01Z",
        },
      ],
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:01Z",
    });
    mockKnowledgeApi.pagePreview.mockResolvedValue({
      blob: new Blob(["路径损耗随距离增加而增大。"], { type: "text/plain" }),
      contentType: "text/plain; charset=utf-8",
    });
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await waitFor(() => {
      expect(localStorage.getItem("workspace:personal")).not.toBeNull();
    });
    await new Promise((resolve) => setTimeout(resolve, 100));
    await user.click(screen.getByRole("button", { name: "打开 AI 家教" }));
    const prompt = screen.getByLabelText("向 AI 导师提问");
    await waitFor(() => expect(prompt).toBeEnabled());
    const form = prompt.closest("form");
    expect(form).not.toBeNull();
    fireEvent.change(prompt, { target: { value: "解释路径损耗" } });
    expect(prompt).toHaveValue("解释路径损耗");
    fireEvent.submit(form!);
    await waitFor(() => {
      expect(mockTutorApi.createConversation).toHaveBeenCalledWith(
        "kb-wireless",
        "解释路径损耗",
        expect.any(AbortSignal),
      );
    });
    expect(await screen.findByText("路径损耗随距离增加而增大。")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "打开引用：无线通信.txt，第 1 页" }));
    expect(screen.queryByRole("dialog", { name: "AI 家教抽屉" })).not.toBeInTheDocument();

    expect(screen.getByRole("tab", { name: "知识库" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => {
      expect(mockKnowledgeApi.pagePreview).toHaveBeenCalledWith(
        "kb-wireless",
        "citation-wireless",
        expect.any(AbortSignal),
      );
    });
    expect(await screen.findByRole("region", { name: "引用原页预览" })).toHaveTextContent(
      "路径损耗随距离增加而增大。",
    );

    await user.click(screen.getByRole("tab", { name: "今日任务" }));
    await user.click(screen.getByRole("tab", { name: "知识库" }));
    expect(mockKnowledgeApi.pagePreview).toHaveBeenCalledTimes(1);
  });
});
