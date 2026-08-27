import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgePanel } from "./knowledge-panel";

const mockKnowledgeApi = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  upload: vi.fn(),
  search: vi.fn(),
  pagePreview: vi.fn(),
  startCandidateGeneration: vi.fn(),
  candidateBatch: vi.fn(),
  confirmCandidateBatch: vi.fn(),
  documentStatus: vi.fn(),
}));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});

const knowledgeBase = {
  id: "kb-math",
  space_id: "space-math",
  name: "七年级数学",
  state: "ACTIVE",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
};

const uploadResponse = (overrides: Record<string, string> = {}) => ({
  document_id: "doc-1",
  document_version_id: "version-1",
  source_name: "chapter.md",
  created_at: "2026-08-18T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
});

describe("KnowledgePanel", () => {
  it("uses the shell-controlled knowledge base and displays the learner hierarchy", () => {
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    expect(mockKnowledgeApi.list).not.toHaveBeenCalled();
    expect(mockKnowledgeApi.create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("知识库面板")).toHaveTextContent("七年级数学空间");
    expect(screen.queryByLabelText("知识库名称")).not.toBeInTheDocument();

    const hierarchy = screen.getByLabelText("知识库内容层级");
    expect(within(hierarchy).getByText("知识库")).toBeInTheDocument();
    expect(within(hierarchy).getByText("教材/练习")).toBeInTheDocument();
    expect(within(hierarchy).getByText("文件")).toBeInTheDocument();
    expect(hierarchy).toHaveTextContent("当前知识库：七年级数学");
    expect(hierarchy).toHaveTextContent("尚未上传文件");
    expect(hierarchy).not.toHaveTextContent(/OCR|embedding|worker|job/i);
  });

  it("shows truthful bounded upload state, then a ready file state", async () => {
    const user = userEvent.setup();
    let resolveUpload: (value: ReturnType<typeof uploadResponse>) => void = () => undefined;
    mockKnowledgeApi.upload.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    const file = new File(["# chapter"], "chapter.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText("选择学习资料"), file);
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    expect(screen.getByRole("status")).toHaveTextContent("正在上传 chapter.md");
    expect(mockKnowledgeApi.upload).toHaveBeenCalledWith(
      "kb-math",
      file,
      expect.stringMatching(/^web-/),
      expect.any(AbortSignal),
    );

    await act(async () => {
      resolveUpload(uploadResponse());
    });

    const hierarchy = screen.getByLabelText("知识库内容层级");
    expect(hierarchy).toHaveTextContent("chapter.md");
    expect(hierarchy).toHaveTextContent("处理中");
    expect(hierarchy).not.toHaveTextContent("可搜索");
  });

  it("keeps a newly accepted active document in processing until its version completes", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(
      uploadResponse({ document_state: "ACTIVE", version_state: "UPLOADED", job_state: "QUEUED" }),
    );
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "queued.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    const hierarchy = screen.getByLabelText("知识库内容层级");
    expect(await within(hierarchy).findByText("处理中")).toBeInTheDocument();
    expect(hierarchy).not.toHaveTextContent("可搜索");
  });

  it("shows failed upload state without internal details and retries the same file", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload
      .mockRejectedValueOnce(new Error("provider credentials at s3://secret"))
      .mockResolvedValueOnce(uploadResponse());
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "failed.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    expect(await screen.findByText("上传失败，请重试。")).toBeInTheDocument();
    expect(screen.queryByText(/provider|credentials|s3:\/\//i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试上传" }));

    expect(mockKnowledgeApi.upload).toHaveBeenCalledTimes(2);
    expect(mockKnowledgeApi.upload.mock.calls[1]?.[2]).toBe(mockKnowledgeApi.upload.mock.calls[0]?.[2]);
    expect(await screen.findByText("处理中")).toBeInTheDocument();
  });

  it("allows only one active logical upload", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockReturnValue(new Promise(() => undefined));
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "single.md", { type: "text/markdown" }),
    );
    const submit = screen.getByRole("button", { name: "上传文件" });
    await user.click(submit);
    expect(submit).toBeDisabled();
    await user.click(submit);

    expect(mockKnowledgeApi.upload).toHaveBeenCalledTimes(1);
  });

  it("keeps a newer file selection when an older upload completes", async () => {
    const user = userEvent.setup();
    let resolveUpload: (value: ReturnType<typeof uploadResponse>) => void = () => undefined;
    mockKnowledgeApi.upload.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    const firstFile = new File(["first"], "first.md", { type: "text/markdown" });
    const secondFile = new File(["second"], "second.md", { type: "text/markdown" });
    const fileInput = screen.getByLabelText("选择学习资料") as HTMLInputElement;
    await user.upload(fileInput, firstFile);
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.upload(fileInput, secondFile);

    await act(async () => {
      resolveUpload(uploadResponse());
    });

    expect(fileInput.files?.[0]).toBe(secondFile);
    const submit = screen.getByRole("button", { name: "上传文件" });
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(mockKnowledgeApi.upload).toHaveBeenCalledTimes(2);
    expect(mockKnowledgeApi.upload.mock.calls[1]?.[1]).toBe(secondFile);
  });

  it("searches the selected knowledge base and opens the opaque cited page", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.search.mockResolvedValue({
      results: [
        {
          excerpt: "直角三角形两直角边平方和等于斜边平方。",
          citation: {
            id: "cite_opaque-token",
            source_name: "数学上册.pdf",
            page_number: 42,
          },
        },
      ],
    });
    mockKnowledgeApi.pagePreview.mockResolvedValue({
      blob: new Blob(["教材第 42 页内容"], { type: "text/plain" }),
      contentType: "text/plain; charset=utf-8",
    });
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.type(screen.getByLabelText("搜索知识库"), " 勾股定理 ");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    expect(mockKnowledgeApi.search).toHaveBeenCalledWith(
      "kb-math",
      "勾股定理",
      10,
      expect.any(AbortSignal),
    );
    const result = await screen.findByText(/直角三角形/);
    const resultItem = result.closest("li");
    expect(resultItem).not.toBeNull();
    expect(within(resultItem as HTMLElement).getByText("数学上册.pdf · 第 42 页")).toBeInTheDocument();
    await user.click(within(resultItem as HTMLElement).getByRole("button", { name: "打开原页" }));

    expect(mockKnowledgeApi.pagePreview).toHaveBeenCalledWith(
      "kb-math",
      "cite_opaque-token",
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("教材第 42 页内容")).toBeInTheDocument();
    expect(screen.queryByText("cite_opaque-token")).not.toBeInTheDocument();
  });

  it("aborts selected knowledge-base requests when switching knowledge bases", async () => {
    const user = userEvent.setup();
    const otherKnowledgeBase = {
      ...knowledgeBase,
      id: "kb-science",
      name: "科学资料",
    };
    let uploadSignal: AbortSignal | undefined;
    let previewSignal: AbortSignal | undefined;
    let searchSignal: AbortSignal | undefined;
    mockKnowledgeApi.upload.mockImplementation(
      (_knowledgeBaseId: string, _file: File, _idempotencyKey: string, signal: AbortSignal) => {
        uploadSignal = signal;
        return new Promise(() => undefined);
      },
    );
    mockKnowledgeApi.search
      .mockResolvedValueOnce({
        results: [
          {
            excerpt: "直角三角形两直角边平方和等于斜边平方。",
            citation: {
              id: "cite_opaque-token",
              source_name: "数学上册.pdf",
              page_number: 42,
            },
          },
        ],
      })
      .mockImplementationOnce(
        (_knowledgeBaseId: string, _query: string, _limit: number, signal: AbortSignal) => {
          searchSignal = signal;
          return new Promise(() => undefined);
        },
      );
    mockKnowledgeApi.pagePreview.mockImplementation(
      (_knowledgeBaseId: string, _citationId: string, signal: AbortSignal) => {
        previewSignal = signal;
        return new Promise(() => undefined);
      },
    );
    const { rerender } = render(
      <KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />,
    );

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "switch.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(uploadSignal).toBeDefined();

    const searchInput = screen.getByLabelText("搜索知识库");
    await user.type(searchInput, "勾股定理");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    const result = await screen.findByText(/直角三角形/);
    const resultItem = result.closest("li");
    expect(resultItem).not.toBeNull();
    await user.click(within(resultItem as HTMLElement).getByRole("button", { name: "打开原页" }));
    expect(previewSignal).toBeDefined();

    await user.clear(searchInput);
    await user.type(searchInput, "平面几何");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(previewSignal?.aborted).toBe(true);
    expect(searchSignal).toBeDefined();

    rerender(<KnowledgePanel spaceName="科学空间" knowledgeBase={otherKnowledgeBase} />);
    expect(uploadSignal?.aborted).toBe(true);
    expect(searchSignal?.aborted).toBe(true);
    expect(screen.queryByText("上传失败，请重试。")).not.toBeInTheDocument();
  });

  it("shows a learner-facing failed state only after a status refresh", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(uploadResponse());
    mockKnowledgeApi.documentStatus.mockResolvedValue({
      document_id: "doc-1",
      document_version_id: "version-1",
      processing_state: "failed",
    });
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "broken.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByText("处理中")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新处理状态" }));
    expect(await screen.findByText("处理失败")).toBeInTheDocument();
    expect(screen.queryByText(/worker|job|embedding|OCR/i)).not.toBeInTheDocument();
  });
  it("keeps concurrent status refreshes independent for different uploads", async () => {
    const user = userEvent.setup();
    const pendingStatuses = new Map<
      string,
      {
        resolve: (value: {
          document_id: string;
          document_version_id: string;
          processing_state: "processing" | "searchable" | "failed";
        }) => void;
        signal: AbortSignal;
      }
    >();
    mockKnowledgeApi.upload
      .mockResolvedValueOnce(
        uploadResponse({ document_id: "doc-1", document_version_id: "version-1", source_name: "first.md" }),
      )
      .mockResolvedValueOnce(
        uploadResponse({ document_id: "doc-2", document_version_id: "version-2", source_name: "second.md" }),
      );
    mockKnowledgeApi.documentStatus.mockImplementation(
      (_knowledgeBaseId: string, documentId: string, documentVersionId: string, signal: AbortSignal) =>
        new Promise((resolve) => {
          pendingStatuses.set(documentId, { resolve, signal });
          expect(documentVersionId).toMatch(/^version-[12]$/);
        }),
    );
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    const fileInput = screen.getByLabelText("选择学习资料");
    await user.upload(fileInput, new File(["first"], "first.md", { type: "text/markdown" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByText("first.md")).toBeInTheDocument();
    await user.upload(fileInput, new File(["second"], "second.md", { type: "text/markdown" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByText("second.md")).toBeInTheDocument();

    const refreshButtons = screen.getAllByRole("button", { name: "刷新处理状态" });
    await user.click(refreshButtons[0]);
    await user.click(refreshButtons[1]);
    expect(pendingStatuses.get("doc-1")?.signal.aborted).toBe(false);
    expect(pendingStatuses.get("doc-2")?.signal.aborted).toBe(false);

    await act(async () => {
      pendingStatuses.get("doc-1")?.resolve({
        document_id: "doc-1",
        document_version_id: "version-1",
        processing_state: "searchable",
      });
    });

    expect(screen.getByRole("button", { name: "刷新处理状态" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "刷新中…" })).toBeDisabled();
    expect(screen.getByText("可搜索")).toBeInTheDocument();
  });

  it("refreshes the post-upload status without exposing worker details", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(uploadResponse());
    mockKnowledgeApi.documentStatus.mockResolvedValue({
      document_id: "doc-1",
      document_version_id: "version-1",
      processing_state: "searchable",
    });
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["# chapter"], "chapter.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    expect(await screen.findByText("处理中")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "刷新处理状态" }));

    expect(mockKnowledgeApi.documentStatus).toHaveBeenCalledWith(
      "kb-math",
      "doc-1",
      "version-1",
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("可搜索")).toBeInTheDocument();
    expect(screen.queryByText(/worker|job|embedding|OCR|checkpoint/i)).not.toBeInTheDocument();
  });


  it("reviews structure and repeated-term links before writing formal wikilinks", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(uploadResponse());
    mockKnowledgeApi.documentStatus.mockResolvedValue({
      document_id: "doc-1",
      document_version_id: "version-1",
      processing_state: "searchable",
    });
    const batch = {
      id: "batch-1",
      document_id: "doc-1",
      document_version_id: "version-1",
      generation_number: 1,
      state: "needs_review",
      failure_code: null,
      notes: [
        {
          id: "note-chapter",
          ordinal: 0,
          candidate_key: "ch-3",
          title: "移动无线传播",
          kind: "chapter",
          parent_key: null,
          markdown: "# 移动无线传播",
          source_pointers: ["wireless#1"],
          review_state: "pending",
        },
        {
          id: "note-term",
          ordinal: 1,
          candidate_key: "term-path-loss",
          title: "路径损耗",
          kind: "concept",
          parent_key: "ch-3",
          markdown: "# 路径损耗",
          source_pointers: ["wireless#2"],
          review_state: "pending",
        },
      ],
      links: [
        {
          id: "link-structure",
          ordinal: 0,
          kind: "structure",
          relation: "defines",
          source_key: "ch-3",
          target_key: "term-path-loss",
          source_pointer: "wireless#2",
          occurrence: "路径损耗",
          context: "章节定义概念",
          review_state: "pending",
        },
        {
          id: "link-term",
          ordinal: 1,
          kind: "term",
          relation: "mentions",
          source_key: "ch-3",
          target_key: "term-path-loss",
          source_pointer: "wireless#2",
          occurrence: "路径损耗",
          context: "术语出现",
          review_state: "pending",
        },
      ],
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z",
    };
    mockKnowledgeApi.startCandidateGeneration.mockResolvedValue(batch);
    mockKnowledgeApi.confirmCandidateBatch.mockResolvedValue({
      ...batch,
      state: "confirmed",
    });
    render(<KnowledgePanel spaceName="七年级数学空间" knowledgeBase={knowledgeBase} />);

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["# chapter"], "chapter.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.click(await screen.findByRole("button", { name: "刷新处理状态" }));
    await screen.findByText("可搜索");
    await user.click(screen.getByRole("button", { name: "生成知识候选" }));

    expect(await screen.findByRole("heading", { name: "结构候选" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "重复术语链接" })).toBeInTheDocument();
    expect(screen.getByText("路径损耗")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "确认并生成层级知识库" }));

    expect(mockKnowledgeApi.confirmCandidateBatch).toHaveBeenCalledWith(
      "kb-math",
      "batch-1",
      ["note-chapter", "note-term"],
      ["link-structure", "link-term"],
    );
    expect(await screen.findByText("已写入正式知识库")).toBeInTheDocument();
  });
});
