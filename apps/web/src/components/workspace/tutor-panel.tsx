"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import {
  TutorApiError,
  tutorApi,
  type TutorCitation,
  type TutorConversation,
  type TutorStatus,
} from "@/lib/tutor-api";

import styles from "./workspace-shell.module.css";

type Props = {
  knowledgeBase: { id: string; name: string };
  contextLabel: string;
  onOpenCitation: (citation: TutorCitation) => void;
};

export function TutorPanel({ knowledgeBase, contextLabel, onOpenCitation }: Props) {
  const [status, setStatus] = useState<TutorStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [statusAttempt, setStatusAttempt] = useState(0);
  const [conversation, setConversation] = useState<TutorConversation | null>(null);
  const [prompt, setPrompt] = useState("");
  const [pending, setPending] = useState(false);
  const [requestError, setRequestError] = useState<TutorApiError | null>(null);
  const [retryPrompt, setRetryPrompt] = useState<string | null>(null);
  const operation = useRef<AbortController | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    void tutorApi.status(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setStatus(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatusFailed(true);
      });
    return () => controller.abort();
  }, [statusAttempt]);

  useEffect(() => {
    generation.current += 1;
    operation.current?.abort();
    operation.current = null;
    let current = true;
    void Promise.resolve().then(() => {
      if (!current) return;
      setConversation(null);
      setPrompt("");
      setPending(false);
      setRequestError(null);
      setRetryPrompt(null);
    });
    return () => { current = false; };
  }, [knowledgeBase.id]);

  useEffect(() => () => operation.current?.abort(), []);

  async function send(value: string) {
    const currentPrompt = value.trim();
    if (!currentPrompt || pending || !status?.configured) return;
    const requestGeneration = generation.current;
    const controller = new AbortController();
    operation.current?.abort();
    operation.current = controller;
    setPending(true);
    setRequestError(null);
    setRetryPrompt(null);
    try {
      const next = conversation
        ? await tutorApi.sendMessage(
            knowledgeBase.id,
            conversation.id,
            currentPrompt,
            controller.signal,
          )
        : await tutorApi.createConversation(
            knowledgeBase.id,
            currentPrompt,
            controller.signal,
          );
      if (!controller.signal.aborted && requestGeneration === generation.current) {
        setConversation(next);
        setPrompt("");
      }
    } catch (error) {
      if (!controller.signal.aborted && requestGeneration === generation.current) {
        setRequestError(error instanceof TutorApiError ? error : new TutorApiError(0));
        setRetryPrompt(currentPrompt);
      }
    } finally {
      if (!controller.signal.aborted && requestGeneration === generation.current) {
        setPending(false);
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(prompt);
  }

  const disabled = pending || status === null || !status.configured || statusFailed;
  const errorMessage = (() => {
    if (requestError === null) return null;
    if (requestError.code === "tutor_provider_key_invalid") {
      return "AI 导师服务密钥无效：请在 .env 中配置真实的 FARO_API_KEY 后重启服务。";
    }
    if (requestError.code === "tutor_provider_timeout") {
      return "AI 导师响应超时，请稍后重试。";
    }
    if (requestError.code === "tutor_provider_rate_limited" || requestError.status === 429) {
      return "请求过于频繁，请稍后再试。";
    }
    if (requestError.status === 503) {
      return "导师服务暂时不可用，请稍后重试。";
    }
    return "消息发送失败，请重试。";
  })();

  return (
    <section aria-label="AI 导师" className={styles.tutorPanel}>
      <header className={styles.tutorHeader}>
        <div>
          <span className={styles.eyebrow}>{knowledgeBase.name}</span>
          <h2>AI 导师</h2>
          <p>当前上下文：{contextLabel}</p>
        </div>
        {status?.configured ? <p className={styles.tutorModel}>使用模型：{status.model}</p> : null}
      </header>

      {status === null && !statusFailed ? <p role="status">正在检查导师状态…</p> : null}
      {status && !status.configured ? (
        <p role="status">模型待配置：请在服务端 .env 中设置真实的 FARO_API_KEY 后重启服务。</p>
      ) : null}
      {statusFailed ? (
        <div className={styles.tutorError}>
          <p role="alert">导师状态暂时无法加载。</p>
          <button onClick={() => { setStatus(null); setStatusFailed(false); setStatusAttempt((value) => value + 1); }} type="button">重试</button>
        </div>
      ) : null}

      {conversation ? (
        <ol aria-label="导师对话" className={styles.tutorMessages}>
          {conversation.messages.map((message) => (
            <li className={message.role === "user" ? styles.tutorMessageUser : styles.tutorMessageAssistant} key={message.id}>
              <span className={styles.tutorMessageRole}>{message.role === "user" ? "你" : "AI 导师"}</span>
              <p>{message.content}</p>
              {message.citations.length > 0 ? (
                <div className={styles.tutorCitations}>
                  {message.citations.map((citation) => (
                    <button
                      aria-label={`打开引用：${citation.source_name}${citation.page_number === null ? "" : `，第 ${citation.page_number} 页`}`}
                      key={citation.id}
                      onClick={() => onOpenCitation(citation)}
                      type="button"
                    >
                      {citation.source_name}{citation.page_number === null ? "" : ` · 第 ${citation.page_number} 页`}
                    </button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}

      {pending ? <p aria-live="polite" role="status">导师正在思考…</p> : null}
      {errorMessage ? (
        <div className={styles.tutorError} id="tutor-request-error">
          <p role="alert">{errorMessage}</p>
          <button onClick={() => retryPrompt && void send(retryPrompt)} type="button">重试</button>
        </div>
      ) : null}

      <form className={styles.tutorForm} onSubmit={submit}>
        <label htmlFor="tutor-prompt">向 AI 导师提问</label>
        <textarea
          aria-describedby={errorMessage ? "tutor-request-error" : undefined}
          aria-invalid={errorMessage ? true : undefined}
          disabled={disabled}
          id="tutor-prompt"
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="围绕当前教材内容提问…"
          rows={3}
          value={prompt}
        />
        <button disabled={disabled || prompt.trim().length === 0} type="submit">发送</button>
      </form>
    </section>
  );
}
