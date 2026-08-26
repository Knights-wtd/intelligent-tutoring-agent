import { beforeEach, describe, expect, it, vi } from "vitest";

import { readWorkspacePreference, writeWorkspacePreference } from "./workspace-preferences";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("workspace preferences", () => {
  it("round-trips only the selected knowledge base and active tab", () => {
    writeWorkspacePreference("personal", {
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });

    expect(JSON.parse(localStorage.getItem("workspace:personal") ?? "null")).toEqual({
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });
    expect(readWorkspacePreference("personal")).toEqual({
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });
  });

  it("keeps workspace preferences isolated by space", () => {
    writeWorkspacePreference("personal", {
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });
    writeWorkspacePreference("math", {
      selectedKnowledgeBaseId: "geometry",
      activeTabId: "practice",
    });

    expect(JSON.parse(localStorage.getItem("workspace:personal") ?? "null")).toEqual({
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });
    expect(JSON.parse(localStorage.getItem("workspace:math") ?? "null")).toEqual({
      selectedKnowledgeBaseId: "geometry",
      activeTabId: "practice",
    });

    expect(readWorkspacePreference("personal")).toEqual({
      selectedKnowledgeBaseId: "wireless",
      activeTabId: "graph:wireless",
    });
    expect(readWorkspacePreference("math")).toEqual({
      selectedKnowledgeBaseId: "geometry",
      activeTabId: "practice",
    });
  });

  it.each([
    "not-json",
    "null",
    "[]",
    '{"activeTabId":7}',
    '{"selectedKnowledgeBaseId":"wireless","activeTabId":"today","extra":true}',
    '{"selectedKnowledgeBaseId":"wireless","activeTabId":"settings"}',
    '{"selectedKnowledgeBaseId":"../wireless","activeTabId":"knowledge"}',
    '{"selectedKnowledgeBaseId":"wireless","activeTabId":"graph:"}',
    '{"selectedKnowledgeBaseId":"wireless","activeTabId":"graph:bad id"}',
  ])("rejects stale or malformed stored workspace preferences: %s", (stored) => {
    localStorage.setItem("workspace:personal", stored);
    expect(readWorkspacePreference("personal")).toBeNull();
  });

  it("allows an absent knowledge selection for a known fixed tab", () => {
    localStorage.setItem("workspace:personal", '{"selectedKnowledgeBaseId":null,"activeTabId":"today"}');
    expect(readWorkspacePreference("personal")).toEqual({
      selectedKnowledgeBaseId: null,
      activeTabId: "today",
    });
  });

  it("silently falls back when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked");
    });
    expect(readWorkspacePreference("personal")).toBeNull();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full");
    });
    expect(() =>
      writeWorkspacePreference("personal", {
        selectedKnowledgeBaseId: null,
        activeTabId: "knowledge",
      }),
    ).not.toThrow();
  });
});