"use client";

import { useEffect, useState } from "react";

import type { KnowledgeBase } from "@/lib/knowledge-api";
import { questionBankApi, type ReviewItem } from "@/lib/question-bank-api";

import styles from "./workspace-shell.module.css";

type StudyDashboardProps = {
  knowledgeBase: KnowledgeBase | null;
  onOpenKnowledge: () => void;
  onOpenPractice: (questionVersionId: string) => void;
};

type LoadResult = {
  requestKey: string;
  state: "ready" | "error";
  items: ReviewItem[];
};

export function StudyDashboard({
  knowledgeBase,
  onOpenKnowledge,
  onOpenPractice,
}: StudyDashboardProps) {
  const [loadResult, setLoadResult] = useState<LoadResult | null>(null);
  const [retrySequence, setRetrySequence] = useState(0);
  const knowledgeBaseId = knowledgeBase?.id ?? null;
  const requestKey = (knowledgeBaseId ?? "none") + ":" + retrySequence;

  useEffect(() => {
    if (!knowledgeBaseId) return;

    const controller = new AbortController();
    let active = true;

    void questionBankApi
      .listReviewItems(knowledgeBaseId, { scope: "due", limit: 20 }, controller.signal)
      .then((response) => {
        if (!active) return;
        setLoadResult({ requestKey, state: "ready", items: response.items });
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setLoadResult({ requestKey, state: "error", items: [] });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [knowledgeBaseId, requestKey]);

  if (!knowledgeBase) {
    return (
      <section aria-labelledby="study-dashboard-title" className={styles.studyDashboard}>
        <div className={styles.studyDashboardCard}>
          <h2 id="study-dashboard-title">开始学习</h2>
          <p>请创建或选择一个知识库开始学习。</p>
          <button onClick={onOpenKnowledge} type="button">
            打开知识
          </button>
        </div>
      </section>
    );
  }

  if (!loadResult || loadResult.requestKey !== requestKey) {
    return (
      <section aria-labelledby="study-dashboard-title" className={styles.studyDashboard}>
        <div className={styles.studyDashboardCard}>
          <h2 id="study-dashboard-title">{knowledgeBase.name}</h2>
          <p role="status">正在加载待复习内容…</p>
        </div>
      </section>
    );
  }

  if (loadResult.state === "error") {
    return (
      <section aria-labelledby="study-dashboard-title" className={styles.studyDashboard}>
        <div className={styles.studyDashboardCard}>
          <h2 id="study-dashboard-title">{knowledgeBase.name}</h2>
          <div className={styles.studyDashboardError} role="alert">
            <p>待复习内容暂时无法加载，请重试。</p>
            <button onClick={() => setRetrySequence((current) => current + 1)} type="button">
              重试
            </button>
          </div>
        </div>
      </section>
    );
  }

  const firstDueItem = loadResult.items[0];
  if (!firstDueItem) {
    return (
      <section aria-labelledby="study-dashboard-title" className={styles.studyDashboard}>
        <div className={styles.studyDashboardCard}>
          <h2 id="study-dashboard-title">{knowledgeBase.name}</h2>
          <p>从知识库检索或整理资料开始。</p>
          <button onClick={onOpenKnowledge} type="button">
            打开知识
          </button>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="study-dashboard-title" className={styles.studyDashboard}>
      <div className={styles.studyDashboardCard}>
        <p className={styles.studyDashboardEyebrow}>{knowledgeBase.name}</p>
        <h2 id="study-dashboard-title">继续上次练习</h2>
        <p className={styles.studyDashboardCount}>{loadResult.items.length} 项待复习</p>
        <ol aria-label="待复习题目" className={styles.studyDashboardList}>
          {loadResult.items.map((item) => (
            <li key={item.question_version_id}>{item.prompt}</li>
          ))}
        </ol>
        <button onClick={() => onOpenPractice(firstDueItem.question_version_id)} type="button">
          继续学习
        </button>
      </div>
    </section>
  );
}
