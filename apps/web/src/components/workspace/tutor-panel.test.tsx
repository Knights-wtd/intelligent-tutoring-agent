import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TutorApiError, type TutorConversation } from "@/lib/tutor-api";
import { TutorPanel } from "./tutor-panel";

const mockTutorApi = vi.hoisted(() => ({
  status: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  sendMessage: vi.fn(),
}));

vi.mock("@/lib/tutor-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tutor-api")>()),
  tutorApi: mockTutorApi,
}));

const citation = { id: "cite-1", source_name: "数学教材.pdf", page_number: 42 };
const created: TutorConversation = {
  id: "conversation-1",
  knowledge_base_id: "kb-1",
  title: "勾股定理",
  messages: [
    { id: "message-1", role: "user", content: "什么是勾股定理？", citations: [], created_at: "2026-08-25T00:00:00Z" },
    { id: "message-2", role: "assistant", content: "直角三角形三边满足关系。", citations: [citation], created_at: "2026-08-25T00:00:01Z" },
  ],
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:01Z",
};

beforeEach(() => {
  Object.values(mockTutorApi).forEach((mock) => mock.mockReset());
  mockTutorApi.status.mockResolvedValue({ configured: true, model: "faro-mini" });
});

describe("TutorPanel", () => {
  it("loads status once, creates a conversation, renders messages and opens citations", async () => {
    const user = userEvent.setup();
    const onOpenCitation = vi.fn();
    mockTutorApi.createConversation.mockResolvedValue(created);
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} contextLabel="勾股定理" onOpenCitation={onOpenCitation} />);

    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "什么是勾股定理？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(mockTutorApi.status).toHaveBeenCalledTimes(1);
    expect(mockTutorApi.createConversation).toHaveBeenCalledWith("kb-1", "什么是勾股定理？", expect.any(AbortSignal));
    const messages = await screen.findByRole("list", { name: "导师对话" });
    expect(within(messages).getByText("什么是勾股定理？")).toBeInTheDocument();
    expect(within(messages).getByText("直角三角形三边满足关系。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开引用：数学教材.pdf，第 42 页" }));
    expect(onOpenCitation).toHaveBeenCalledWith(citation);
    expect(mockTutorApi.status).toHaveBeenCalledTimes(1);
  });

  it("does not create a conversation when the provider is unconfigured", async () => {
    mockTutorApi.status.mockResolvedValue({ configured: false, model: "faro-mini" });
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("模型待配置"));
    expect(screen.getByRole("textbox", { name: "向 AI 导师提问" })).toBeDisabled();
    expect(mockTutorApi.createConversation).not.toHaveBeenCalled();
  });

  it("sends later prompts through the existing conversation without reloading status", async () => {
    const user = userEvent.setup();
    mockTutorApi.createConversation.mockResolvedValue(created);
    mockTutorApi.sendMessage.mockResolvedValue({ ...created, messages: [...created.messages, { id: "message-3", role: "user", content: "继续", citations: [], created_at: "2026-08-25T00:00:02Z" }] });
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });

    await user.type(input, "什么是勾股定理？");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("直角三角形三边满足关系。");
    await user.type(input, "继续");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(mockTutorApi.sendMessage).toHaveBeenCalledWith("kb-1", "conversation-1", "继续", expect.any(AbortSignal));
    expect(mockTutorApi.status).toHaveBeenCalledTimes(1);
  });

  it("keeps a conversation when only the context label changes", async () => {
    const user = userEvent.setup();
    mockTutorApi.createConversation.mockResolvedValue(created);
    mockTutorApi.sendMessage.mockResolvedValue(created);
    const props = { knowledgeBase: { id: "kb-1", name: "七年级数学" }, onOpenCitation: vi.fn() };
    const { rerender } = render(<TutorPanel {...props} contextLabel="第一节" />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "初次问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("直角三角形三边满足关系。");

    rerender(<TutorPanel {...props} contextLabel="第二节" />);
    expect(screen.getByText("当前上下文：第二节")).toBeInTheDocument();
    await user.type(input, "后续问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(mockTutorApi.sendMessage).toHaveBeenCalledWith("kb-1", "conversation-1", "后续问题", expect.any(AbortSignal));
  });

  it("aborts old work, clears the conversation on knowledge-base change, and ignores stale results", async () => {
    let firstSignal: AbortSignal | undefined;
    let resolveFirst!: (value: TutorConversation) => void;
    mockTutorApi.createConversation.mockImplementation((_kb: string, _prompt: string, signal: AbortSignal) => {
      firstSignal = signal;
      return new Promise<TutorConversation>((resolve) => { resolveFirst = resolve; });
    });
    const { rerender } = render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "旧库" }} contextLabel="旧章节" onOpenCitation={vi.fn()} />);
    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "旧问题");
    await user.click(screen.getByRole("button", { name: "发送" }));

    rerender(<TutorPanel knowledgeBase={{ id: "kb-2", name: "新库" }} contextLabel="新章节" onOpenCitation={vi.fn()} />);
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => resolveFirst(created));
    await waitFor(() => expect(screen.queryByText("直角三角形三边满足关系。")).not.toBeInTheDocument());
  });

  it("disables submission while pending and aborts on unmount", async () => {
    let signal: AbortSignal | undefined;
    mockTutorApi.createConversation.mockImplementation((_kb: string, _prompt: string, requestSignal: AbortSignal) => {
      signal = requestSignal;
      return new Promise(() => undefined);
    });
    const user = userEvent.setup();
    const { unmount } = render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(input).toBeDisabled();
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it.each([[429, "请求过于频繁，请稍后再试。"], [503, "导师服务暂时不可用，请稍后重试。"]])("shows a distinct message for %s", async (status, message) => {
    const user = userEvent.setup();
    mockTutorApi.createConversation.mockRejectedValue(new TutorApiError(status));
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("tells the operator to fix the API key when the provider rejects it as unauthorized", async () => {
    const user = userEvent.setup();
    mockTutorApi.createConversation.mockRejectedValue(
      new TutorApiError(503, "tutor_provider_key_invalid"),
    );
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AI 导师服务密钥无效：请在 .env 中配置真实的 FARO_API_KEY 后重启服务。",
    );
  });

  it("shows a timeout message when the provider times out", async () => {
    const user = userEvent.setup();
    mockTutorApi.createConversation.mockRejectedValue(
      new TutorApiError(503, "tutor_provider_timeout"),
    );
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI 导师响应超时，请稍后重试。");
  });

  it("retries a general message failure with the same prompt", async () => {
    const user = userEvent.setup();
    mockTutorApi.createConversation
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(created);
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "向 AI 导师提问" });
    await user.type(input, "问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("消息发送失败，请重试。");

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("直角三角形三边满足关系。")).toBeInTheDocument();
    expect(mockTutorApi.createConversation).toHaveBeenNthCalledWith(2, "kb-1", "问题", expect.any(AbortSignal));
  });
  it("retries a failed status request and describes the configured model without price data", async () => {
    const user = userEvent.setup();
    mockTutorApi.status.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ configured: true, model: "faro-mini" });
    render(<TutorPanel knowledgeBase={{ id: "kb-1", name: "数学" }} contextLabel="章节" onOpenCitation={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("导师状态暂时无法加载");
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("使用模型：faro-mini")).toBeInTheDocument();
    expect(screen.queryByText(/价格|余额/)).not.toBeInTheDocument();
  });
});
