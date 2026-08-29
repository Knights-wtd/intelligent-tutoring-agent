"use client";

import type { KnowledgeCandidateBatch } from "@/lib/knowledge-api";

export type KnowledgeCandidateReviewProps = {
  batch: KnowledgeCandidateBatch;
  acceptedNoteIds: string[];
  acceptedLinkIds: string[];
  isRefreshing: boolean;
  isConfirming: boolean;
  /** Optional provider-specific explanation for the failed state. */
  failureMessage?: string;
  onRefresh: () => void;
  onToggleNote: (noteId: string) => void;
  onToggleLink: (linkId: string) => void;
  onConfirm: () => void;
};

export function KnowledgeCandidateReview({
  batch,
  acceptedNoteIds,
  acceptedLinkIds,
  isRefreshing,
  isConfirming,
  failureMessage,
  onRefresh,
  onToggleNote,
  onToggleLink,
  onConfirm,
}: KnowledgeCandidateReviewProps) {
  return (
    <section aria-label="知识候选审核">
      {batch.state === "processing" ? (
        <>
          <p role="status">正在识别章、节、小节并生成候选…</p>
          <button disabled={isRefreshing} onClick={onRefresh} type="button">
            刷新候选状态
          </button>
        </>
      ) : null}
      {batch.state === "failed" ? (
        <p role="alert">
          {failureMessage ?? "候选生成失败，请重新发起生成。"}
        </p>
      ) : null}
      {batch.state === "confirmed" ? <p>已写入正式知识库</p> : null}
      {batch.state === "needs_review" ? (
        <>
          <CandidateNoteGroup
            acceptedIds={acceptedNoteIds}
            notes={batch.notes.filter((note) =>
              ["chapter", "section", "subsection"].includes(note.kind),
            )}
            onToggle={onToggleNote}
            title="结构候选"
          />
          <CandidateNoteGroup
            acceptedIds={acceptedNoteIds}
            notes={batch.notes.filter(
              (note) => !["chapter", "section", "subsection"].includes(note.kind),
            )}
            onToggle={onToggleNote}
            title="知识笔记候选"
          />
          <CandidateLinkGroup
            acceptedIds={acceptedLinkIds}
            links={batch.links.filter((link) => link.kind === "structure")}
            onToggle={onToggleLink}
            title="结构链接"
          />
          <CandidateLinkGroup
            acceptedIds={acceptedLinkIds}
            links={batch.links.filter((link) => link.kind === "term")}
            onToggle={onToggleLink}
            title="重复术语链接"
          />
          <button
            disabled={isConfirming || acceptedNoteIds.length === 0}
            onClick={onConfirm}
            type="button"
          >
            {isConfirming ? "正在写入…" : "确认并生成层级知识库"}
          </button>
        </>
      ) : null}
    </section>
  );
}

function CandidateNoteGroup({
  title,
  notes,
  acceptedIds,
  onToggle,
}: {
  title: string;
  notes: KnowledgeCandidateBatch["notes"];
  acceptedIds: string[];
  onToggle: (noteId: string) => void;
}) {
  return (
    <>
      <h3>{title}</h3>
      {notes.map((note) => (
        <label key={note.id}>
          <input
            checked={acceptedIds.includes(note.id)}
            onChange={() => onToggle(note.id)}
            type="checkbox"
          />
          <span>{note.title}</span>
        </label>
      ))}
    </>
  );
}

function CandidateLinkGroup({
  title,
  links,
  acceptedIds,
  onToggle,
}: {
  title: string;
  links: KnowledgeCandidateBatch["links"];
  acceptedIds: string[];
  onToggle: (linkId: string) => void;
}) {
  return (
    <>
      <h3>{title}</h3>
      {links.map((link) => (
        <label key={link.id}>
          <input
            checked={acceptedIds.includes(link.id)}
            onChange={() => onToggle(link.id)}
            type="checkbox"
          />
          <span>{link.context}</span>
        </label>
      ))}
    </>
  );
}
