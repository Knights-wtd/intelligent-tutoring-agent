import { apiBaseUrl, apiUrl } from "@/lib/api-base";
import { parseAgentEvent } from "./agent-events";
import type { AgentEventEnvelope, AgentSessionState } from "./agent-events";

export type { AgentEventEnvelope, AgentSessionState } from "./agent-events";

export interface AgentSessionSummary {
  id: string;
  title: string;
  provider: string;
  model: string;
  state: AgentSessionState;
  last_event_sequence: number;
  is_legacy: boolean;
}

export interface AgentSession extends AgentSessionSummary {
  knowledge_base_id?: string | null;
  permission_mode?: "bypassPermissions";
  context_window?: number;
  parent_session_id?: string | null;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface AgentCreateRequest {
  knowledge_base_id: string;
  provider: string;
  model: string;
  context_window?: number;
  title?: string;
  linked_contexts?: AgentLinkedContext[];
}

export interface AgentLinkedContext {
  knowledge_base_id?: string;
  vault_file_id?: string;
  label?: string;
  source_name?: string;
  path?: string;
  heading?: string;
  selection?: string;
}

export interface AgentAttachmentReference {
  id: string;
  name?: string;
  media_type?: string;
}

export interface AgentSendRequest {
  text: string;
  linked_contexts?: AgentLinkedContext[];
  attachments?: AgentAttachmentReference[];
  skill?: string;
  agent?: string;
}

export interface AgentBranchRequest {
  after_sequence?: number;
  turn_id?: string;
  title?: string;
}

export interface AgentEventsResponse {
  events: AgentEventEnvelope[];
  last_sequence: number;
}

export interface AgentSettings {
  provider?: string;
  model?: string;
  context_window?: number;
  permission_mode?: "bypassPermissions";
  workspace_roots?: string[];
  mcp_enabled?: boolean;
  skills_enabled?: boolean;
  subagents_enabled?: boolean;
  web_enabled?: boolean;
  [key: string]: unknown;
}

export interface AgentMcpServer {
  id: string;
  name: string;
  state?: string;
  [key: string]: unknown;
}

export interface AgentSkill {
  id: string;
  name: string;
  description?: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface AgentDiagnostics {
  runtime?: Record<string, unknown>;
  providers?: unknown[];
  mcp?: unknown[];
  [key: string]: unknown;
}

export class AgentApiError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, detail?: string) {
    super(detail ?? "Agent request failed");
    this.name = "AgentApiError";
    this.status = status;
    this.detail = detail;
  }
}

function resource(value: string): string {
  return encodeURIComponent(value);
}

async function errorDetail(response: Response): Promise<string | undefined> {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) return undefined;
  try {
    const body = await response.json() as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : undefined;
  } catch {
    return undefined;
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) throw new AgentApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function post<T>(path: string, body?: unknown, headers?: HeadersInit): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    ...(headers ? { headers } : {}),
  });
}

export const agentApi = {
  create(input: AgentCreateRequest, signal?: AbortSignal): Promise<AgentSession> {
    return requestJson("/api/v1/agent/sessions", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    });
  },

  list(signal?: AbortSignal): Promise<AgentSessionSummary[]> {
    return requestJson("/api/v1/agent/sessions", { signal });
  },

  get(sessionId: string, signal?: AbortSignal): Promise<AgentSession> {
    return requestJson(`/api/v1/agent/sessions/${resource(sessionId)}`, { signal });
  },

  archive(sessionId: string, signal?: AbortSignal): Promise<void> {
    return requestJson<void>(`/api/v1/agent/sessions/${resource(sessionId)}/archive`, {
      method: "POST",
      signal,
    });
  },

  send(
    sessionId: string,
    input: AgentSendRequest,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    const { text: prompt, ...context } = input;
    return requestJson(`/api/v1/agent/sessions/${resource(sessionId)}/turns`, {
      method: "POST",
      body: JSON.stringify({
        prompt,
        ...context,
        ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
      }),
      signal,
    });
  },

  stop(sessionId: string): Promise<AgentSession> {
    return post(`/api/v1/agent/sessions/${resource(sessionId)}/stop`);
  },

  resume(sessionId: string): Promise<AgentSession> {
    return post(`/api/v1/agent/sessions/${resource(sessionId)}/resume`);
  },

  rewind(sessionId: string, input: AgentBranchRequest): Promise<AgentSession> {
    return post(`/api/v1/agent/sessions/${resource(sessionId)}/rewind`, input);
  },

  fork(sessionId: string, input: AgentBranchRequest = {}): Promise<AgentSession> {
    return post(`/api/v1/agent/sessions/${resource(sessionId)}/fork`, input);
  },

  async events(sessionId: string, after = 0, signal?: AbortSignal): Promise<AgentEventsResponse> {
    const response = await requestJson<unknown>(
      `/api/v1/agent/sessions/${resource(sessionId)}/events?after=${encodeURIComponent(String(after))}`,
      { signal },
    );
    if (Array.isArray(response)) {
      const events = response.map(parseAgentEvent);
      return {
        events,
        last_sequence: events.at(-1)?.sequence ?? after,
      };
    }
    if (!response || typeof response !== "object") {
      throw new TypeError("agent events response must be an array or replay object");
    }
    const replay = response as Record<string, unknown>;
    if (!Array.isArray(replay.events) || !Number.isSafeInteger(replay.last_sequence)) {
      throw new TypeError("agent events replay object is invalid");
    }
    return {
      events: replay.events.map(parseAgentEvent),
      last_sequence: Number(replay.last_sequence),
    };
  },

  settings(signal?: AbortSignal): Promise<AgentSettings> {
    return requestJson("/api/v1/agent/settings", { signal });
  },

  updateSettings(input: AgentSettings, signal?: AbortSignal): Promise<AgentSettings> {
    return requestJson("/api/v1/agent/settings", {
      method: "PUT",
      body: JSON.stringify(input),
      signal,
    });
  },

  mcp(signal?: AbortSignal): Promise<AgentMcpServer[]> {
    return requestJson("/api/v1/agent/mcp", { signal });
  },

  skills(signal?: AbortSignal): Promise<AgentSkill[]> {
    return requestJson("/api/v1/agent/skills", { signal });
  },

  diagnostics(signal?: AbortSignal): Promise<AgentDiagnostics> {
    return requestJson("/api/v1/agent/diagnostics", { signal });
  },

  async sidecar(
    sidecarId: string,
    options: { range?: string; signal?: AbortSignal } = {},
  ): Promise<Response> {
    const headers = new Headers();
    if (options.range) headers.set("Range", options.range);
    const response = await fetch(apiUrl(`/api/v1/agent/sidecars/${resource(sidecarId)}`), {
      credentials: "include",
      headers,
      signal: options.signal,
    });
    if (!response.ok) throw new AgentApiError(response.status, await errorDetail(response));
    return response;
  },
};

function websocketBase(explicit?: string): string {
  const configured = explicit ?? apiBaseUrl;
  if (configured) return configured;
  if (typeof window !== "undefined") return window.location.origin;
  throw new Error("A FastAPI base URL is required outside the browser");
}

export function agentWebSocketUrl(
  sessionId: string,
  after: number,
  baseUrl?: string,
): string {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new RangeError("after must be a non-negative safe integer");
  }
  const url = new URL(
    `/api/v1/agent/ws/${resource(sessionId)}?after=${after}`,
    websocketBase(baseUrl),
  );
  if (url.protocol === "http:") url.protocol = "ws:";
  else if (url.protocol === "https:") url.protocol = "wss:";
  else if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new TypeError("FastAPI base URL must use HTTP(S) or WS(S)");
  }
  return url.toString();
}

export type AgentConnectionStatus =
  | "connecting"
  | "open"
  | "reconnecting"
  | "unauthorized"
  | "error"
  | "closed";

export interface AgentConnectionState {
  status: AgentConnectionStatus;
  attempt: number;
  after: number;
  code?: number;
  error?: Error;
}

export interface AgentEventConnection {
  readonly after: number;
  close(): void;
}

interface AgentWebSocketLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(code?: number, reason?: string): void;
}

type AgentWebSocketConstructor = new (url: string | URL) => AgentWebSocketLike;

export interface AgentConnectionOptions {
  apiBaseUrl?: string;
  WebSocketImpl?: AgentWebSocketConstructor;
  reconnectDelayMs?: (attempt: number) => number;
  pollIntervalMs?: number;
  setTimeoutImpl?: typeof globalThis.setTimeout;
  clearTimeoutImpl?: typeof globalThis.clearTimeout;
}

const UNAUTHORIZED_CLOSE_CODES = new Set([401, 403, 1008, 4401, 4403]);

function defaultReconnectDelay(attempt: number): number {
  return Math.min(30_000, 500 * 2 ** Math.max(0, attempt - 1));
}

export function connectAgentEvents(
  sessionId: string,
  after: number,
  onEvent: (event: AgentEventEnvelope) => void,
  onState: (state: AgentConnectionState) => void,
  options: AgentConnectionOptions = {},
): AgentEventConnection {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new RangeError("after must be a non-negative safe integer");
  }

  const useSameOriginPolling = options.apiBaseUrl === undefined
    && options.WebSocketImpl === undefined
    && apiBaseUrl === "";
  const delayFor = options.reconnectDelayMs ?? defaultReconnectDelay;
  const schedule = options.setTimeoutImpl ?? globalThis.setTimeout.bind(globalThis);
  const cancel = options.clearTimeoutImpl ?? globalThis.clearTimeout.bind(globalThis);
  let cursor = after;
  let attempt = 0;
  let stopped = false;

  const emitState = (state: Omit<AgentConnectionState, "after">) => {
    onState({ ...state, after: cursor });
  };

  if (useSameOriginPolling) {
    const pollIntervalMs = options.pollIntervalMs ?? 500;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let pollController: AbortController | null = null;

    const schedulePoll = (delayMs: number) => {
      if (stopped) return;
      pollTimer = schedule(() => {
        pollTimer = null;
        void poll();
      }, delayMs);
    };

    const poll = async () => {
      if (stopped) return;
      const controller = new AbortController();
      pollController = controller;
      try {
        const replay = await agentApi.events(sessionId, cursor, controller.signal);
        if (stopped) return;
        for (const incoming of replay.events) {
          if (incoming.session_id !== sessionId) {
            throw new TypeError("received event for a different session");
          }
          if (incoming.sequence <= cursor) continue;
          cursor = incoming.sequence;
          onEvent(incoming);
          if (stopped) return;
        }
        cursor = Math.max(cursor, replay.last_sequence);
        attempt = 0;
        emitState({ status: "open", attempt });
        schedulePoll(pollIntervalMs);
      } catch (caught) {
        if (stopped || (caught instanceof Error && caught.name === "AbortError")) return;
        const error = caught instanceof Error ? caught : new Error("Agent event polling failed");
        if (caught instanceof AgentApiError && (caught.status === 401 || caught.status === 403)) {
          stopped = true;
          emitState({ status: "unauthorized", attempt, code: caught.status, error });
          return;
        }
        attempt += 1;
        emitState({
          status: "reconnecting",
          attempt,
          error,
          ...(caught instanceof AgentApiError ? { code: caught.status } : {}),
        });
        schedulePoll(delayFor(attempt));
      } finally {
        if (pollController === controller) pollController = null;
      }
    };

    emitState({ status: "connecting", attempt });
    void poll();

    return {
      get after() {
        return cursor;
      },
      close() {
        if (stopped) return;
        stopped = true;
        if (pollTimer !== null) {
          cancel(pollTimer);
          pollTimer = null;
        }
        pollController?.abort();
        pollController = null;
        emitState({ status: "closed", attempt, code: 1000 });
      },
    };
  }

  const WebSocketImpl = options.WebSocketImpl
    ?? (globalThis.WebSocket as unknown as AgentWebSocketConstructor | undefined);
  if (!WebSocketImpl) throw new Error("WebSocket is not available");

  let socket: AgentWebSocketLike | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (stopped) return;
    emitState({ status: "connecting", attempt });
    socket = new WebSocketImpl(agentWebSocketUrl(sessionId, cursor, options.apiBaseUrl));

    socket.onopen = () => {
      attempt = 0;
      emitState({ status: "open", attempt });
    };
    socket.onmessage = (message) => {
      try {
        const raw = typeof message.data === "string" ? JSON.parse(message.data) : message.data;
        const incoming = parseAgentEvent(raw);
        if (incoming.session_id !== sessionId) {
          throw new TypeError("received event for a different session");
        }
        cursor = incoming.sequence;
        onEvent(incoming);
      } catch (caught) {
        const error = caught instanceof Error ? caught : new Error("Invalid agent event");
        emitState({ status: "error", attempt, error });
      }
    };
    socket.onerror = () => {
      emitState({ status: "error", attempt, error: new Error("Agent WebSocket failed") });
    };
    socket.onclose = (closeEvent) => {
      socket = null;
      if (stopped) return;
      if (UNAUTHORIZED_CLOSE_CODES.has(closeEvent.code)) {
        stopped = true;
        emitState({ status: "unauthorized", attempt, code: closeEvent.code });
        return;
      }
      attempt += 1;
      emitState({ status: "reconnecting", attempt, code: closeEvent.code });
      reconnectTimer = schedule(() => {
        reconnectTimer = null;
        connect();
      }, delayFor(attempt));
    };
  };

  connect();

  return {
    get after() {
      return cursor;
    },
    close() {
      if (stopped) return;
      stopped = true;
      if (reconnectTimer !== null) {
        cancel(reconnectTimer);
        reconnectTimer = null;
      }
      const active = socket;
      socket = null;
      active?.close(1000, "client closed");
      emitState({ status: "closed", attempt, code: 1000 });
    },
  };
}
