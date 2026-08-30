import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeBase } from "@/lib/knowledge-api";
import type { ReviewItem } from "@/lib/question-bank-api";

import { StudyDashboard } from "./study-dashboard";

const mockQuestionBankApi = vi.hoisted(() => ({ listReviewItems: vi.fn() }));

vi.mock("@/lib/question-bank-api", () => ({ questionBankApi: mockQuestionBankApi }));

const wireless: KnowledgeBase = {
  id: "wireless",
  space_id: "personal",
  name: "无线通信",
  state: "ready",
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:00:00Z",
};

function reviewItem(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    question_id: "question-1",
    question_version_id: "version-1",
    question_type: "single_choice",
    prompt: "香农容量公式中的带宽如何影响信道容量？",
    attempted_at: "2026-08-25T08:00:00Z",
    correct: false,
    score_basis_points: 2500,
    error_type: "application",
    needs_review: true,
    review_due_at: "2026-08-26T08:00:00Z",
    review_interval_days: 1,
    expected_answer: null,
    explanation: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockQuestionBankApi.listReviewItems.mockReset();
});

describe("StudyDashboard", () => {
  it("shows due items in API order and continues the first question without a mastery percentage", async () => {
    const user = userEvent.setup();
    const onOpenPractice = vi.fn();
    const first = reviewItem();
    const second = reviewItem({
      question_id: "question-2",
      question_version_id: "version-2",
      prompt: "奈奎斯特准则解决了什么问题？",
    });
    mockQuestionBankApi.listReviewItems.mockResolvedValue({
      items: [first, second],
      next_cursor: null,
    });

    const { container } = render(
      <StudyDashboard
        knowledgeBase={wireless}
        onOpenKnowledge={vi.fn()}
        onOpenPractice={onOpenPractice}
      />,
    );

    expect(await screen.findByRole("heading", { name: "继续上次练习" })).toBeInTheDocument();
    expect(mockQuestionBankApi.listReviewItems).toHaveBeenCalledWith(
      "wireless",
      { scope: "due", limit: 20 },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("2 项待复习")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "待复习题目" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(first.prompt);
    expect(items[1]).toHaveTextContent(second.prompt);
    expect(container).not.toHaveTextContent("%");

    await user.click(screen.getByRole("button", { name: "继续学习" }));
    expect(onOpenPractice).toHaveBeenCalledWith("version-1");
  });

  it("opens knowledge when the selected knowledge base has nothing due", async () => {
    const user = userEvent.setup();
    const onOpenKnowledge = vi.fn();
    mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [], next_cursor: null });

    render(
      <StudyDashboard
        knowledgeBase={wireless}
        onOpenKnowledge={onOpenKnowledge}
        onOpenPractice={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "无线通信" })).toBeInTheDocument();
    expect(screen.getByText("从知识库检索或整理资料开始。")) .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开知识" }));
    expect(onOpenKnowledge).toHaveBeenCalledTimes(1);
  });

  it("prompts for a knowledge base without issuing a review request", () => {
    render(
      <StudyDashboard
        knowledgeBase={null}
        onOpenKnowledge={vi.fn()}
        onOpenPractice={vi.fn()}
      />,
    );

    expect(screen.getByText("请创建或选择一个知识库开始学习。")) .toBeInTheDocument();
    expect(mockQuestionBankApi.listReviewItems).not.toHaveBeenCalled();
  });

  it("announces loading and retries a stable review error", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.listReviewItems
      .mockRejectedValueOnce(new Error("private upstream detail"))
      .mockResolvedValueOnce({ items: [], next_cursor: null });

    render(
      <StudyDashboard
        knowledgeBase={wireless}
        onOpenKnowledge={vi.fn()}
        onOpenPractice={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在加载待复习内容…");
    expect(await screen.findByRole("alert")).toHaveTextContent("待复习内容暂时无法加载，请重试。");
    expect(screen.queryByText(/private upstream detail/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByRole("heading", { name: "无线通信" })).toBeInTheDocument();
    expect(mockQuestionBankApi.listReviewItems).toHaveBeenCalledTimes(2);
  });

  it("aborts the old request and ignores a stale result after switching knowledge bases", async () => {
    let firstSignal: AbortSignal | undefined;
    let resolveFirst!: (value: { items: ReviewItem[]; next_cursor: string | null }) => void;
    const current = reviewItem({
      question_id: "question-current",
      question_version_id: "version-current",
      prompt: "当前知识库题目",
    });
    const stale = reviewItem({
      question_id: "question-stale",
      question_version_id: "version-stale",
      prompt: "过期知识库题目",
    });
    mockQuestionBankApi.listReviewItems
      .mockImplementationOnce(
        (_id: string, _options: unknown, signal?: AbortSignal) => {
          firstSignal = signal;
          return new Promise((resolve) => {
            resolveFirst = resolve;
          });
        },
      )
      .mockResolvedValueOnce({ items: [current], next_cursor: null });

    const { rerender } = render(
      <StudyDashboard
        knowledgeBase={wireless}
        onOpenKnowledge={vi.fn()}
        onOpenPractice={vi.fn()}
      />,
    );
    rerender(
      <StudyDashboard
        knowledgeBase={{ ...wireless, id: "digital", name: "数字通信" }}
        onOpenKnowledge={vi.fn()}
        onOpenPractice={vi.fn()}
      />,
    );

    expect(firstSignal?.aborted).toBe(true);
    expect(await screen.findByText("当前知识库题目")).toBeInTheDocument();

    await act(async () => resolveFirst({ items: [stale], next_cursor: null }));

    await waitFor(() => {
      expect(screen.getByText("当前知识库题目")).toBeInTheDocument();
      expect(screen.queryByText("过期知识库题目")).not.toBeInTheDocument();
    });
  });
});
