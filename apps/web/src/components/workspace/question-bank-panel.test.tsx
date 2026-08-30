import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionBankPanel } from "./question-bank-panel";

const mockKnowledgeApi = vi.hoisted(() => ({ list: vi.fn() }));
const mockQuestionBankApi = vi.hoisted(() => ({
  listQuestions: vi.fn(),
  submitAttempt: vi.fn(),
  listReviewItems: vi.fn(),
  listAttemptHistory: vi.fn(),
  generateQuestions: vi.fn(),
  getQuestionGeneration: vi.fn(),
}));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});
vi.mock("@/lib/question-bank-api", () => ({ questionBankApi: mockQuestionBankApi }));

const knowledgeBase = {
  id: "kb-math",
  space_id: "space-math",
  name: "七年级数学",
  state: "active",
  created_at: "2026-08-21T00:00:00Z",
  updated_at: "2026-08-21T00:00:00Z",
};
const assessment = {
  question_version_id: "version-1",
  created_at: "2026-08-21T00:00:00Z",
  correct: true,
  score_basis_points: 10000,
  error_type: "none",
  needs_review: false,
  mastery_basis_points: 9000,
  mastery_evidence_count: 1,
  review_due_at: "2026-08-28T00:00:00Z",
  review_interval_days: 7,
  grading_contract_version: "grading-v1",
  mastery_contract_version: "mastery-v1",
  review_policy_version: "review-v1",
  expected_answer: null,
  explanation: null,
};
const choiceAssessment = {
  ...assessment,
  expected_answer: "B",
  explanation: "勾股定理指出两直角边平方和等于斜边平方。",
};
const choiceQuestion = {
  id: "question-9",
  question_version_id: "version-9",
  knowledge_base_id: "kb-math",
  space_id: "space-math",
  version_number: 1,
  question_type: "choice",
  prompt: "勾股定理指的是什么？",
  choices: [
    { key: "A", text: "两直角边之和等于斜边" },
    { key: "B", text: "两直角边的平方和等于斜边的平方" },
    { key: "C", text: "斜边最长" },
    { key: "D", text: "三角形内角和为 180 度" },
  ],
  difficulty: 2,
  created_at: "2026-08-21T00:00:00Z",
};

beforeEach(() => {
  for (const mock of Object.values(mockQuestionBankApi)) mock.mockReset();
  mockKnowledgeApi.list.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([
    {
      id: "kb-math",
      space_id: "space-math",
      name: "七年级数学",
      state: "active",
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
    },
  ]);
  mockQuestionBankApi.listQuestions.mockResolvedValue([
    {
      id: "question-1",
      question_version_id: "version-1",
      knowledge_base_id: "kb-math",
      space_id: "space-math",
      version_number: 1,
      question_type: "short",
      prompt: "请写出勾股定理。",
      choices: null,
      difficulty: null,
      created_at: "2026-08-21T00:00:00Z",
    },
  ]);
  mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [], next_cursor: null });
  mockQuestionBankApi.listAttemptHistory.mockResolvedValue({
    items: [{ ...assessment, question_id: "question-1", question_type: "short", prompt: "请写出勾股定理。", attempted_at: "2026-08-20T00:00:00Z" }],
    next_cursor: null,
  });
  mockQuestionBankApi.generateQuestions.mockResolvedValue({
    generation_id: "gen-1",
    state: "processing",
    failure_code: null,
    requested_question_count: 10,
    question_count: 0,
    created_at: "2026-08-30T00:00:00Z",
    completed_at: null,
  });
  mockQuestionBankApi.getQuestionGeneration.mockResolvedValue({
    generation_id: "gen-1",
    state: "completed",
    failure_code: null,
    requested_question_count: 10,
    question_count: 2,
    created_at: "2026-08-30T00:00:00Z",
    completed_at: "2026-08-30T00:01:00Z",
  });
});

describe("QuestionBankPanel", () => {
  it("uses the shell-controlled knowledge base and initial question", async () => {
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} initialQuestionVersionId="version-1" />);

    expect(mockKnowledgeApi.list).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mockQuestionBankApi.listQuestions).toHaveBeenCalledWith(
        "kb-math",
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("请写出勾股定理。")).toBeInTheDocument();
  });
  it("lets a learner answer, see safe feedback, review items, and own history", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.submitAttempt.mockResolvedValue(assessment);
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(await screen.findByText("请写出勾股定理。")).toBeInTheDocument();
    await user.type(screen.getByLabelText("你的答案"), "直角三角形两直角边平方和等于斜边平方");
    await user.click(screen.getByRole("button", { name: "提交答案" }));

    expect(mockQuestionBankApi.submitAttempt).toHaveBeenCalledWith(
      "kb-math",
      "version-1",
      "直角三角形两直角边平方和等于斜边平方",
      expect.stringMatching(/^web-attempt-/),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("回答正确")).toBeInTheDocument();
    expect(screen.getByText("得分 100.00")).toBeInTheDocument();
    expect(screen.getByText(/下次复习/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看本题历史" }));
    expect(mockQuestionBankApi.listAttemptHistory).toHaveBeenCalledWith(
      "kb-math",
      "version-1",
      expect.any(AbortSignal),
    );
    expect(await screen.findByText(/历史记录：回答正确/)).toBeInTheDocument();
    expect(screen.queryByText(/expected_answer|rubric|source_pointer|user_id|assessment_id/i)).not.toBeInTheDocument();
  });

  it("cancels stale submit and history work when a learner selects another question", async () => {
    const user = userEvent.setup();
    let resolveSubmit: (value: typeof assessment) => void = () => undefined;
    let resolveHistory: (value: { items: []; next_cursor: null }) => void = () => undefined;
    let submitSignal: AbortSignal | undefined;
    let historySignal: AbortSignal | undefined;
    mockQuestionBankApi.listQuestions.mockResolvedValue([
      {
        question_version_id: "version-1",
        question_type: "short",
        prompt: "第一题",
      },
      {
        question_version_id: "version-2",
        question_type: "short",
        prompt: "第二题",
      },
    ]);
    mockQuestionBankApi.submitAttempt.mockImplementation(
      (_knowledgeBaseId: string, _questionVersionId: string, _answer: string, _key: string, signal: AbortSignal) => {
        submitSignal = signal;
        return new Promise((resolve) => {
          resolveSubmit = resolve;
        });
      },
    );
    mockQuestionBankApi.listAttemptHistory.mockImplementation(
      (_knowledgeBaseId: string, _questionVersionId: string, signal: AbortSignal) => {
        historySignal = signal;
        return new Promise((resolve) => {
          resolveHistory = resolve;
        });
      },
    );
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(await screen.findByText("第一题")).toBeInTheDocument();
    await user.type(screen.getByLabelText("你的答案"), "第一题答案");
    await user.click(screen.getByRole("button", { name: "提交答案" }));
    await user.click(screen.getByRole("button", { name: "查看本题历史" }));
    expect(screen.getByRole("button", { name: "正在读取历史…" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "题目 2" }));
    expect(submitSignal?.aborted).toBe(true);
    expect(historySignal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "提交答案" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "查看本题历史" })).toBeEnabled();
    await user.type(screen.getByLabelText("你的答案"), "第二题答案");

    await act(async () => {
      resolveSubmit(assessment);
      resolveHistory({ items: [], next_cursor: null });
    });

    expect(screen.getByLabelText("你的答案")).toHaveValue("第二题答案");
    expect(screen.queryByLabelText("本次评估")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("本题历史")).not.toBeInTheDocument();
  });

  it("reuses the idempotency key after a successful submit when review refresh fails", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.submitAttempt.mockResolvedValue(assessment);
    mockQuestionBankApi.listReviewItems
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockRejectedValueOnce(new Error("review refresh failed"))
      .mockResolvedValueOnce({ items: [], next_cursor: null });
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(await screen.findByText("请写出勾股定理。")).toBeInTheDocument();
    const answerInput = screen.getByLabelText("你的答案");
    await user.type(answerInput, "同一个答案");
    await user.click(screen.getByRole("button", { name: "提交答案" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "答案已提交，但待复习列表刷新失败，请稍后重试。",
    );
    expect(screen.getByText("回答正确")).toBeInTheDocument();
    expect(answerInput).toHaveValue("同一个答案");
    const firstKey = mockQuestionBankApi.submitAttempt.mock.calls[0]?.[3];

    await user.click(screen.getByRole("button", { name: "提交答案" }));

    expect(await screen.findByText("暂无待复习项。")).toBeInTheDocument();
    expect(mockQuestionBankApi.submitAttempt.mock.calls[1]?.[3]).toBe(firstKey);
    expect(answerInput).toHaveValue("");
  });

  it("renders choice questions, reveals the correct answer and explanation after submitting", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.listQuestions.mockResolvedValue([choiceQuestion]);
    mockQuestionBankApi.submitAttempt.mockResolvedValue(choiceAssessment);
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(await screen.findByText("勾股定理指的是什么？")).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "选项" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /两直角边的平方和等于斜边的平方/ }));
    await user.click(screen.getByRole("button", { name: "提交答案" }));

    expect(mockQuestionBankApi.submitAttempt).toHaveBeenCalledWith(
      "kb-math",
      "version-9",
      "B",
      expect.stringMatching(/^web-attempt-/),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("回答正确")).toBeInTheDocument();
    expect(screen.getByText(/正确答案：B/)).toBeInTheDocument();
    expect(screen.getByLabelText("答案解析")).toHaveTextContent("勾股定理指出两直角边平方和等于斜边平方。");
  });

  it("generates questions from the knowledge base and reloads them when the job completes", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.listQuestions.mockResolvedValue([]);
    mockQuestionBankApi.getQuestionGeneration.mockResolvedValue({
      generation_id: "gen-1",
      state: "processing",
      failure_code: null,
      requested_question_count: 10,
      question_count: 0,
      created_at: "2026-08-30T00:00:00Z",
      completed_at: null,
    });
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(
      await screen.findByText(/AI 生成课后题/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/当前知识库还没有题目/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "AI 生成课后题" }));
    expect(mockQuestionBankApi.generateQuestions).toHaveBeenCalledWith(
      "kb-math",
      10,
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "生成中…" })).toBeDisabled();

    // 第一次轮询仍在处理，随后完成并重载题目。
    await waitFor(
      () => expect(mockQuestionBankApi.getQuestionGeneration).toHaveBeenCalled(),
    );
    mockQuestionBankApi.listQuestions.mockResolvedValue([choiceQuestion]);
    mockQuestionBankApi.getQuestionGeneration.mockResolvedValue({
      generation_id: "gen-1",
      state: "completed",
      failure_code: null,
      requested_question_count: 10,
      question_count: 1,
      created_at: "2026-08-30T00:00:00Z",
      completed_at: "2026-08-30T00:01:00Z",
    });

    expect(
      await screen.findByText("已生成 1 道课后题。", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(await screen.findByText("勾股定理指的是什么？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 生成课后题" })).toBeEnabled();
  });

  it("surfaces a friendly message when generation fails permanently", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.listQuestions.mockResolvedValue([]);
    mockQuestionBankApi.generateQuestions.mockResolvedValue({
      generation_id: "gen-2",
      state: "failed",
      failure_code: "llm_unauthorized",
      requested_question_count: 10,
      question_count: 0,
      created_at: "2026-08-30T00:00:00Z",
      completed_at: "2026-08-30T00:00:10Z",
    });
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    await user.click(
      await screen.findByRole("button", { name: "AI 生成课后题" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("AI 服务密钥无效");
    expect(screen.getByRole("button", { name: "AI 生成课后题" })).toBeEnabled();
  });

  it("reuses the idempotency key for the same answer retry and replaces it after an answer change", async () => {
    const user = userEvent.setup();
    mockQuestionBankApi.submitAttempt
      .mockRejectedValueOnce(new Error("temporary network failure"))
      .mockRejectedValueOnce(new Error("temporary network failure"))
      .mockRejectedValueOnce(new Error("temporary network failure"));
    render(<QuestionBankPanel knowledgeBase={knowledgeBase} />);

    expect(await screen.findByText("请写出勾股定理。")).toBeInTheDocument();
    const answerInput = screen.getByLabelText("你的答案");
    await user.type(answerInput, "第一次答案");
    await user.click(screen.getByRole("button", { name: "提交答案" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法提交答案，请重试。");
    await user.click(screen.getByRole("button", { name: "提交答案" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法提交答案，请重试。");
    const retryKey = mockQuestionBankApi.submitAttempt.mock.calls[1]?.[3];
    expect(retryKey).toBe(mockQuestionBankApi.submitAttempt.mock.calls[0]?.[3]);

    await user.clear(answerInput);
    await user.type(answerInput, "修改后的答案");
    await user.click(screen.getByRole("button", { name: "提交答案" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法提交答案，请重试。");
    expect(mockQuestionBankApi.submitAttempt.mock.calls[2]?.[3]).not.toBe(retryKey);
  });

});
