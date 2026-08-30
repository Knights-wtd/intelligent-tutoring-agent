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
  knowledgeBaseId: string;
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

function isLegacySession(session: AgentSessionSummary): boolean {
  return session.is_legacy === true || session.legacy === true;
}

function normalizeSession<T extends AgentSessionSummary>(session: T): T {
  const legacy = isLegacySession(session);
  const provider = typeof session.provider === "string" && session.provider.trim()
    ? session.provider
    : legacy ? "legacy" : FARO_PROVIDER;
  const model = typeof session.model === "string" && session.model.trim()
    ? session.model
    : legacy ? "历史助教" : FARO_MODEL;
  const state = ["running", "waiting_input", "stopped", "failed", "archived"].includes(session.state)
    ? session.state
    : legacy ? "archived" : "waiting_input";
  const lastEventSequence = Number.isSafeInteger(session.last_event_sequence)
    && session.last_event_sequence >= 0
    ? session.last_event_sequence
    : 0;
  return {
    ...session,
    title: typeof session.title === "string" && session.title.trim()
      ? session.title
      : "历史助教会话",
    provider,
    model,
    state,
    last_event_sequence: lastEventSequence,
    is_legacy: legacy,
  };
}

function isFaroSession(session: AgentSessionSummary): boolean {
  return !isLegacySession(session)
    && session.provider === FARO_PROVIDER
    && session.model === FARO_MODEL;
}

function isWritableSession(session: AgentSessionSummary): boolean {
  return isFaroSession(session)
    && session.state !== "failed"
    && session.state !== "archived"
    && session.state !== "stopped";
}

function asReadOnlyHistory<T extends AgentSessionSummary>(session: T): T {
  const normalized = normalizeSession(session);
  return isFaroSession(normalized)
    ? normalized
    : { ...normalized, is_legacy: true, legacy: true };
}

function normalizeSessions(
  sessions: readonly AgentSessionSummary[],
  knowledgeBaseId: string,
): AgentSessionSummary[] {
  return sessions
    .filter((session) => session.knowledge_base_id === knowledgeBaseId)
    .map(asReadOnlyHistory);
}

function legacyView(session: AgentSession): AgentView {
  const next = emptyAgentView();
  next.sessionState = session.state;
  next.messages = (Array.isArray(session.messages) ? session.messages : []).flatMap(
    (message, index) => {
      if (
        !message
        || (message.role !== "user" && message.role !== "assistant")
        || typeof message.content !== "string"
      ) {
        return [];
      }
      const id = typeof message.id === "string" && message.id
        ? message.id
        : `legacy-${session.id}-${index}`;
      return [{
        id,
        eventId: id,
        turnId: null,
        role: message.role,
        text: message.content,
        streaming: false,
      }];
    },
  );
  return next;
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

const AGENT_CAPABILITY_PREFERENCE_KEY = "agent-capability-preferences-v1";
const AGENT_CAPABILITY_KEYS = [
  "mcp_enabled",
  "skills_enabled",
  "subagents_enabled",
  "web_enabled",
] as const;

type AgentCapabilityPreference = Pick<
  AgentSettingsValue,
  (typeof AGENT_CAPABILITY_KEYS)[number]
>;

function capabilityPreferenceOf(value: AgentSettingsValue): AgentCapabilityPreference {
  return {
    mcp_enabled: value.mcp_enabled === true,
    skills_enabled: value.skills_enabled === true,
    subagents_enabled: value.subagents_enabled === true,
    web_enabled: value.web_enabled === true,
  };
}

function readCapabilityPreference(storageKey: string): AgentCapabilityPreference | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(storageKey);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!AGENT_CAPABILITY_KEYS.every((key) => typeof parsed[key] === "boolean")) return null;
    return capabilityPreferenceOf(parsed as AgentSettingsValue);
  } catch {
    return null;
  }
}

function mergeCapabilityPreference(
  value: AgentSettingsValue,
  preference: AgentCapabilityPreference | null,
): AgentSettingsValue {
  return fixedAgentServiceSettings(preference ? { ...value, ...preference } : value);
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
    () => linkedContexts ?? [{
      knowledge_base_id: knowledgeBase.id,
      label: `知识库：${knowledgeBase.name}`,
    }],
    [knowledgeBase.id, knowledgeBase.name, linkedContexts],
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
  const capabilityPreferenceKey = `${AGENT_CAPABILITY_PREFERENCE_KEY}:${knowledgeBase.id}`;

  const mountedRef = useRef(false);
  const knowledgeBaseIdRef = useRef(knowledgeBase.id);
  knowledgeBaseIdRef.current = knowledgeBase.id;
  const sessionIdRef = useRef<string | null>(null);
  const settingsRef = useRef<AgentSettingsValue>(fixedAgentServiceSettings({}));
  const settingsRevisionRef = useRef(0);
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
    session: AgentSessionSummary,
    controller: AbortController,
    readOnly = false,
  ) {
    const sessionId = session.id;
    closeConnection();
    replayRef.current?.abort();
    replayRef.current = controller;
    publishView(emptyAgentView());
    setConnection(null);

    if (isLegacySession(session)) {
      publishView(legacyView(session as AgentSession));
      persistCursor(sessionId, 0);
      return;
    }

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
    const created = await agentApi.create({
      knowledge_base_id: knowledgeBase.id,
      provider: FARO_PROVIDER,
      model: FARO_MODEL,
      context_window: FARO_CONTEXT_WINDOW,
      title: knowledgeBase.name,
      linked_contexts: defaultLinkedContexts,
    }, controller.signal);
    return normalizeSession({
      ...created,
      knowledge_base_id: created.knowledge_base_id ?? knowledgeBase.id,
      space_id: created.space_id ?? space.id,
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    bootstrapRef.current?.abort();
    bootstrapRef.current = controller;
    abortActions();
    settingsRevisionRef.current += 1;
    replayRef.current?.abort();
    closeConnection();
    sessionIdRef.current = null;
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      setSelectedSessionId(null);
      setReadOnlyHistorySelected(false);
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
        const safeSettings = mergeCapabilityPreference(
          loadedSettings,
          readCapabilityPreference(capabilityPreferenceKey),
        );
        settingsRef.current = safeSettings;
        setSettings(safeSettings);
        setDiagnostics(loadedDiagnostics);

        const nextSessions = normalizeSessions(loadedSessions, knowledgeBase.id);
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
        await replaySession(selected, controller);
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
      abortActions();
      closeConnection();
    };
    // A knowledge-base change deliberately starts a fresh controller lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capabilityPreferenceKey, knowledgeBase.id, retryGeneration]);


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

  function abortActions() {
    for (const controller of actionControllersRef.current) controller.abort();
    actionControllersRef.current.clear();
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
      if (controller.signal.aborted || selected.knowledge_base_id !== knowledgeBase.id) return;
      const safeSelected = asReadOnlyHistory(selected);
      setSessions((current) => upsertSession(current, safeSelected));
      setCurrentSession(safeSelected);
      await replaySession(safeSelected, controller, !isWritableSession(safeSelected));
      if (!controller.signal.aborted) closeSettings();
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
      await replaySession(created, controller);
      if (!controller.signal.aborted) closeSettings();
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
      if (controller.signal.aborted) return;
      updateSessionState(sessionId, "archived");
      if (sessionIdRef.current === sessionId) {
        closeConnection();
        setConnection(null);
        setReadOnlyHistorySelected(true);
      }
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function stopSession(sessionId: string) {
    const controller = actionController();
    try {
      await agentApi.stop(sessionId, controller.signal);
      if (controller.signal.aborted) return;
      updateSessionState(sessionId, "stopped");
      if (sessionIdRef.current === sessionId) {
        closeConnection();
        setConnection(null);
        setReadOnlyHistorySelected(true);
      }
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function forkSession(sessionId: string, afterSequence: number) {
    const controller = actionController();
    try {
      const branched = await agentApi.fork(
        sessionId,
        { checkpoint_id: `sequence:${afterSequence}` },
        controller.signal,
      );
      if (controller.signal.aborted || !branched) return;
      const safeBranched = asReadOnlyHistory({
        ...branched,
        knowledge_base_id: branched.knowledge_base_id ?? knowledgeBase.id,
        space_id: branched.space_id ?? space.id,
      });
      setSessions((current) => upsertSession(current, safeBranched));
      setCurrentSession(safeBranched);
      await replaySession(safeBranched, controller, !isWritableSession(safeBranched));
      if (!controller.signal.aborted) closeSettings();
    } catch (error) {
      if (!controller.signal.aborted) setRuntimeFailure(failureOf(error));
    } finally {
      finishAction(controller);
    }
  }

  async function send(request: AgentSendRequest) {
    const knowledgeBaseId = knowledgeBase.id;
    const sessionId = sessionIdRef.current;
    const selected = sessions.find((session) => (
      session.id === sessionId && session.knowledge_base_id === knowledgeBaseId
    ));
    if (!sessionId || !selected || !isWritableSession(selected)) return;
    const controller = actionController();
    const idempotencyKey = randomIdempotencyKey();
    setRuntimeFailure(null);
    setFailedTurn(null);
    try {
      await agentApi.send(sessionId, request, idempotencyKey, controller.signal);
      if (
        controller.signal.aborted
        || knowledgeBaseIdRef.current !== knowledgeBaseId
        || sessionIdRef.current !== sessionId
      ) return;
      updateSessionState(sessionId, "running");
    } catch (error) {
      if (
        controller.signal.aborted
        || knowledgeBaseIdRef.current !== knowledgeBaseId
        || sessionIdRef.current !== sessionId
      ) return;
      setFailedTurn({ knowledgeBaseId, sessionId, request, idempotencyKey });
      setRuntimeFailure(failureOf(error));
      updateSessionState(sessionId, "failed");
    } finally {
      finishAction(controller);
    }
  }

  async function retryRuntime() {
    const turn = failedTurn;
    if (!turn) {
      setRetryGeneration((current) => current + 1);
      return;
    }
    const selected = sessions.find((session) => (
      session.id === turn.sessionId
      && session.knowledge_base_id === turn.knowledgeBaseId
      && isFaroSession(session)
      && session.state !== "archived"
      && session.state !== "stopped"
    ));
    if (
      !selected
      || turn.knowledgeBaseId !== knowledgeBase.id
      || knowledgeBaseIdRef.current !== turn.knowledgeBaseId
      || sessionIdRef.current !== turn.sessionId
    ) {
      setRuntimeFailure(null);
      setFailedTurn(null);
      return;
    }
    const controller = actionController();
    setRetryingFailedTurn(true);
    try {
      await agentApi.send(
        turn.sessionId,
        turn.request,
        turn.idempotencyKey,
        controller.signal,
      );
      if (
        controller.signal.aborted
        || knowledgeBaseIdRef.current !== turn.knowledgeBaseId
        || sessionIdRef.current !== turn.sessionId
      ) return;
      setRuntimeFailure(null);
      setFailedTurn(null);
      updateSessionState(turn.sessionId, "running");
    } catch (error) {
      if (
        controller.signal.aborted
        || knowledgeBaseIdRef.current !== turn.knowledgeBaseId
        || sessionIdRef.current !== turn.sessionId
      ) return;
      setRuntimeFailure(failureOf(error));
      updateSessionState(turn.sessionId, "failed");
    } finally {
      finishAction(controller);
      if (knowledgeBaseIdRef.current === turn.knowledgeBaseId) {
        setRetryingFailedTurn(false);
      }
    }
  }
  async function updateSettings(value: AgentSettingsValue) {
    const controller = actionController();
    const safeValue = fixedAgentServiceSettings(value);
    const revision = settingsRevisionRef.current + 1;
    settingsRevisionRef.current = revision;
    settingsRef.current = safeValue;
    setSettings(safeValue);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(
        capabilityPreferenceKey,
        JSON.stringify(capabilityPreferenceOf(safeValue)),
      );
    }
    try {
      const saved = await agentApi.updateSettings(safeValue as AgentApiSettings, controller.signal);
      if (!controller.signal.aborted && settingsRevisionRef.current === revision) {
        const safeSaved = mergeCapabilityPreference(
          saved,
          capabilityPreferenceOf(settingsRef.current),
        );
        settingsRef.current = safeSaved;
        setSettings(safeSaved);
      }
    } catch {
      // The capability preference remains active in this browser even if the
      // deployment only exposes read-only capability defaults.
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
                  onFork={forkSession}
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