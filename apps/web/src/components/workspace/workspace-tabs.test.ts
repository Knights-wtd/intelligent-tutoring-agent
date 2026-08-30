import { describe, expect, it } from "vitest";

import { initialWorkspaceTabs, reduceWorkspaceTabs } from "./workspace-tabs";

describe("reduceWorkspaceTabs", () => {
  it("starts with the three fixed tabs", () => {
    expect(initialWorkspaceTabs).toEqual({
      tabs: [
        { id: "today", kind: "today", label: "今日任务" },
        { id: "knowledge", kind: "knowledge", label: "知识库" },
        { id: "practice", kind: "practice", label: "题库练习" },
      ],
      activeTabId: "today",
    });
  });

  it("deduplicates a graph tab by knowledge base", () => {
    const once = reduceWorkspaceTabs(initialWorkspaceTabs, {
      type: "open-graph",
      knowledgeBaseId: "wireless",
      knowledgeBaseName: "无线通信",
    });
    const twice = reduceWorkspaceTabs(once, {
      type: "open-graph",
      knowledgeBaseId: "wireless",
      knowledgeBaseName: "无线通信",
    });

    expect(twice.tabs.filter((tab) => tab.id === "graph:wireless")).toHaveLength(1);
    expect(twice.activeTabId).toBe("graph:wireless");
  });

  it("focuses only a tab that is currently open", () => {
    const focused = reduceWorkspaceTabs(initialWorkspaceTabs, { type: "focus", tabId: "practice" });
    const ignored = reduceWorkspaceTabs(focused, { type: "focus", tabId: "graph:missing" });

    expect(focused.activeTabId).toBe("practice");
    expect(ignored).toBe(focused);
  });

  it("closes an active graph safely and ignores fixed or unknown tabs", () => {
    const withGraph = reduceWorkspaceTabs(initialWorkspaceTabs, {
      type: "open-graph",
      knowledgeBaseId: "wireless",
      knowledgeBaseName: "无线通信",
    });
    const closed = reduceWorkspaceTabs(withGraph, { type: "close", tabId: "graph:wireless" });

    expect(closed.tabs.some((tab) => tab.id === "graph:wireless")).toBe(false);
    expect(closed.activeTabId).toBe("practice");
    expect(reduceWorkspaceTabs(closed, { type: "close", tabId: "today" })).toBe(closed);
    expect(reduceWorkspaceTabs(closed, { type: "close", tabId: "graph:missing" })).toBe(closed);
  });

  it("focuses the previous tab when closing the active graph among multiple graphs", () => {
    const first = reduceWorkspaceTabs(initialWorkspaceTabs, {
      type: "open-graph",
      knowledgeBaseId: "wireless",
      knowledgeBaseName: "无线通信",
    });
    const second = reduceWorkspaceTabs(first, {
      type: "open-graph",
      knowledgeBaseId: "digital",
      knowledgeBaseName: "数字通信",
    });
    const closed = reduceWorkspaceTabs(second, { type: "close", tabId: "graph:digital" });

    expect(closed.activeTabId).toBe("graph:wireless");
  });
  it("updates the practice question and focuses the practice tab", () => {
    const next = reduceWorkspaceTabs(initialWorkspaceTabs, {
      type: "open-practice",
      questionVersionId: "question-2",
    });

    expect(next.activeTabId).toBe("practice");
    expect(next.tabs.find((tab) => tab.id === "practice")).toMatchObject({
      questionVersionId: "question-2",
    });
  });
});