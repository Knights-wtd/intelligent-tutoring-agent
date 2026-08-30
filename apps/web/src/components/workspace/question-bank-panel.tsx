"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import type { KnowledgeBase } from "@/lib/knowledge-api";
import {
  questionBankApi,
  type AttemptAssessment,
  type AttemptHistoryItem,
  type ChoiceOption,
  type LearnerQuestion,
  type ReviewItem,
} from "@/lib/question-bank-api";

import { TutorRichText } from "./tutor-rich-text";
import styles from "./workspace-shell.module.css";

type QuestionBankPanelProps = {
  knowledgeBase: KnowledgeBase;
  initialQuestionVersionId?: string;
};

const GENERATION_POLL_MS = 2_000;
const DEFAULT_GENERATION_COUNT = 10;
const DIFFICULTY_LABELS = ["", "简单", "较易", "中等", "较难", "困难"];

export function QuestionBankPanel(props: QuestionBankPanelProps) {
  return <QuestionBankPanelForKnowledgeBase key={props.knowledgeBase.id} {...props} />;
}

function QuestionBankPanelForKnowledgeBase({
  knowledgeBase,
  initialQuestionVersionId,
}: QuestionBankPanelProps) {
  const knowledgeBaseId = knowledgeBase.id;
  const [questions, setQuestions] = useState<LearnerQuestion[]>([]);
  const [selectedQuestionVersionId, setSelectedQuestionVersionId] = useState("");
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [answer, setAnswer] = useState("");
  const [assessment, setAssessment] = useState<AttemptAssessment | null>(null);
  const [history, setHistory] = useState<AttemptHistoryItem[] | null>(null);
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationStatus, setGenerationStatus] = useState("");
  const sequenceRef = useRef(0);
  const submitControllerRef = useRef<AbortController | null>(null);
  const historyControllerRef = useRef<AbortController | null>(null);
  const generationControllerRef = useRef<AbortController | null>(null);
  const generationTimerRef = useRef<number | null>(null);
  const attemptKeyRef = useRef<
    { knowledgeBaseId: string; questionVersionId: string; answer: string; value: string } | null
  >(null);

  const abortGeneration = useCallback(() => {
    if (generationTimerRef.current !== null) {
      window.clearTimeout(generationTimerRef.current);
      generationTimerRef.current = null;
    }
    generationControllerRef.current?.abort();
    generationControllerRef.current = null;
  }, []);

  function abortQuestionRequests() {
    sequenceRef.current += 1;
    submitControllerRef.current?.abort();
    historyControllerRef.current?.abort();
    submitControllerRef.current = null;
    historyControllerRef.current = null;
  }

  function cancelQuestionRequests() {
    abortQuestionRequests();
    setIsSubmitting(false);
    setIsLoadingHistory(false);
  }

  useEffect(() => {
    abortQuestionRequests();
    abortGeneration();
    attemptKeyRef.current = null;
    const sequence = sequenceRef.current;
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setIsLoading(true);
      setIsGenerating(false);
      setGenerationStatus("");
      setQuestions([]);
      setSelectedQuestionVersionId(initialQuestionVersionId ?? "");
      setReviewItems([]);
      setAssessment(null);
      setHistory(null);
      setMessage("");
    });
    void Promise.all([
      questionBankApi.listQuestions(knowledgeBaseId, controller.signal),
      questionBankApi.listReviewItems(knowledgeBaseId, controller.signal),
    ])
      .then(([loadedQuestions, loadedReviewItems]) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setQuestions(loadedQuestions);
        setReviewItems(loadedReviewItems.items);
        setSelectedQuestionVersionId(
          loadedQuestions.some((question) => question.question_version_id === initialQuestionVersionId)
            ? (initialQuestionVersionId ?? "")
            : (loadedQuestions[0]?.question_version_id ?? ""),
        );
      })
      .catch(() => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setMessage("题库暂时无法加载，请重试。");
      })
      .finally(() => {
        if (!controller.signal.aborted && sequence === sequenceRef.current) setIsLoading(false);
      });
    return () => controller.abort();
    // abortGeneration 是稳定的回调，切换知识库时由它清理轮询。
  }, [abortGeneration, initialQuestionVersionId, knowledgeBaseId]);

  useEffect(() => {
    return () => {
      submitControllerRef.current?.abort();
      historyControllerRef.current?.abort();
      submitControllerRef.current = null;
      historyControllerRef.current = null;
      abortGeneration();
    };
  }, [abortGeneration]);

  const selectedQuestion = questions.find(
    (question) => question.question_version_id === selectedQuestionVersionId,
  );

  function selectQuestion(questionVersionId: string) {
    if (questionVersionId === selectedQuestionVersionId) return;
    cancelQuestionRequests();
    attemptKeyRef.current = null;
    setSelectedQuestionVersionId(questionVersionId);
    setAnswer("");
    setAssessment(null);
    setHistory(null);
  }

  function changeAnswer(value: string) {
    if (value !== answer) attemptKeyRef.current = null;
    setAnswer(value);
  }

  function pollGeneration(knowledgeBaseId: string, generationId: string, sequence: number) {
    if (sequence !== sequenceRef.current) return;
    const controller = new AbortController();
    generationControllerRef.current = controller;
    questionBankApi
      .getQuestionGeneration(knowledgeBaseId, generationId, controller.signal)
      .then((generation) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        if (generation.state === "processing") {
          setGenerationStatus("AI 正在出题，请稍候…");
          generationTimerRef.current = window.setTimeout(
            () => pollGeneration(knowledgeBaseId, generationId, sequence),
            GENERATION_POLL_MS,
          );
          return;
        }
        generationControllerRef.current = null;
        setIsGenerating(false);
        setGenerationStatus("");
        if (generation.state === "failed") {
          setMessage(
            generationFailureMessage(generation.failure_code),
          );
          return;
        }
        const reloadController = new AbortController();
        void Promise.all([
          questionBankApi.listQuestions(knowledgeBaseId, reloadController.signal),
          questionBankApi.listReviewItems(knowledgeBaseId, reloadController.signal),
        ])
          .then(([loadedQuestions, loadedReviewItems]) => {
            if (reloadController.signal.aborted || sequence !== sequenceRef.current) return;
            setQuestions(loadedQuestions);
            setReviewItems(loadedReviewItems.items);
            setSelectedQuestionVersionId((current) =>
              loadedQuestions.some((question) => question.question_version_id === current)
                ? current
                : (loadedQuestions[0]?.question_version_id ?? ""),
            );
            setMessage(`已生成 ${generation.question_count} 道课后题。`);
          })
          .catch(() => {
            if (reloadController.signal.aborted || sequence !== sequenceRef.current) return;
            setMessage("题目已生成，但列表刷新失败，请稍后重试。");
          });
      })
      .catch(() => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        generationControllerRef.current = null;
        setIsGenerating(false);
        setGenerationStatus("");
        setMessage("生成状态暂时无法获取，请重试。");
      });
  }

  function generateQuestions() {
    if (isGenerating) return;
    abortGeneration();
    const sequence = sequenceRef.current;
    const controller = new AbortController();
    generationControllerRef.current = controller;
    setIsGenerating(true);
    setMessage("");
    setGenerationStatus("正在发起课后题生成…");
    questionBankApi
      .generateQuestions(knowledgeBaseId, DEFAULT_GENERATION_COUNT, controller.signal)
      .then((generation) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        if (generation.state === "failed") {
          generationControllerRef.current = null;
          setIsGenerating(false);
          setGenerationStatus("");
          setMessage(generationFailureMessage(generation.failure_code));
          return;
        }
        setGenerationStatus("AI 正在通读整个知识库并出题，约需一至两分钟…");
        pollGeneration(knowledgeBaseId, generation.generation_id, sequence);
      })
      .catch(() => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        generationControllerRef.current = null;
        setIsGenerating(false);
        setGenerationStatus("");
        setMessage("暂时无法发起生成，请重试。");
      });
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedAnswer = answer.trim();
    if (!selectedQuestion || !normalizedAnswer) {
      setMessage("请先选择题目并填写答案。");
      return;
    }
    submitControllerRef.current?.abort();
    const controller = new AbortController();
    submitControllerRef.current = controller;
    const sequence = sequenceRef.current;
    const questionVersionId = selectedQuestion.question_version_id;
    const existingAttemptKey = attemptKeyRef.current;
    const idempotencyKey =
      existingAttemptKey !== null &&
      existingAttemptKey.knowledgeBaseId === knowledgeBaseId &&
      existingAttemptKey.questionVersionId === questionVersionId &&
      existingAttemptKey.answer === normalizedAnswer
        ? existingAttemptKey.value
        : newAttemptKey();
    attemptKeyRef.current = {
      knowledgeBaseId: knowledgeBaseId,
      questionVersionId,
      answer: normalizedAnswer,
      value: idempotencyKey,
    };
    setIsSubmitting(true);
    setMessage("");
    let attemptSubmitted = false;
    try {
      const result = await questionBankApi.submitAttempt(
        knowledgeBaseId,
        questionVersionId,
        normalizedAnswer,
        idempotencyKey,
        controller.signal,
      );
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      attemptSubmitted = true;
      setAssessment(result);
      const loadedReviewItems = await questionBankApi.listReviewItems(
        knowledgeBaseId,
        controller.signal,
      );
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setReviewItems(loadedReviewItems.items);
      attemptKeyRef.current = null;
      // 选择题保留所选选项以便对照答案解析；主观题清空输入框。
      if (!selectedQuestion.choices?.length) setAnswer("");
    } catch {
      if (!controller.signal.aborted && sequence === sequenceRef.current) {
        setMessage(
          attemptSubmitted
            ? "答案已提交，但待复习列表刷新失败，请稍后重试。"
            : "暂时无法提交答案，请重试。",
        );
      }
    } finally {
      if (submitControllerRef.current === controller) {
        submitControllerRef.current = null;
        setIsSubmitting(false);
      }
    }
  }

  async function loadHistory() {
    if (!selectedQuestion) return;
    historyControllerRef.current?.abort();
    const controller = new AbortController();
    historyControllerRef.current = controller;
    const sequence = sequenceRef.current;
    const questionVersionId = selectedQuestion.question_version_id;
    setIsLoadingHistory(true);
    setMessage("");
    try {
      const result = await questionBankApi.listAttemptHistory(
        knowledgeBaseId,
        questionVersionId,
        controller.signal,
      );
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setHistory(result.items);
    } catch {
      if (!controller.signal.aborted && sequence === sequenceRef.current) {
        setMessage("暂时无法读取答题历史，请重试。");
      }
    } finally {
      if (historyControllerRef.current === controller) {
        historyControllerRef.current = null;
        setIsLoadingHistory(false);
      }
    }
  }

  return (
    <section aria-label="题库练习面板" className={styles.questionBankPanel}>
      <header className={styles.knowledgeHeader}>
        <div>
          <span className={styles.eyebrow}>{knowledgeBase.name}</span>
          <h2>题库练习</h2>
        </div>
        <button disabled={isGenerating || isLoading} onClick={generateQuestions} type="button">
          {isGenerating ? "生成中…" : "AI 生成课后题"}
        </button>
      </header>
      {isLoading ? <p role="status">正在加载题库…</p> : null}
      {generationStatus ? <p role="status">{generationStatus}</p> : null}
      {!isLoading ? (
        <>
          {questions.length > 0 ? (
            <div className={styles.questionList} aria-label="题目列表">
              {questions.map((question, index) => (
                <button
                  aria-pressed={question.question_version_id === selectedQuestionVersionId}
                  key={question.question_version_id}
                  onClick={() => selectQuestion(question.question_version_id)}
                  type="button"
                >
                  题目 {index + 1}
                  {question.difficulty ? ` · ${difficultyLabel(question.difficulty)}` : ""}
                </button>
              ))}
            </div>
          ) : (
            <p>当前知识库还没有题目，点击右上角“AI 生成课后题”即可从知识库生成一套由简到难的选择题。</p>
          )}

          {selectedQuestion ? (
            <article className={styles.questionCard}>
              <p className={styles.questionPrompt}>{selectedQuestion.prompt}</p>
              {selectedQuestion.choices && selectedQuestion.choices.length > 0 ? (
                <div
                  aria-label="选项"
                  className={styles.choiceList}
                  role="radiogroup"
                >
                  {selectedQuestion.choices.map((choice) => (
                    <label className={styles.choiceOption} key={choice.key}>
                      <input
                        checked={answer === choice.key}
                        disabled={isSubmitting}
                        name={`choice-${selectedQuestion.question_version_id}`}
                        onChange={() => changeAnswer(choice.key)}
                        type="radio"
                        value={choice.key}
                      />
                      <span className={styles.choiceKey}>{choice.key}</span>
                      <span>{choice.text}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <label className={styles.answerLabel}>
                  你的答案
                  <textarea
                    aria-label="你的答案"
                    disabled={isSubmitting}
                    onChange={(event) => changeAnswer(event.target.value)}
                    value={answer}
                  />
                </label>
              )}
              <form onSubmit={submitAnswer}>
                <div className={styles.questionActions}>
                  <button disabled={isSubmitting} type="submit">
                    {isSubmitting ? "提交中…" : "提交答案"}
                  </button>
                  <button
                    disabled={isLoadingHistory}
                    onClick={() => void loadHistory()}
                    type="button"
                  >
                    {isLoadingHistory ? "正在读取历史…" : "查看本题历史"}
                  </button>
                </div>
              </form>
              {assessment ? (
                <AssessmentSummary
                  assessment={assessment}
                  choices={selectedQuestion.choices}
                />
              ) : null}
              {history ? (
                <section aria-label="本题历史" className={styles.learningList}>
                  {history.length === 0 ? <p>尚无答题历史。</p> : null}
                  {history.map((item, index) => (
                    <p key={`${item.question_version_id}-${index}`}>
                      历史记录：{item.correct ? "回答正确" : "需要复习"} · 得分 {formatScore(item.score_basis_points)}
                    </p>
                  ))}
                </section>
              ) : null}
            </article>
          ) : null}

          <section aria-label="待复习项" className={styles.learningList}>
            <h3>待复习项</h3>
            {reviewItems.length === 0 ? <p>暂无待复习项。</p> : null}
            {reviewItems.map((item) => (
              <button
                key={item.question_version_id}
                onClick={() => selectQuestion(item.question_version_id)}
                type="button"
              >
                {item.prompt} · {formatReviewDue(item.review_due_at)}
              </button>
            ))}
          </section>
          {message ? <p role="alert">{message}</p> : null}
        </>
      ) : null}
    </section>
  );
}

function AssessmentSummary({
  assessment,
  choices,
}: {
  assessment: AttemptAssessment;
  choices: ChoiceOption[] | null;
}) {
  const correctOption = choices?.find(
    (choice) => choice.key === assessment.expected_answer,
  );
  return (
    <section aria-label="本次评估" className={styles.assessment}>
      <strong>{assessment.correct ? "回答正确" : "需要复习"}</strong>
      <span>得分 {formatScore(assessment.score_basis_points)}</span>
      <span>错误类型：{errorTypeLabel(assessment.error_type)}</span>
      <span>{formatReviewDue(assessment.review_due_at)}</span>
      {assessment.expected_answer ? (
        <p className={styles.revealedAnswer}>
          正确答案：{assessment.expected_answer}
          {correctOption ? `（${correctOption.text}）` : ""}
        </p>
      ) : null}
      {assessment.explanation ? (
        <section aria-label="答案解析" className={styles.explanation}>
          <strong>解析</strong>
          <TutorRichText content={assessment.explanation} />
        </section>
      ) : null}
    </section>
  );
}

function difficultyLabel(difficulty: number): string {
  return DIFFICULTY_LABELS[difficulty] ?? `难度 ${difficulty}`;
}

function generationFailureMessage(failureCode: string | null): string {
  switch (failureCode) {
    case "llm_unauthorized":
      return "AI 服务密钥无效，请联系管理员检查 FARO_API_KEY 配置。";
    case "llm_timeout":
      return "AI 服务响应超时，请稍后重试。";
    case "llm_rate_limited":
      return "AI 服务请求过于频繁，请稍后重试。";
    case "llm_network_error":
      return "无法连接 AI 服务，请检查网络后重试。";
    case "question_output_invalid":
      return "AI 返回的题目格式异常，请重新生成。";
    case "question_source_empty":
      return "知识库还没有可出题的内容，请先上传资料并等待解析完成。";
    default:
      return "生成失败，请重新尝试。";
  }
}

function formatScore(scoreBasisPoints: number): string {
  return (scoreBasisPoints / 100).toFixed(2);
}

function errorTypeLabel(errorType: AttemptAssessment["error_type"]): string {
  if (errorType === "metacognitive") return "理解反思";
  if (errorType === "application") return "应用";
  return "无";
}

function formatReviewDue(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "下次复习时间待定";
  return `下次复习：${date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" })}`;
}

function newAttemptKey(): string {
  const value = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `web-attempt-${value}`;
}
