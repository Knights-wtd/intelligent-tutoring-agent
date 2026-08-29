import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeCandidateBatch } from "@/lib/knowledge-api";

import { KnowledgeCandidateReview } from "./knowledge-candidate-review";

const batch: KnowledgeCandidateBatch = {
  id: "batch-1",
  document_id: "doc-1",
  document_version_id: "version-1",
  generation_number: 1,
  state: "needs_review",
  failure_code: null,
  notes: [
    {
      id: "chapter-1",
      ordinal: 0,
      candidate_key: "chapter",
      title: "第一章",
      kind: "chapter",
      parent_key: null,
      markdown: "# 第一章",
      source_pointers: ["教材.docx#第一章"],
      review_state: "accepted",
    },
    {
      id: "concept-1",
      ordinal: 1,
      candidate_key: "concept",
      title: "核心概念",
      kind: "concept",
      parent_key: "chapter",
      markdown: "## 核心概念",
      source_pointers: ["教材.docx#核心概念"],
      review_state: "rejected",
    },
  ],
  links: [
    {
      id: "link-1",
      ordinal: 0,
      kind: "structure",
      relation: "contains",
      source_key: "chapter",
      target_key: "concept",
      source_pointer: "教材.docx#核心概念",
      occurrence: null,
      context: "第一章包含核心概念",
      review_state: "pending",
    },
  ],
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
};

describe("KnowledgeCandidateReview", () => {
  it("keeps the four candidate groups and delegates selection and confirmation", async () => {
    const user = userEvent.setup();
    const onToggleNote = vi.fn();
    const onToggleLink = vi.fn();
    const onConfirm = vi.fn();

    render(
      <KnowledgeCandidateReview
        acceptedLinkIds={["link-1"]}
        acceptedNoteIds={["chapter-1"]}
        batch={batch}
        isConfirming={false}
        isRefreshing={false}
        onConfirm={onConfirm}
        onRefresh={vi.fn()}
        onToggleLink={onToggleLink}
        onToggleNote={onToggleNote}
      />,
    );

    expect(screen.getByRole("heading", { name: "结构候选" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "知识笔记候选" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "结构链接" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "重复术语链接" })).toBeInTheDocument();

    const review = screen.getByRole("region", { name: "知识候选审核" });
    const chapter = within(review).getByRole("checkbox", { name: "第一章" });
    const concept = within(review).getByRole("checkbox", { name: "核心概念" });
    expect(chapter).toBeChecked();
    expect(concept).not.toBeChecked();

    await user.click(concept);
    await user.click(within(review).getByRole("checkbox", { name: "第一章包含核心概念" }));
    await user.click(screen.getByRole("button", { name: "确认并生成层级知识库" }));

    expect(onToggleNote).toHaveBeenCalledWith("concept-1");
    expect(onToggleLink).toHaveBeenCalledWith("link-1");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
