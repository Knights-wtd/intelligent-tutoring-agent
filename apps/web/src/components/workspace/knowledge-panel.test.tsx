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
  ingestion_job_id: "job-1",
  space_id: "space-math",
  knowledge_base_id: "kb-math",
  source_name: "chapter.md",
  version_number: 1,
  content_sha256: "digest",
  content_type: "text/markdown",
  document_state: "PROCESSING",
  version_state: "UPLOADED",
  job_state: "PENDING",
  created_at: "2026-08-18T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([knowledgeBase]);
});

describe("KnowledgePanel", () => {
  it("loads space-scoped knowledge bases and displays the learner hierarchy", async () => {
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);

    expect(await screen.findByRole("button", { name: "七年级数学" })).toBeInTheDocument();
    expect(mockKnowledgeApi.list).toHaveBeenCalledWith("space-math", expect.any(AbortSignal));

    const hierarchy = screen.getByLabelText("知识库内容层级");
    expect(within(hierarchy).getByText("知识库")).toBeInTheDocument();
    expect(within(hierarchy).getByText("教材/练习")).toBeInTheDocument();
    expect(within(hierarchy).getByText("文件")).toBeInTheDocument();
    expect(hierarchy).toHaveTextContent("当前知识库：七年级数学");
    expect(hierarchy).toHaveTextContent("尚未上传文件");
    expect(hierarchy).not.toHaveTextContent(/OCR|embedding|worker|job/i);
  });

  it("creates a knowledge base with a bounded learner-facing name", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.create.mockResolvedValue({ ...knowledgeBase, id: "kb-new", name: "几何练习" });
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

    await user.type(screen.getByLabelText("知识库名称"), "  几何练习  ");
    await user.click(screen.getByRole("button", { name: "创建知识库" }));

    expect(mockKnowledgeApi.create).toHaveBeenCalledWith(
      "space-math",
      "几何练习",
      expect.any(AbortSignal),
    );
    expect(await screen.findByRole("button", { name: "几何练习" })).toBeInTheDocument();
  });

  it("shows truthful bounded upload state, then a ready file state", async () => {
    const user = userEvent.setup();
    let resolveUpload: (value: ReturnType<typeof uploadResponse>) => void = () => undefined;
    mockKnowledgeApi.upload.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

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
      resolveUpload(uploadResponse({ document_state: "READY", version_state: "READY", job_state: "COMPLETED" }));
    });

    const hierarchy = screen.getByLabelText("知识库内容层级");
    expect(hierarchy).toHaveTextContent("chapter.md");
    expect(hierarchy).toHaveTextContent("可搜索");
  });

  it("keeps a newly accepted active document in processing until its version completes", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(
      uploadResponse({ document_state: "ACTIVE", version_state: "UPLOADED", job_state: "QUEUED" }),
    );
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

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
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "failed.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    expect(await screen.findByText("上传失败，请重试。")).toBeInTheDocument();
    expect(screen.queryByText(/provider|credentials|s3:\/\//i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试上传" }));

    expect(mockKnowledgeApi.upload).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("处理中")).toBeInTheDocument();
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
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

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

  it("keeps a failed knowledge request retryable", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.list
      .mockRejectedValueOnce(new Error("not for display"))
      .mockResolvedValueOnce([knowledgeBase]);
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);

    expect(await screen.findByText("知识库暂时无法加载。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试知识库" }));

    expect(await screen.findByRole("button", { name: "七年级数学" })).toBeInTheDocument();
    expect(mockKnowledgeApi.list).toHaveBeenCalledTimes(2);
  });

  it("ignores a stale response after the active space changes", async () => {
    let resolveOld: (value: Array<typeof knowledgeBase>) => void = () => undefined;
    mockKnowledgeApi.list
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
      )
      .mockResolvedValueOnce([{ ...knowledgeBase, id: "kb-science", name: "科学资料", space_id: "space-science" }]);
    const { rerender } = render(
      <KnowledgePanel spaceId="space-math" spaceName="数学空间" />,
    );

    rerender(<KnowledgePanel spaceId="space-science" spaceName="科学空间" />);
    expect(await screen.findByRole("button", { name: "科学资料" })).toBeInTheDocument();

    await act(async () => {
      resolveOld([knowledgeBase]);
    });

    expect(screen.queryByRole("button", { name: "七年级数学" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "科学资料" })).toBeInTheDocument();
  });

  it("shows a learner-facing failed state returned by the upload endpoint", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.upload.mockResolvedValue(
      uploadResponse({ document_state: "FAILED", version_state: "FAILED", job_state: "FAILED" }),
    );
    render(<KnowledgePanel spaceId="space-math" spaceName="七年级数学空间" />);
    await screen.findByRole("button", { name: "七年级数学" });

    await user.upload(
      screen.getByLabelText("选择学习资料"),
      new File(["content"], "broken.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "上传文件" }));

    expect(await screen.findByText("处理失败")).toBeInTheDocument();
    expect(screen.queryByText(/worker|job|embedding|OCR/i)).not.toBeInTheDocument();
  });
});
