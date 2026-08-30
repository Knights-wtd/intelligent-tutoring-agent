"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AgentComposer } from "@/components/agent/agent-composer";
import { AgentMessageList } from "@/components/agent/agent-message-list";
import type {
  ReadableVaultScope,
  VaultCitationTarget,
} from "@/components/agent/agent-message-list";
import {
  AGENT_SESSION_PREFERENCE_KEY,
  AGENT_SEQUENCE_QUERY_PARAMETER,
  AGENT_SESSION_QUERY_PARAMETER,
  AgentSessionSidebar,
  encodeAgentSessionPreference,
  resolveAgentSessionPreference,
} from "@/components/agent/agent-session-sidebar";
import {
  AgentSettings,
  FARO_CONTEXT_WINDOW,
  FARO_MODEL,
  FARO_PROVIDER,
  fixedAgentServiceSettings,
} from "@/components/agent/agent-settings";
import type { AgentSettingsValue } from "@/components/agent/agent-settings";
import { AgentSidecarPreview } from "@/components/agent/agent-sidecar-preview";
import { AgentToolCard } from "@/components/agent/agent-tool-card";
import {
  AgentApiError,
  agentApi,
  connectAgentEvents,
} from "@/lib/agent-api";
import type {
  AgentConnectionState,
  AgentDiagnostics,
  AgentEventConnection,
  AgentLinkedContext,
  AgentSendRequest,
  AgentSession,
  AgentSessionSummary,
  AgentSettings as AgentApiSettings,
} from "@/lib/agent-api";
import {
  emptyAgentView,
  reduceAgentEvents,
} from "@/lib/agent-events";
import type {
  AgentSessionState,
  AgentToolView,
  AgentView,
} from "@/lib/agent-events";

import styles from "./agent-panel.module.css";

export interface AgentPanelCitationTarget extends VaultCitationTarget {
  spaceId: string;
}

export interface AgentPanelProps {
  space: { id: string; name: string };
  knowledgeBase: { id: string; name: string };
  contextLabel: string;
  linkedContexts?: AgentLinkedContext[];
  joinedSpaceIds?: readonly string[];
  readableVaultScopes?: readonly ReadableVaultScope[];
  onOpenCitation: (citation: AgentPanelCitationTarget) => void;
}

type RuntimeFailure = {
  message: string;
  status?: number;
};

type FailedTurn = {
  sessionId: string;
  request: AgentSendRequest;
  idempotencyKey: string;
};

function failureOf(error: unknown): RuntimeFailure {
  if (error instanceof AgentApiError) {
    return {
      message: error.detail ?? error.message,
      status: error.status,
    };
  }
  return {
    message: error instanceof Error ? error.message : "Agent Runtime request failed",
  };
}

function isFaroSession(session: AgentSessionSummary): boolean {
  return session.is_legacy !== true
    && session.provider === FARO_PROVIDER
    && session.model === FARO_MODEL;
}

function isWritableSession(session: AgentSessionSummary): boolean {
  return isFaroSession(session)
    && session.state !== "failed"
    && session.state !== "archived";
}

function asReadOnlyHistory(session: AgentSessionSummary): AgentSessionSummary {
  return isFaroSession(session) ? session : { ...session, is_legacy: true };
}

function normalizeSessions(sessions: readonly AgentSessionSummary[]): AgentSessionSummary[] {
  return sessions.map(asReadOnlyHistory);
}

function upsertSession(
  sessions: readonly AgentSessionSummary[],
  session: AgentSessionSummary,
): AgentSessionSummary[] {
  const index = sessions.findIndex((item) => item.id === session.id);
  if (index < 0) return [session, ...sessions];
  return sessions.map((item, itemIndex) => itemIndex === index ? session : item);
}

function randomIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function connectionLabel(state: AgentConnectionState | null): string {
  if (!state) return "未连接";
  switch (state.status) {
    case "connecting":
      return "正在连接…";
    case "open":
      return `已连接 · cursor ${state.after}`;
    case "reconnecting":
      return `正在重连（第 ${state.attempt} 次）· cursor ${state.after}`;
    case "unauthorized":
      return "连接未授权";
    case "error":
      return "连接错误";
    case "closed":
      return "连接已关闭";
  }
}

function sessionState(
  view: AgentView,
  sessions: readonly AgentSessionSummary[],
  selectedSessionId: string | null,
): AgentSessionState {
  if (view.sessionState) return view.sessionState;
  return sessions.find((item) => item.id === selectedSessionId)?.state ?? "waiting_input";
}

function asSubagentTool(
  subagent: AgentView["subagents"][string],
): AgentToolView {
  return {
    id: `subagent:${subagent.id}`,
    turnId: subagent.turnId,
    name: subagent.name,
    kind: "subagent",
    state: subagent.state === "completed" ? "completed" : "running",
    output: subagent.result,
    startedAt: subagent.startedAt,
    completedAt: subagent.completedAt,
    payload: {
      ...subagent.payload,
      subagent_id: subagent.id,
    },
  };
}

export function AgentPanel({
  space,
  knowledgeBase,
  contextLabel,
  linkedContexts,
  joinedSpaceIds,
  readableVaultScopes,
  onOpenCitation,
}: AgentPanelProps) {
  const defaultLinkedContexts = useMemo<AgentLinkedContext[]>(
    () => linkedContexts ?? [{ knowledge_base_id: knowledgeBase.id }],
    [knowledgeBase.id, linkedContexts],
  );
  const vaultCitationAccess = useMemo(() => ({
    joinedSpaceIds: joinedSpaceIds ?? [space.id],
    readableVaultScopes: readableVaultScopes ?? [{
      spaceId: space.id,
      knowledgeBaseId: knowledgeBase.id,
    }],
  }), [joinedSpaceIds, knowledgeBase.id, readableVaultScopes, space.id]);
  const [sessions, setSessions] = useState<AgentSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [readOnlyHistorySelected, setReadOnlyHistorySelected] = useState(false);
  const [settings, setSettings] = useState<AgentSettingsValue>(() => fixedAgentServiceSettings({}));
  const [diagnostics, setDiagnostics] = useState<AgentDiagnostics>({});
  const [view, setView] = useState<AgentView>(() => emptyAgentView());
  const [connection, setConnection] = useState<AgentConnectionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [runtimeFailure, setRuntimeFailure] = useState<RuntimeFailure | null>(null);
  const [failedTurn, setFailedTurn] = useState<FailedTurn | null>(null);
  const [retryingFailedTurn, setRetryingFailedTurn] = useState(false);
  const [retryGeneration, setRetryGeneration] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"sessions" | "settings">("sessions");

  const mountedRef = useRef(false);
  const sessionIdRef = useRef<string | null>(null);
  const settingsRef = useRef<AgentSettingsValue>(fixedAgentServiceSettings({}));
  const viewRef = useRef<AgentView>(emptyAgentView());
  const connectionRef = useRef<AgentEventConnection | null>(null);
  const bootstrapRef = useRef<AbortController | null>(null);
  const replayRef = useRef<AbortController | null>(null);
  const actionControllersRef = useRef(new Set<AbortController>());
  const replayingRef = useRef(false);
  const settingsTriggerRef = useRef<HTMLButtonElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);

  function publishView(next: AgentView) {
    viewRef.current = next;
    setView(next);
  }

  function persistCursor(sessionId: string, after: number) {
    if (typeof window === "undefined") return;
    const preference = { sessionId, lastPersistedSequence: after };
    window.localStorage.setItem(
      AGENT_SESSION_PREFERENCE_KEY,
      encodeAgentSessionPreference(preference),
    );
    const url = new URL(window.location.href);
    url.searchParams.set(AGENT_SESSION_QUERY_PARAMETER, sessionId);
    url.searchParams.set(AGENT_SEQUENCE_QUERY_PARAMETER, String(after));
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function closeConnection() {
    connectionRef.current?.close();
    connectionRef.current = null;
  }

  function setCurrentSession(session: AgentSessionSummary) {
    sessionIdRef.current = session.id;
    setSelectedSessionId(session.id);
    setReadOnlyHistorySelected(!isWritableSession(session));
  }

  async function recoverGap(sessionId: string, after: number) {
    if (replayingRef.current || sessionIdRef.current !== sessionId) return;
    replayingRef.current = true;
    closeConnection();
    replayRef.current?.abort();
    const controller = new AbortController();
    replayRef.current = controller;
    try {
      const replay = await agentApi.events(sessionId, after, controller.signal);
      if (controller.signal.aborted || sessionIdRef.current !== sessionId) return;
      let next = viewRef.current;
      for (const incoming of replay.events) {
        next = reduceAgentEvents(next, incoming);
        if (next.needsReplay) {
          throw new Error("Agent event replay still contains a sequence gap");
        }
      }
      if (replay.last_sequence !== next.lastSequence) {
        throw new Error("Agent event replay cursor does not match the persisted events");
      }
      publishView(next);
      persistCursor(sessionId, next.lastSequence);
      openConnection(sessionId, next.lastSequence);
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        setRuntimeFailure(failureOf(error));
      }
    } finally {
      if (replayRef.current === controller) replayRef.current = null;
      replayingRef.current = false;
    }
  }

  function openConnection(sessionId: string, after: number) {
    closeConnection();
    try {
      connectionRef.current = connectAgentEvents(
        sessionId,
        after,
        (incoming) => {
          if (sessionIdRef.current !== sessionId) return;
          const current = viewRef.current;
          const next = reduceAgentEvents(current, incoming);
          if (next.needsReplay) {
            void recoverGap(sessionId, current.lastSequence);
            return;
          }
          publishView(next);
          persistCursor(sessionId, next.lastSequence);
        },
        (nextState) => {
          if (sessionIdRef.current === sessionId && mountedRef.current) {
            setConnection(nextState);
          }
        },
      );
    } catch (error) {
      setRuntimeFailure(failureOf(error));
    }
  }

  async function replaySession(
    sessionId: string,
    controller: AbortController,
    readOnly = false,
  ) {
    closeConnection();
    replayRef.current?.abort();
    replayRef.current = controller;
    publishView(emptyAgentView());
    setConnection(null);

    const replay = await agentApi.events(sessionId, 0, controller.signal);
    if (controller.signal.aborted || sessionIdRef.current !== sessionId) return;
    let next = emptyAgentView();
    for (const incoming of replay.events) {
      next = reduceAgentEvents(next, incoming);
      if (next.needsReplay) {
        throw new Error("Agent event history contains a sequence gap");
      }
    }
    if (replay.last_sequence !== next.lastSequence) {
      throw new Error("Agent event history cursor does not match the persisted events");
    }
    publishView(next);
    persistCursor(sessionId, next.lastSequence);
    if (!readOnly) openConnection(sessionId, next.lastSequence);
  }

  async function createSession(controller: AbortController): Promise<AgentSession> {
    return agentApi.create({
      knowledge_base_id: knowledgeBase.id,
      provider: FARO_PROVIDER,
      model: FARO_MODEL,
      context_window: FARO_CONTEXT_WINDOW,
      title: knowledgeBase.name,
      linked_contexts: defaultLinkedContexts,
    }, controller.signal);
  }

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    bootstrapRef.current?.abort();
    bootstrapRef.current = controller;
    replayRef.current?.abort();
    closeConnection();
    sessionIdRef.current = null;
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      setSelectedSessionId(null);
      setLoading(true);
      setRuntimeFailure(null);
      setFailedTurn(null);
      setRetryingFailedTurn(false);
      setConnection(null);
      publishView(emptyAgentView());
    });

    async function bootstrap() {
      try {
        const [loadedSessions, loadedSettings, loadedDiagnostics] = await Promise.all([
          agentApi.list(controller.signal),
          agentApi.settings(controller.signal),
          agentApi.diagnostics(controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const safeSettings = fixedAgentServiceSettings(loadedSettings);
        settingsRef.current = safeSettings;
        setSettings(safeSettings);
        setDiagnostics(loadedDiagnostics);

        const nextSessions = normalizeSessions(loadedSessions);
        const writableSessions = nextSessions.filter(isWritableSession);
        const preference = resolveAgentSessionPreference({
          search: window.location.search,
          storedPreference: window.localStorage.getItem(AGENT_SESSION_PREFERENCE_KEY),
          sessions: writableSessions,
        });
        let selected = preference.sessionId
          ? writableSessions.find((item) => item.id === preference.sessionId)
          : writableSessions.find((item) => item.state !== "archived");
        if (!selected) {
          selected = await createSession(controller);
          if (controller.signal.aborted) return;
          nextSessions.unshift(selected);
        }
        setSessions(nextSessions);
        setCurrentSession(selected);
        await replaySession(selected.id, controller);
      } catch (error) {
        if (!controller.signal.aborted) {
          setRuntimeFailure(failureOf(error));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void bootstrap();
    return () => {
      mountedRef.current = false;
      controller.abort();
      replayRef.current?.abort();
      closeConnection();
    };
    // A knowledge-base change deliberately starts a fresh controller lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledgeBase.id, retryGeneration]);

  useEffect(() => () => {
    for (const controller of actionControllersRef.current) controller.abort();
    actionControllersRef.current.clear();
  }, []);

  useEffect(() => {
    if (!settingsOpen) return;
    settingsCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeSettings();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [settingsOpen]);

  function closeSettings() {
    setSettingsOpen(false);
    queueMicrotask(() => settingsTriggerRef.current?.focus());
  }

  function actionController(): AbortController {
    const controller = new AbortController();
    actionControllersRef.current.add(controller);
    return controller;
  }

  function finishAction(controller: AbortController) {
    actionControllersRef.current.delete(controller);
  }

  function updateSessionState(sessionId: string, state: AgentSessionState) {
    setSessions((current) => current.map((item) => (
      item.id === sessionId ? { ...item, state } : item
    )));
    if (sessionIdRef.current === sessionId) {
      publishView({ ...viewRef.current, sessionState: state });
    }
  }

  async function selectSession(sessionId: string) {
    const controller = actionController();
    setRuntimeFailure(null);
    setFailedTurn(null);
    try {
      const selected = await agentApi.get(sessionId, controller.signal);
      if (controller.signal.aborted) return;
      const safeSelected = asReadOnlyHistory(selected);
      setSessions((current) => upsertSession(current, safeSelected));
      setCurrentSession(safeSelected);
      await replaySession(safeSelected.id, controller, !isWritableSession(safeSelected));
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function startNewSession() {
    const controller = actionController();
    setRuntimeFailure(null);
    setFailedTurn(null);
    try {
      const created = await createSession(controller);
      if (controller.signal.aborted) return;
      setSessions((current) => upsertSession(current, created));
      setCurrentSession(created);
      await replaySession(created.id, controller);
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function archiveSession(sessionId: string) {
    const controller = actionController();
    try {
      await agentApi.archive(sessionId, controller.signal);
      if (!controller.signal.aborted) updateSessionState(sessionId, "archived");
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function stopSession(sessionId: string) {
    try {
      const stopped = await agentApi.stop(sessionId);
      setSessions((current) => upsertSession(current, stopped));
      updateSessionState(sessionId, stopped.state);
    } catch (error) {
      setRuntimeFailure(failureOf(error));
    }
  }

  async function resumeSession(sessionId: string) {
    try {
      const resumed = await agentApi.resume(sessionId);
      setSessions((current) => upsertSession(current, resumed));
      updateSessionState(sessionId, resumed.state);
    } catch (error) {
      setRuntimeFailure(failureOf(error));
    }
  }

  async function branchSession(
    kind: "rewind" | "fork",
    sessionId: string,
    afterSequence: number,
  ) {
    const controller = actionController();
    try {
      const branched = await agentApi[kind](sessionId, { after_sequence: afterSequence });
      if (controller.signal.aborted) return;
      setSessions((current) => upsertSession(current, branched));
      setCurrentSession(branched);
      await replaySession(branched.id, controller);
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function send(request: AgentSendRequest) {
    const sessionId = sessionIdRef.current;
    const selected = sessions.find((session) => session.id === sessionId);
    if (!sessionId || !selected || !isWritableSession(selected)) return;
    const idempotencyKey = randomIdempotencyKey();
    setRuntimeFailure(null);
    setFailedTurn(null);
    try {
      await agentApi.send(sessionId, request, idempotencyKey);
      updateSessionState(sessionId, "running");
    } catch (error) {
      setFailedTurn({ sessionId, request, idempotencyKey });
      setRuntimeFailure(failureOf(error));
      updateSessionState(sessionId, "failed");
    }
  }

  async function retryRuntime() {
    if (!failedTurn) {
      setRetryGeneration((current) => current + 1);
      return;
    }
    setRetryingFailedTurn(true);
    try {
      await agentApi.send(failedTurn.sessionId, failedTurn.request, failedTurn.idempotencyKey);
      setRuntimeFailure(null);
      setFailedTurn(null);
      updateSessionState(failedTurn.sessionId, "running");
    } catch (error) {
      setRuntimeFailure(failureOf(error));
      updateSessionState(failedTurn.sessionId, "failed");
    } finally {
      setRetryingFailedTurn(false);
    }
  }

  async function updateSettings(value: AgentSettingsValue) {
    const controller = actionController();
    const safeValue = fixedAgentServiceSettings(value);
    settingsRef.current = safeValue;
    setSettings(safeValue);
    try {
      const saved = await agentApi.updateSettings(safeValue as AgentApiSettings, controller.signal);
      if (!controller.signal.aborted) {
        const safeSaved = fixedAgentServiceSettings(saved);
        settingsRef.current = safeSaved;
        setSettings(safeSaved);
      }
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  const selectedState = sessionState(view, sessions, selectedSessionId);
  const tools = Object.values(view.tools);
  const subagents = Object.values(view.subagents).map(asSubagentTool);
  const sidecars = Object.values(view.sidecars);

  return (
    <section aria-label="Workspace Agent" className={styles.panel}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>{space.name} · {knowledgeBase.name}</span>
          <h2>Workspace Agent</h2>
          <p>当前上下文：{contextLabel}</p>
        </div>
        <div className={styles.headerActions}>
          <p aria-live="polite" className={styles.connectionStatus}>
            {connectionLabel(connection)}
          </p>
          <button
            aria-expanded={settingsOpen}
            aria-haspopup="dialog"
            aria-label="打开助教设置"
            className={styles.settingsTrigger}
            onClick={() => setSettingsOpen(true)}
            ref={settingsTriggerRef}
            type="button"
          >
            <span aria-hidden="true">⚙</span>
            <span>设置</span>
          </button>
        </div>
      </header>

      {runtimeFailure ? (
        <div className={styles.runtimeError}>
          <div>
            <strong role="alert">Runtime unavailable</strong>
            <p>{runtimeFailure.status ? `HTTP ${runtimeFailure.status} · ` : ""}{runtimeFailure.message}</p>
          </div>
          <button
            disabled={retryingFailedTurn}
            onClick={() => void retryRuntime()}
            type="button"
          >
            {failedTurn ? "重试失败的 Agent 消息" : "重试 Agent Runtime"}
          </button>
        </div>
      ) : null}

      {loading ? <p role="status">正在加载 Agent Runtime…</p> : null}

      <div className={styles.layout}>
        <main className={styles.conversation}>
          {readOnlyHistorySelected ? (
            <p className={styles.readOnlyNotice} role="status">
              此旧会话仅供查看。继续对话请新建 Faro · {FARO_MODEL} 会话。
            </p>
          ) : null}
          <AgentMessageList
            onOpenVaultCitation={(citation) => {
              if (!citation.spaceId) return;
              onOpenCitation({ ...citation, spaceId: citation.spaceId });
            }}
            vaultCitationAccess={vaultCitationAccess}
            view={view}
          />

          <section aria-label="Agent tools" className={styles.toolList}>
            {[...tools, ...subagents].map((tool) => (
              <AgentToolCard key={tool.id} tool={tool} />
            ))}
          </section>

          <section aria-label="Agent sidecars" className={styles.sidecarList}>
            {sidecars.map((sidecar) => (
              <AgentSidecarPreview key={sidecar.id} sidecar={sidecar} />
            ))}
          </section>

          <section aria-label="Agent composer" className={styles.composerRegion}>
            <AgentComposer
              disabled={loading || !selectedSessionId || readOnlyHistorySelected || runtimeFailure !== null}
              linkedContexts={defaultLinkedContexts}
              onResume={selectedSessionId && !readOnlyHistorySelected ? () => resumeSession(selectedSessionId) : undefined}
              onSend={send}
              onStop={selectedSessionId && !readOnlyHistorySelected ? () => stopSession(selectedSessionId) : undefined}
              state={selectedState}
            />
          </section>
        </main>
      </div>

      {settingsOpen ? (
        <div className={styles.settingsOverlay}>
          <button
            aria-label="关闭助教设置遮罩"
            className={styles.settingsBackdrop}
            onClick={closeSettings}
            type="button"
          />
          <section
            aria-label="Workspace Agent 设置"
            aria-modal="true"
            className={styles.settingsDialog}
            role="dialog"
          >
            <header className={styles.settingsDialogHeader}>
              <div>
                <span className={styles.eyebrow}>Workspace Agent</span>
                <h3>助教设置</h3>
                <p>管理会话记录、模型连接和工作区能力。</p>
              </div>
              <button
                aria-label="关闭助教设置"
                className={styles.settingsClose}
                onClick={closeSettings}
                ref={settingsCloseRef}
                type="button"
              >
                <span aria-hidden="true">×</span>
              </button>
            </header>

            <div aria-label="助教设置导航" className={styles.settingsTabs} role="tablist">
              <button
                aria-controls="agent-sessions-tabpanel"
                aria-selected={settingsTab === "sessions"}
                className={styles.settingsTab}
                id="agent-sessions-tab"
                onClick={() => setSettingsTab("sessions")}
                role="tab"
                type="button"
              >
                会话记录
              </button>
              <button
                aria-controls="agent-settings-tabpanel"
                aria-selected={settingsTab === "settings"}
                className={styles.settingsTab}
                id="agent-settings-tab"
                onClick={() => setSettingsTab("settings")}
                role="tab"
                type="button"
              >
                服务设置
              </button>
            </div>

            {settingsTab === "sessions" ? (
              <div aria-labelledby="agent-sessions-tab" id="agent-sessions-tabpanel" role="tabpanel">
                <AgentSessionSidebar
                  onArchive={archiveSession}
                  onCreate={startNewSession}
                  onFork={(sessionId, after) => branchSession("fork", sessionId, after)}
                  onResume={resumeSession}
                  onRewind={(sessionId, after) => branchSession("rewind", sessionId, after)}
                  onSelect={selectSession}
                  onStop={stopSession}
                  selectedSessionId={selectedSessionId}
                  sessions={sessions}
                />
              </div>
            ) : (
              <div aria-labelledby="agent-settings-tab" id="agent-settings-tabpanel" role="tabpanel">
                <AgentSettings
                  diagnostics={diagnostics}
                  onChange={updateSettings}
                  value={settings}
                />
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}