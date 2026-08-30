"use client";

import type { AgentSessionSummary } from "@/lib/agent-api";

import styles from "./agent-settings.module.css";

export const AGENT_SESSION_PREFERENCE_KEY = "agent-session-preference-v1";
export const AGENT_SESSION_QUERY_PARAMETER = "agentSession";
export const AGENT_SEQUENCE_QUERY_PARAMETER = "agentAfter";

export interface AgentSessionPreference {
  sessionId: string | null;
  lastPersistedSequence: number;
}

export interface ResolveAgentSessionPreferenceOptions {
  search: string;
  storedPreference: string | null;
  sessions: readonly AgentSessionSummary[];
}

type SessionAction = (sessionId: string) => void | Promise<void>;
type BranchAction = (
  sessionId: string,
  afterSequence: number,
) => void | Promise<void>;

export interface AgentSessionSidebarProps {
  sessions: readonly AgentSessionSummary[];
  selectedSessionId?: string | null;
  onCreate?: () => void | Promise<void>;
  onSelect?: SessionAction;
  onArchive?: SessionAction;
  onStop?: SessionAction;
  onResume?: SessionAction;
  onRewind?: BranchAction;
  onFork?: BranchAction;
}

type SessionGroup = "active" | "warm" | "archived" | "legacy";

const GROUPS: ReadonlyArray<{ id: SessionGroup; label: string }> = [
  { id: "active", label: "Active" },
  { id: "warm", label: "Warm" },
  { id: "archived", label: "Archived" },
  { id: "legacy", label: "Legacy" },
];

function groupFor(session: AgentSessionSummary): SessionGroup {
  if (session.is_legacy) return "legacy";
  if (session.state === "archived") return "archived";
  if (session.state === "running") return "active";
  return "warm";
}

function nonNegativeSequence(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(numeric) && numeric >= 0 ? numeric : null;
}

function parseStoredPreference(raw: string | null): AgentSessionPreference | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (typeof parsed.sessionId !== "string" || !parsed.sessionId) return null;
    const sequence = nonNegativeSequence(parsed.lastPersistedSequence);
    if (sequence === null) return null;
    return { sessionId: parsed.sessionId, lastPersistedSequence: sequence };
  } catch {
    return null;
  }
}

export function resolveAgentSessionPreference({
  search,
  storedPreference,
  sessions,
}: ResolveAgentSessionPreferenceOptions): AgentSessionPreference {
  const available = new Set(sessions.map(({ id }) => id));
  const stored = parseStoredPreference(storedPreference);
  const parameters = new URLSearchParams(search);
  const urlSessionId = parameters.get(AGENT_SESSION_QUERY_PARAMETER);

  if (urlSessionId && available.has(urlSessionId)) {
    const urlSequence = nonNegativeSequence(
      parameters.get(AGENT_SEQUENCE_QUERY_PARAMETER),
    );
    const storedSequence = stored?.sessionId === urlSessionId
      ? stored.lastPersistedSequence
      : 0;
    return {
      sessionId: urlSessionId,
      lastPersistedSequence: urlSequence ?? storedSequence,
    };
  }

  if (stored && available.has(stored.sessionId ?? "")) return stored;
  return { sessionId: null, lastPersistedSequence: 0 };
}

export function encodeAgentSessionPreference(
  preference: AgentSessionPreference,
): string {
  const sequence = nonNegativeSequence(preference.lastPersistedSequence) ?? 0;
  return JSON.stringify({
    sessionId: preference.sessionId,
    lastPersistedSequence: sequence,
  });
}

function sessionAction(callback: SessionAction, sessionId: string) {
  return () => void callback(sessionId);
}

function branchAction(callback: BranchAction, session: AgentSessionSummary) {
  return () => void callback(session.id, session.last_event_sequence);
}

function SessionRow({
  session,
  selected,
  onSelect,
  onArchive,
  onStop,
  onResume,
  onRewind,
  onFork,
}: {
  session: AgentSessionSummary;
  selected: boolean;
  onSelect?: SessionAction;
  onArchive?: SessionAction;
  onStop?: SessionAction;
  onResume?: SessionAction;
  onRewind?: BranchAction;
  onFork?: BranchAction;
}) {
  const archived = session.state === "archived";
  const running = session.state === "running";
  const native = !session.is_legacy && !archived;

  return (
    <li className={styles.sessionRow} data-testid={`agent-session-${session.id}`}>
      <button
        aria-current={selected ? "page" : undefined}
        aria-label={`切换到${session.title}`}
        className={styles.sessionSelect}
        onClick={onSelect ? sessionAction(onSelect, session.id) : undefined}
        type="button"
      >
        <strong>{session.title}</strong>
        <span>{session.provider} · {session.model}</span>
        <small>{session.state} · seq {session.last_event_sequence}</small>
      </button>

      <div className={styles.sessionActions}>
        {!archived && onArchive ? (
          <button
            onClick={sessionAction(onArchive, session.id)}
            type="button"
          >
            归档
          </button>
        ) : null}
        {native && running && onStop ? (
          <button
            onClick={sessionAction(onStop, session.id)}
            type="button"
          >
            停止
          </button>
        ) : null}
        {native && !running && onResume ? (
          <button
            onClick={sessionAction(onResume, session.id)}
            type="button"
          >
            继续
          </button>
        ) : null}
        {native ? (
          <>
            {onRewind ? (
              <button
                onClick={branchAction(onRewind, session)}
                title={`回退 ${session.title}`}
                type="button"
              >
                回退
              </button>
            ) : null}
            {onFork ? (
              <button
                onClick={branchAction(onFork, session)}
                title={`分叉 ${session.title}`}
                type="button"
              >
                分叉
              </button>
            ) : null}
          </>
        ) : null}
      </div>
    </li>
  );
}

export function AgentSessionSidebar({
  sessions,
  selectedSessionId = null,
  onCreate,
  onSelect,
  onArchive,
  onStop,
  onResume,
  onRewind,
  onFork,
}: AgentSessionSidebarProps) {
  return (
    <nav aria-label="Agent sessions" className={styles.sessionSidebar}>
      <header className={styles.sessionHeader}>
        <div>
          <span className={styles.eyebrow}>Workspace agent</span>
          <strong>Sessions</strong>
        </div>
        {onCreate ? (
          <button onClick={() => void onCreate()} type="button">新建会话</button>
        ) : null}
      </header>

      <div className={styles.sessionGroups}>
        {GROUPS.map((group) => {
          const grouped = sessions.filter((item) => groupFor(item) === group.id);
          return (
            <section className={styles.sessionGroup} key={group.id}>
              <h2>{group.label}</h2>
              {grouped.length > 0 ? (
                <ul>
                  {grouped.map((item) => (
                    <SessionRow
                      key={item.id}
                      onArchive={onArchive}
                      onFork={onFork}
                      onResume={onResume}
                      onRewind={onRewind}
                      onSelect={onSelect}
                      onStop={onStop}
                      selected={item.id === selectedSessionId}
                      session={item}
                    />
                  ))}
                </ul>
              ) : (
                <p className={styles.emptyGroup}>None</p>
              )}
            </section>
          );
        })}
      </div>
    </nav>
  );
}
