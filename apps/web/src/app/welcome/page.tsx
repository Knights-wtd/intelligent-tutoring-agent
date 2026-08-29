"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import styles from "./welcome.module.css";

const PRINCIPLES = [
  {
    no: "1",
    title: "证据锚定",
    body: "每道题、每个知识点都能回溯到教材原文页码。答案不凭模型记忆，凭你上传的书。",
  },
  {
    no: "2",
    title: "难度生长",
    body: "同一考点三级难度：直接套用、一步变形、跨章综合。答对解锁，答错降级，题目跟着你走。",
  },
  {
    no: "3",
    title: "错哪红哪",
    body: "作答结果回写知识图谱。薄弱考点在图上蔓延成红色区域，下一分钟该学什么一目了然。",
  },
];

const PIPELINE = [
  { step: "01", label: "导入教材", note: "PDF · DOCX · Markdown · Obsidian" },
  { step: "02", label: "自动知识化", note: "解析 → 索引 → 知识候选 → 人工审阅" },
  { step: "03", label: "带证据出题", note: "按图谱节点命题，L1 / L2 / L3 三档" },
  { step: "04", label: "练习闭环", note: "批改 → 错因 → 掌握度 → 复习队列" },
];

const FEATURES = [
  {
    icon: "◇",
    title: "检索带引用",
    body: "混合检索返回文件名、页码与受限摘录，打开原页核对。",
  },
  {
    icon: "◈",
    title: "知识图谱审阅制",
    body: "AI 生成的知识候选先审后入图，图谱永远是确认过的事实。",
  },
  {
    icon: "◉",
    title: "空间隔离",
    body: "个人空间与班级空间彼此隔离，权限边界在数据库层强制。",
  },
  {
    icon: "◐",
    title: "版本不可变",
    body: "文档与索引多版本管理，重建不覆盖，随时可回滚。",
  },
];

const FAQ = [
  {
    q: "题目是 AI 编的吗？可信吗？",
    a: "题目由 AI 依据你教材中「审阅通过」的知识节点生成，每题强制携带教材引用。未经审阅的内容不会进入题库。",
  },
  {
    q: "我的教材安全吗？",
    a: "全部数据存储在你自部署的 PostgreSQL 与对象存储中，模型密钥只存在于服务端，浏览器不接触任何凭据。",
  },
  {
    q: "支持哪些教材格式？",
    a: "PDF、Word（DOCX）、Markdown、JPG/PNG 图片（OCR 管线）以及 Obsidian Vault 打包 ZIP。",
  },
];

function useRevealOnScroll() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const targets = root.querySelectorAll<HTMLElement>(`[data-reveal]`);
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add(styles.revealed);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    for (const target of targets) observer.observe(target);
    return () => observer.disconnect();
  }, []);

  return rootRef;
}

export default function WelcomePage() {
  const rootRef = useRevealOnScroll();

  return (
    <div className={styles.page} ref={rootRef}>
      <header className={styles.hero}>
        <div className={styles.bubbles} aria-hidden="true">
          {[
            { size: 180, x: "6%", y: "18%", delay: "0s", dur: "9s" },
            { size: 90, x: "78%", y: "8%", delay: "1.2s", dur: "11s" },
            { size: 260, x: "62%", y: "46%", delay: "0.6s", dur: "13s" },
            { size: 60, x: "30%", y: "60%", delay: "2s", dur: "10s" },
            { size: 130, x: "14%", y: "66%", delay: "0.3s", dur: "12s" },
            { size: 44, x: "88%", y: "34%", delay: "1.6s", dur: "8s" },
          ].map((bubble, index) => (
            <span
              key={index}
              className={styles.bubble}
              style={{
                width: bubble.size,
                height: bubble.size,
                left: bubble.x,
                top: bubble.y,
                animationDelay: bubble.delay,
                animationDuration: bubble.dur,
              }}
            />
          ))}
        </div>
        <p className={styles.heroKicker}>知学空间 · KNOWLEDGE WORKSPACE</p>
        <h1 className={styles.heroTitle}>
          <span className={styles.heroTitleLine}>让练习</span>
          <span className={styles.heroTitleOutline}>从教材里</span>
          <span className={styles.heroTitleLine}>生长出来</span>
        </h1>
        <p className={styles.heroSub}>
          导入你自己的教材，知学空间把它变成可检索、可溯源、可练习的知识库。
          每道题都带教材引用，每个薄弱点都在图谱上发光。
        </p>
        <div className={styles.heroActions}>
          <Link className={styles.primaryAction} href="/register">
            注册，开始建我的知识库 →
          </Link>
          <Link className={styles.ghostAction} href="/login">
            已有账号，直接登录
          </Link>
        </div>
      </header>

      <div className={styles.marquee} aria-hidden="true">
        <div className={styles.marqueeTrack}>
          {Array.from({ length: 6 }).map((_, index) => (
            <span className={styles.marqueeItem} key={index}>
              WHY ITA
              <span className={styles.marqueeDots} />
            </span>
          ))}
        </div>
      </div>

      <section className={`${styles.section} ${styles.principles}`}>
        <h2 className={`${styles.sectionTitle} ${styles.revealTarget}`} data-reveal>
          三条设计原则
        </h2>
        <ol className={styles.principleList}>
          {PRINCIPLES.map((principle) => (
            <li key={principle.no} className={`${styles.principle} ${styles.revealTarget}`} data-reveal>
              <span className={styles.principleNo}>{principle.no}</span>
              <h3 className={styles.principleTitle}>{principle.title}</h3>
              <p className={styles.principleBody}>{principle.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className={`${styles.section} ${styles.pipeline}`}>
        <h2 className={`${styles.sectionTitle} ${styles.revealTarget}`} data-reveal>
          四步，教材变成练习
        </h2>
        <ol className={styles.pipelineList}>
          {PIPELINE.map((stage) => (
            <li key={stage.step} className={`${styles.pipelineRow} ${styles.revealTarget}`} data-reveal>
              <span className={styles.pipelineStep}>{stage.step}</span>
              <span className={styles.pipelineLabel}>{stage.label}</span>
              <span className={styles.pipelineNote}>{stage.note}</span>
              <span className={styles.pipelineArrow} aria-hidden="true">
                ⟶
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className={`${styles.section} ${styles.features}`}>
        <h2 className={`${styles.sectionTitle} ${styles.revealTarget}`} data-reveal>
          在工程上较真
        </h2>
        <div className={styles.featureGrid}>
          {FEATURES.map((feature) => (
            <article key={feature.title} className={`${styles.featureCard} ${styles.revealTarget}`} data-reveal>
              <span className={styles.featureIcon} aria-hidden="true">
                {feature.icon}
              </span>
              <h3 className={styles.featureTitle}>{feature.title}</h3>
              <p className={styles.featureBody}>{feature.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className={`${styles.section} ${styles.faq}`}>
        <h2 className={`${styles.sectionTitle} ${styles.revealTarget}`} data-reveal>
          常见疑问
        </h2>
        <div className={styles.faqList}>
          {FAQ.map((item) => (
            <details key={item.q} className={`${styles.faqItem} ${styles.revealTarget}`} data-reveal>
              <summary className={styles.faqQuestion}>{item.q}</summary>
              <p className={styles.faqAnswer}>{item.a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className={styles.footer}>
        <p className={styles.footerLine}>教材进来，练习出去。</p>
        <div className={styles.footerActions}>
          <Link className={styles.primaryAction} href="/register">
            现在注册，让教材长出练习 →
          </Link>
        </div>
      </footer>
    </div>
  );
}
