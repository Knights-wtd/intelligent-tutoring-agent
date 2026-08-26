import { render, screen, waitFor } from "@testing-library/react";
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
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  for (const mock of Object.values(mockQuestionBankApi)) mock.mockReset();
  for (const mock of Object.values(mockClassroomApi)) mock.mockReset();
  for (const mock of Object.values(mockTutorApi)) mock.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([wireless, digital]);
  mockKnowledgeApi.graph.mockResolvedValue({ nodes: [], edges: [] });
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

  it("keeps the real classroom entry in the knowledge sidebar footer", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell spaces={[personalSpace]} />);

    await user.click(await screen.findByRole("button", { name: "创建或加入班级" }));
    expect(screen.getByRole("dialog", { name: "创建或加入班级" })).toBeInTheDocument();
    expect(screen.getByLabelText("班级名称")).toBeInTheDocument();
    expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
  });
});
