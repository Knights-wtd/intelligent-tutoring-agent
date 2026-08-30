import type { WorkspaceTab } from "./workspace-tabs";

export type WorkspacePreference = {
  selectedKnowledgeBaseId: string | null;
  activeTabId: WorkspaceTab["id"];
};

const fixedTabIds = new Set<WorkspaceTab["id"]>(["today", "knowledge", "practice"]);
const safeIdPattern = /^[A-Za-z0-9][A-Za-z0-9._~-]*$/u;
const legacyAssistantModes = new Set(["tutor", "agent"]);

function isSafeId(value: unknown): value is string {
  return typeof value === "string" && safeIdPattern.test(value);
}

function isActiveTabId(value: unknown): value is WorkspaceTab["id"] {
  if (typeof value !== "string") return false;
  if (fixedTabIds.has(value as WorkspaceTab["id"])) return true;
  return value.startsWith("graph:") && isSafeId(value.slice("graph:".length));
}

function parseWorkspacePreference(value: unknown): WorkspacePreference | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;

  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  const hasLegacyAssistantMode =
    keys.length === 3 && Object.prototype.hasOwnProperty.call(record, "assistantMode");
  if (
    (keys.length !== 2 && !hasLegacyAssistantMode) ||
    !Object.prototype.hasOwnProperty.call(record, "selectedKnowledgeBaseId") ||
    !Object.prototype.hasOwnProperty.call(record, "activeTabId")
  ) {
    return null;
  }
  if (
    !(record.selectedKnowledgeBaseId === null || isSafeId(record.selectedKnowledgeBaseId)) ||
    !isActiveTabId(record.activeTabId) ||
    (hasLegacyAssistantMode &&
      (typeof record.assistantMode !== "string" || !legacyAssistantModes.has(record.assistantMode)))
  ) {
    return null;
  }

  return {
    selectedKnowledgeBaseId: record.selectedKnowledgeBaseId,
    activeTabId: record.activeTabId,
  };
}

export function readWorkspacePreference(spaceId: string): WorkspacePreference | null {
  try {
    const stored = localStorage.getItem(`workspace:${spaceId}`);
    if (stored === null) return null;
    const parsed: unknown = JSON.parse(stored);
    return parseWorkspacePreference(parsed);
  } catch {
    return null;
  }
}

export function writeWorkspacePreference(
  spaceId: string,
  preference: WorkspacePreference,
): void {
  const persisted = parseWorkspacePreference({
    selectedKnowledgeBaseId: preference.selectedKnowledgeBaseId,
    activeTabId: preference.activeTabId,
  });
  if (persisted === null) return;

  try {
    localStorage.setItem(`workspace:${spaceId}`, JSON.stringify(persisted));
  } catch {
    // Preferences are best-effort when storage is unavailable or full.
  }
}
