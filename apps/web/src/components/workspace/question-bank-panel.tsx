"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import type { KnowledgeBase } from "@/lib/knowledge-api";
import {
  questionBankApi,
  type AttemptAssessment,
  type AttemptHistoryItem,
  type LearnerQuestion,
  type ReviewItem,
} from "@/lib/question-bank-api";

import styles from "./workspace-shell.module.css";

type QuestionBankPanelProps = {
  knowledgeBase: KnowledgeBase;
  initialQuestionVersionId?: string;
};

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
  const sequenceRef = useRef(0);
  const submitControllerRef = useRef<AbortController | null>(null);
  const historyControllerRef = useRef<AbortController | null>(null);
  const attemptKeyRef = useRef<
    { knowledgeBaseId: string; questionVersionId: string; answer: string; value: string } | null
  >(null);

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
    attemptKeyRef.current = null;
    const sequence = sequenceRef.current;
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setIsLoading(true);
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
        setSelectedQuestionVersionId(
          loadedQuestions.some((question) => question.question_version_id === initialQuestionVersionId)
            ? (initialQuestionVersionId ?? "")
            : (loadedQuestions[0]?.question_version_id ?? ""),
        );
        setReviewItems(loadedReviewItems.items);
      })
      .catch(() => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setMessage("题库暂时无法加载，请重试。");
      })
      .finally(() => {
        if (!controller.signal.aborted && sequence === sequenceRef.current) setIsLoading(false);
      });
    return () => controller.abort();
  }, [initialQuestionVersionId, knowledgeBaseId]);

  useEffect(() => {
    return () => {
      submitControllerRef.current?.abort();
      historyControllerRef.current?.abort();
      submitControllerRef.current = null;
      historyControllerRef.current = null;
    };
  }, []);

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
      setAnswer("");
      attemptKeyRef.current = null;
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
      </header>
      {isLoading ? <p role="status">正在加载题库…</p> : null}
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
                </button>
              ))}
            </div>
          ) : (
            <p>当前知识库还没有可练习题目。</p>
          )}

          {selectedQuestion ? (
            <article className={styles.questionCard}>
              <p className={styles.questionPrompt}>{selectedQuestion.prompt}</p>
              <form onSubmit={submitAnswer}>
                <label className={styles.answerLabel}>
                  你的答案
                  <textarea
                    aria-label="你的答案"
                    disabled={isSubmitting}
                    onChange={(event) => changeAnswer(event.target.value)}
                    value={answer}
                  />
                </label>
                <div className={styles.questionActions}>
                  <button disabled={isSubmitting} type="submit">
                    {isSubmitting ? "提交中…" : "提交答案"}
                  </button>
                  <button disabled={isLoadingHistory} onClick={() => void loadHistory()} type="button">
                    {isLoadingHistory ? "正在读取历史…" : "查看本题历史"}
                  </button>
                </div>
              </form>
              {assessment ? <AssessmentSummary assessment={assessment} /> : null}
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
              <p key={item.question_version_id}>
                {item.prompt} · {formatReviewDue(item.review_due_at)}
              </p>
            ))}
          </section>
          {message ? <p role="alert">{message}</p> : null}
        </>
      ) : null}
    </section>
  );
}

function AssessmentSummary({ assessment }: { assessment: AttemptAssessment }) {
  return (
    <section aria-label="本次评估" className={styles.assessment}>
      <strong>{assessment.correct ? "回答正确" : "需要复习"}</strong>
      <span>得分 {formatScore(assessment.score_basis_points)}</span>
      <span>错误类型：{errorTypeLabel(assessment.error_type)}</span>
      <span>{formatReviewDue(assessment.review_due_at)}</span>
    </section>
  );
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
