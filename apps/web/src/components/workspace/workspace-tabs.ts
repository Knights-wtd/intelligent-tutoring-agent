export type WorkspaceTab =
  | { id: "today"; kind: "today"; label: "今日任务" }
  | { id: "knowledge"; kind: "knowledge"; label: "知识库" }
  | { id: "practice"; kind: "practice"; label: "题库练习"; questionVersionId?: string }
  | { id: `graph:${string}`; kind: "graph"; label: string; knowledgeBaseId: string };

export type WorkspaceTabsState = {
  tabs: WorkspaceTab[];
  activeTabId: WorkspaceTab["id"];
};

export type WorkspaceTabsAction =
  | { type: "focus"; tabId: WorkspaceTab["id"] }
  | { type: "close"; tabId: WorkspaceTab["id"] }
  | { type: "open-graph"; knowledgeBaseId: string; knowledgeBaseName: string }
  | { type: "open-practice"; questionVersionId?: string };

export const initialWorkspaceTabs: WorkspaceTabsState = {
  tabs: [
    { id: "today", kind: "today", label: "今日任务" },
    { id: "knowledge", kind: "knowledge", label: "知识库" },
    { id: "practice", kind: "practice", label: "题库练习" },
  ],
  activeTabId: "today",
};

export function reduceWorkspaceTabs(
  state: WorkspaceTabsState,
  action: WorkspaceTabsAction,
): WorkspaceTabsState {
  switch (action.type) {
    case "focus": {
      if (!state.tabs.some((tab) => tab.id === action.tabId)) return state;
      if (state.activeTabId === action.tabId) return state;
      return { ...state, activeTabId: action.tabId };
    }

    case "open-graph": {
      const tabId = `graph:${action.knowledgeBaseId}` as const;
      const existingIndex = state.tabs.findIndex((tab) => tab.id === tabId);
      if (existingIndex < 0) {
        return {
          tabs: [
            ...state.tabs,
            {
              id: tabId,
              kind: "graph",
              label: action.knowledgeBaseName,
              knowledgeBaseId: action.knowledgeBaseId,
            },
          ],
          activeTabId: tabId,
        };
      }

      const existing = state.tabs[existingIndex];
      const tabs =
        existing.label === action.knowledgeBaseName
          ? state.tabs
          : state.tabs.map((tab, index) =>
              index === existingIndex && tab.kind === "graph"
                ? { ...tab, label: action.knowledgeBaseName }
                : tab,
            );
      if (tabs === state.tabs && state.activeTabId === tabId) return state;
      return { tabs, activeTabId: tabId };
    }

    case "close": {
      const closingIndex = state.tabs.findIndex(
        (tab) => tab.id === action.tabId && tab.kind === "graph",
      );
      if (closingIndex < 0) return state;

      const tabs = state.tabs.filter((_, index) => index !== closingIndex);
      if (state.activeTabId !== action.tabId) return { ...state, tabs };

      const adjacentTab = tabs[Math.max(0, closingIndex - 1)] ?? tabs[0];
      return {
        tabs,
        activeTabId: adjacentTab?.id ?? "today",
      };
    }

    case "open-practice": {
      const practice = state.tabs.find(
        (tab): tab is Extract<WorkspaceTab, { kind: "practice" }> => tab.kind === "practice",
      );
      if (
        practice?.questionVersionId === action.questionVersionId &&
        state.activeTabId === "practice"
      ) {
        return state;
      }

      return {
        tabs: state.tabs.map((tab) =>
          tab.kind === "practice"
            ? { ...tab, questionVersionId: action.questionVersionId }
            : tab,
        ),
        activeTabId: "practice",
      };
    }
  }
}