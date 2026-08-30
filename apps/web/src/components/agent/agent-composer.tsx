"use client";

import { useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import type {
  AgentAttachmentReference,
  AgentLinkedContext,
  AgentSendRequest,
} from "@/lib/agent-api";
import type { AgentSessionState } from "@/lib/agent-events";

import styles from "./agent-conversation.module.css";

export interface AgentComposerProps {
  disabled?: boolean;
  state?: AgentSessionState;
  linkedContexts: AgentLinkedContext[];
  attachments?: AgentAttachmentReference[];
  skill?: string;
  agent?: string;
  onSend: (request: AgentSendRequest) => void | Promise<void>;
  onStop?: () => void | Promise<void>;
  onResume?: () => void | Promise<void>;
  onRemoveLinkedContext?: (index: number) => void;
  onRemoveAttachment?: (id: string) => void;
}

function contextLabel(context: AgentLinkedContext, index: number): string {
  const base = context.label ?? context.source_name ?? context.path ?? `上下文 ${index + 1}`;
  return context.heading ? `${base} · ${context.heading}` : base;
}

export function AgentComposer({
  disabled = false,
  state = "waiting_input",
  linkedContexts,
  attachments = [],
  skill,
  agent,
  onSend,
  onStop,
  onResume,
  onRemoveLinkedContext,
  onRemoveAttachment,
}: AgentComposerProps) {
  const [text, setText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const composingRef = useRef(false);
  const canSubmit = (
    state === "waiting_input"
    && text.trim().length > 0
    && !disabled
    && !isSending
  );

  async function submit() {
    if (!canSubmit) return;

    const request: AgentSendRequest = {
      text,
      ...(linkedContexts.length > 0 ? { linked_contexts: linkedContexts } : {}),
      ...(attachments.length > 0 ? { attachments } : {}),
      ...(skill ? { skill } : {}),
      ...(agent ? { agent } : {}),
    };

    setIsSending(true);
    try {
      await onSend(request);
      setText("");
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (composingRef.current || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  }

  const isRunning = state === "running";
  const canResume = state === "stopped" || state === "failed";

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      {(linkedContexts.length > 0 || attachments.length > 0 || skill || agent) && (
        <div className={styles.referenceTray} aria-label="已关联内容">
          {linkedContexts.map((context, index) => (
            <span className={styles.referenceChip} key={`${context.vault_file_id ?? context.path ?? "context"}:${index}`}>
              <span>{contextLabel(context, index)}</span>
              {onRemoveLinkedContext && (
                <button
                  aria-label={`移除 ${contextLabel(context, index)}`}
                  className={styles.chipButton}
                  disabled={disabled}
                  onClick={() => onRemoveLinkedContext(index)}
                  type="button"
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {attachments.map((attachment) => (
            <span className={styles.referenceChip} key={attachment.id}>
              <span>{attachment.name ?? attachment.id}</span>
              {onRemoveAttachment && (
                <button
                  aria-label={`移除 ${attachment.name ?? attachment.id}`}
                  className={styles.chipButton}
                  disabled={disabled}
                  onClick={() => onRemoveAttachment(attachment.id)}
                  type="button"
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {skill && <span className={styles.referenceChip}>Skill: {skill}</span>}
          {agent && <span className={styles.referenceChip}>@{agent}</span>}
        </div>
      )}

      <label className={styles.inputLabel}>
        <span className={styles.visuallyHidden}>向 Agent 发送消息</span>
        <textarea
          aria-label="向 Agent 发送消息"
          className={styles.textarea}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onKeyDown={handleKeyDown}
          placeholder="询问知识库、网页，或让 Agent 操作工作区…"
          rows={3}
          value={text}
        />
      </label>

      <div className={styles.composerFooter}>
        <span className={styles.shortcutHint}>Enter 发送 · Shift+Enter 换行</span>
        {isRunning ? (
          <button
            className={styles.stopButton}
            disabled={disabled || !onStop}
            onClick={() => void onStop?.()}
            type="button"
          >
            停止
          </button>
        ) : canResume ? (
          <button
            className={styles.resumeButton}
            disabled={disabled || !onResume}
            onClick={() => void onResume?.()}
            type="button"
          >
            继续
          </button>
        ) : (
          <button className={styles.sendButton} disabled={!canSubmit} type="submit">
            {isSending ? "发送中…" : "发送"}
          </button>
        )}
      </div>
    </form>
  );
}
