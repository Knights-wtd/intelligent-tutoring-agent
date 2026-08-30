import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeBase, KnowledgeNoteDetail } from "@/lib/knowledge-api";

import { KnowledgeExplorer } from "./knowledge-explorer";

const mockKnowledgeApi = vi.hoisted(() => ({ note: vi.fn() }));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: { ...actual.knowledgeApi, note: mockKnowledgeApi.note } };
});

const knowledgeBase: KnowledgeBase = {
  id: "kb-1",
  space_id: "space-1",
  name: "Faro 教程",
  state: "active",
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
};

beforeEach(() => mockKnowledgeApi.note.mockReset());

describe("KnowledgeExplorer", () => {
  it("shows knowledge notes and source documents as two explorer roots", () => {
    render(
      <KnowledgeExplorer
        documents={[
          {
            document_id: "doc-1",
            document_version_id: "version-1",
            source_name: "Faro_API_小白使用教程.docx",
            content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            processing_state: "searchable",
            created_at: "2026-08-28T00:00:00Z",
            updated_at: "2026-08-28T00:00:00Z",
          },
        ]}
        knowledgeBase={knowledgeBase}
        notes={[
          {
            id: "parent",
            title: "Faro 配置",
            kind: "note",
            parent_id: null,
            source_document_id: "doc-1",
            updated_at: "2026-08-28T00:00:00Z",
          },
          {
            id: "child",
            title: "配置文件位置",
            kind: "note",
            parent_id: "parent",
            source_document_id: "doc-1",
            updated_at: "2026-08-28T00:00:00Z",
          },
        ]}
      />,
    );

    const tree = screen.getByRole("tree", { name: "知识库内容层级" });
    expect(within(tree).getByText("知识笔记")).toBeInTheDocument();
    expect(within(tree).getByText("原始资料")).toBeInTheDocument();
    expect(within(tree).getByText("Faro 配置.md")).toBeInTheDocument();
    expect(within(tree).getByText("配置文件位置.md")).toBeInTheDocument();
    expect(within(tree).getByText("Faro_API_小白使用教程.docx")).toBeInTheDocument();
    expect(within(tree).getByText("可搜索")).toBeInTheDocument();
    expect(mockKnowledgeApi.note).not.toHaveBeenCalled();
  });

  it("loads note body only after selection and shows source metadata", async () => {
    const user = userEvent.setup();
    const detail: KnowledgeNoteDetail = {
      id: "note-1",
      title: "配置文件位置",
      kind: "note",
      markdown: "# 配置文件位置\n\n这是正文。",
      source_markers: ["Faro_API_小白使用教程.docx#block=20"],
      source_document_id: "doc-1",
      source_name: "Faro_API_小白使用教程.docx",
      parent: { id: "parent", title: "Faro 配置" },
      children: [],
      updated_at: "2026-08-28T08:00:00Z",
    };
    mockKnowledgeApi.note.mockResolvedValue(detail);
    render(
      <KnowledgeExplorer
        documents={[]}
        knowledgeBase={knowledgeBase}
        notes={[
          {
            id: "note-1",
            title: "配置文件位置",
            kind: "note",
            parent_id: "parent",
            source_document_id: "doc-1",
            updated_at: "2026-08-28T08:00:00Z",
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "打开知识笔记：配置文件位置" }));

    expect(mockKnowledgeApi.note).toHaveBeenCalledWith("kb-1", "note-1", expect.any(AbortSignal));
    const viewer = await screen.findByRole("region", { name: "知识文件查看器" });
    expect(viewer).toHaveTextContent("Faro 配置 / 配置文件位置");
    expect(viewer).toHaveTextContent("这是正文");
    expect(viewer).toHaveTextContent("Faro_API_小白使用教程.docx#block=20");
  });

  it("explains that a parsed DOCX is available to search and Tutor", async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeExplorer
        documents={[
          {
            document_id: "doc-1",
            document_version_id: "version-1",
            source_name: "wireless.docx",
            content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            processing_state: "searchable",
            created_at: "2026-08-28T00:00:00Z",
            updated_at: "2026-08-28T00:00:00Z",
          },
        ]}
        knowledgeBase={knowledgeBase}
        notes={[]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "打开原始资料：wireless.docx" }));

    expect(screen.getByRole("region", { name: "知识文件查看器" })).toHaveTextContent(
      "已完成解析，可供知识库搜索和 AI 助教使用",
    );
  });
});

describe("KnowledgeExplorer folders and document actions", () => {
  const searchableDocument = {
    document_id: "doc-1",
    document_version_id: "version-1",
    source_name: "Faro_API_小白使用教程.docx",
    content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    processing_state: "searchable" as const,
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
  };
  const parentNote = {
    id: "parent",
    title: "Faro 配置",
    kind: "note",
    parent_id: null,
    source_document_id: "doc-1",
    updated_at: "2026-08-28T00:00:00Z",
  };
  const childNote = {
    id: "child",
    title: "配置文件位置",
    kind: "note",
    parent_id: "parent",
    source_document_id: "doc-1",
    updated_at: "2026-08-28T00:00:00Z",
  };

  it("shows refresh and generate-candidate actions on source document rows, generate below refresh", async () => {
    const user = userEvent.setup();
    const onRefreshDocument = vi.fn();
    const onGenerateCandidates = vi.fn();
    render(
      <KnowledgeExplorer
        documents={[searchableDocument]}
        documentRefreshStates={{}}
        isGeneratingCandidates={false}
        knowledgeBase={knowledgeBase}
        notes={[]}
        onGenerateCandidates={onGenerateCandidates}
        onRefreshDocument={onRefreshDocument}
      />,
    );

    const refresh = screen.getByRole("button", { name: "刷新处理状态" });
    const generate = screen.getByRole("button", { name: "生成知识候选" });
    expect(refresh.compareDocumentPosition(generate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(refresh);
    await user.click(generate);
    expect(onRefreshDocument).toHaveBeenCalledWith(searchableDocument);
    expect(onGenerateCandidates).toHaveBeenCalledWith(searchableDocument);
  });

  it("disables candidate generation while a batch is being generated", () => {
    render(
      <KnowledgeExplorer
        documents={[searchableDocument]}
        isGeneratingCandidates
        knowledgeBase={knowledgeBase}
        notes={[]}
        onGenerateCandidates={vi.fn()}
        onRefreshDocument={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "生成中…" })).toBeDisabled();
  });

  it("hides duplicate document actions for documents represented in the session task list", () => {
    render(
      <KnowledgeExplorer
        documents={[searchableDocument]}
        knowledgeBase={knowledgeBase}
        notes={[]}
        onGenerateCandidates={vi.fn()}
        onRefreshDocument={vi.fn()}
        suppressActionDocumentIds={["doc-1"]}
      />,
    );
    expect(screen.queryByRole("button", { name: "刷新处理状态" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成知识候选" })).not.toBeInTheDocument();
  });

  it("collapses and re-expands the notes folder", async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeExplorer
        documents={[]}
        knowledgeBase={knowledgeBase}
        notes={[parentNote, childNote]}
      />,
    );

    expect(screen.getByText("Faro 配置.md")).toBeInTheDocument();
    const notesToggle = screen.getByRole("button", { name: "知识笔记" });
    expect(notesToggle).toHaveAttribute("aria-expanded", "true");
    await user.click(notesToggle);
    expect(notesToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Faro 配置.md")).not.toBeInTheDocument();

    await user.click(notesToggle);
    expect(screen.getByText("Faro 配置.md")).toBeInTheDocument();
  });

  it("collapses and re-expands a parent note's children", async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeExplorer
        documents={[]}
        knowledgeBase={knowledgeBase}
        notes={[parentNote, childNote]}
      />,
    );

    const collapseToggle = screen.getByRole("button", { name: "收起子级笔记：Faro 配置" });
    expect(screen.getByText("配置文件位置.md")).toBeInTheDocument();
    await user.click(collapseToggle);
    expect(screen.queryByText("配置文件位置.md")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "展开子级笔记：Faro 配置" }));
    expect(screen.getByText("配置文件位置.md")).toBeInTheDocument();
  });

  it("collapses the source documents folder", async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeExplorer documents={[searchableDocument]} knowledgeBase={knowledgeBase} notes={[]} />,
    );

    const documentsToggle = screen.getByRole("button", { name: "原始资料" });
    expect(documentsToggle).toHaveAttribute("aria-expanded", "true");
    await user.click(documentsToggle);
    expect(screen.queryByText("Faro_API_小白使用教程.docx")).not.toBeInTheDocument();
  });
});
